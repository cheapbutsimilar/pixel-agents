"""안드로이드 앱(Chaquopy)과 다운로드 엔진 사이의 다리.

PC/Termux 버전은 gallery-dl을 별도 프로세스로 실행하지만, 안드로이드 앱에는 실행할 수 있는 파이썬 파일이
따로 없다. 그래서 x_media_downloader.download()에 InProcessRunner를 넘겨 gallery-dl을 같은 프로세스 안에서
실행한다. 설정 생성·받은 기록·빠른 새로고침·오류 해석은 PC 버전과 같은 코드를 그대로 쓴다.

Kotlin 쪽에서 쓰는 함수: init, engine_version, parse_target, run_download, stop, update_engine, reset_engine
"""

import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

ENGINE_DIR_NAME = "engine"
# 사용할 엔진 파일 이름을 적어 두는 파일. 비어 있거나 없으면 앱에 들어 있는 기본 엔진을 쓴다.
ENGINE_CURRENT = "current.txt"
PYPI_URL = "https://pypi.org/pypi/gallery-dl/json"
NETWORK_TIMEOUT = 60
LOG_FORMAT = "[{name}][{levelname}] {message}"

# 안드로이드 앱에 맞는 오류 안내 (PC/Termux 문구 대신)
ANDROID_HINTS = {
    "login": (
        "X 로그인이 만료됐거나 잘못됐습니다. 앱의 '다시 로그인' 버튼을 눌러 X에 다시 로그인하세요. "
        "(쿠키를 직접 입력했다면 새 값으로 다시 입력하세요)"
    ),
    "engine": (
        "X에서 데이터를 받지 못했습니다. 인터넷 연결과 계정 아이디를 확인하고, 계속 실패하면 "
        "앱 아래쪽의 '엔진 업데이트'를 누른 뒤 다시 시도하세요."
    ),
}

_state = {"files_dir": None, "engine_wheel": None}
_run_lock = threading.Lock()  # 다운로드는 한 번에 하나만
_current = {"runner": None}


class StopRequested(BaseException):
    """사용자가 중지를 눌렀다. gallery-dl의 'except Exception'에 잡히지 않도록 BaseException을 상속한다."""


# ---------------------------------------------------------------------------
# 초기화 / 엔진
# ---------------------------------------------------------------------------


def init(files_dir: str) -> None:
    """앱 시작 시 한 번. gallery_dl을 import하기 전에 불러야 업데이트된 엔진이 적용된다."""
    _state["files_dir"] = files_dir
    os.environ["HOME"] = files_dir  # x_media_downloader가 import 시 Path.home()을 쓴다
    os.environ["XDG_CACHE_HOME"] = os.path.join(files_dir, "cache")
    tmp = os.path.join(files_dir, "tmp")
    os.makedirs(tmp, exist_ok=True)
    tempfile.tempdir = tmp  # 안드로이드에는 /tmp가 없다

    engine_dir = os.path.join(files_dir, ENGINE_DIR_NAME)
    chosen = _read_current(engine_dir)
    wheel = os.path.join(engine_dir, chosen) if chosen else ""
    if "gallery_dl" not in sys.modules and wheel and os.path.isfile(wheel) and _wheel_ok(wheel):
        sys.path.insert(0, wheel)
        _state["engine_wheel"] = wheel
    # 이전 엔진 파일 정리. 새로 시작한 이 프로세스는 아직 그 파일들을 쓰지 않으므로 지워도 안전하다.
    # (쓰고 있는 엔진 파일을 바꾸거나 지우면 나중에 불러오는 모듈이 깨지므로, 바꾸기는 항상 새 이름으로 하고
    #  지우기는 다음 시작 때만 한다)
    _cleanup_engine_dir(engine_dir, keep=_state["engine_wheel"])


def _read_current(engine_dir: str) -> str:
    try:
        with open(os.path.join(engine_dir, ENGINE_CURRENT), encoding="utf-8") as fp:
            name = fp.read().strip()
    except OSError:
        return ""
    # 경로 조작 방지: 엔진 폴더 안의 파일 이름만
    return name if name and os.path.basename(name) == name else ""


def _write_current(engine_dir: str, name: str) -> None:
    os.makedirs(engine_dir, exist_ok=True)
    tmp = os.path.join(engine_dir, ENGINE_CURRENT + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fp:
        fp.write(name)
    os.replace(tmp, os.path.join(engine_dir, ENGINE_CURRENT))


def _cleanup_engine_dir(engine_dir: str, keep) -> None:
    if not os.path.isdir(engine_dir):
        return
    keep_names = {ENGINE_CURRENT}
    if keep:
        keep_names.add(os.path.basename(keep))
    # 다음 시작 때 쓸 엔진(업데이트 직후 아직 재시작 전)은 남긴다
    pending = _read_current(engine_dir)
    if pending:
        keep_names.add(pending)
    for name in os.listdir(engine_dir):
        if name not in keep_names:
            try:
                os.remove(os.path.join(engine_dir, name))
            except OSError:
                pass


def _engine_dir() -> str:
    return os.path.join(_files_dir(), ENGINE_DIR_NAME)


def _version_from_wheel_name(name: str) -> str:
    match = re.match(r"gallery_dl-(.+)\.whl$", name or "")
    return match.group(1) if match else ""


def _files_dir() -> str:
    if not _state["files_dir"]:
        raise RuntimeError("android_bridge.init()을 먼저 불러야 합니다")
    return _state["files_dir"]


def _wheel_ok(path: str) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return "gallery_dl/__init__.py" in zf.namelist() and zf.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def engine_version() -> str:
    from gallery_dl import version

    origin = "업데이트됨" if _state["engine_wheel"] else "기본"
    text = f"{version.__version__} ({origin})"
    pending = _read_current(_engine_dir())
    active = os.path.basename(_state["engine_wheel"] or "")
    if pending != active:
        nxt = _version_from_wheel_name(pending) or "기본 엔진"
        text += f" — 앱을 다시 시작하면 {nxt} 적용"
    return text


def _version_tuple(text: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", text)[:4])


def _engine_result(message: str, restart: bool) -> str:
    return json.dumps({"message": message, "restart": restart}, ensure_ascii=False)


def update_engine() -> str:
    """PyPI에서 최신 gallery-dl을 받아 둔다. 적용하려면 앱을 다시 시작해야 한다.

    반환: JSON {"message": 사람이 읽을 결과, "restart": 다시 시작해야 적용되는지}. 실패하면 예외.
    """
    from gallery_dl import version as current

    with urllib.request.urlopen(PYPI_URL, timeout=NETWORK_TIMEOUT) as resp:
        info = json.load(resp)
    latest = info["info"]["version"]
    if _version_tuple(latest) <= _version_tuple(current.__version__):
        return _engine_result(f"이미 최신입니다 (gallery-dl {current.__version__})", False)
    engine_dir = _engine_dir()
    pending = _read_current(engine_dir)
    if _version_from_wheel_name(pending) == latest and os.path.isfile(os.path.join(engine_dir, pending)):
        return _engine_result(f"gallery-dl {latest}을(를) 이미 받아 두었습니다. 앱을 다시 시작하면 적용됩니다", True)

    wheel_info = next(
        (f for f in info["urls"] if f.get("packagetype") == "bdist_wheel" and f["filename"].endswith("-none-any.whl")),
        None,
    )
    if wheel_info is None:
        raise RuntimeError(f"gallery-dl {latest} 설치 파일을 찾지 못했습니다")

    os.makedirs(engine_dir, exist_ok=True)
    name = "gallery_dl-" + re.sub(r"[^0-9A-Za-z.]+", "_", latest) + ".whl"
    target = os.path.join(engine_dir, name)
    if _state["engine_wheel"] and os.path.basename(_state["engine_wheel"]) == name:
        return _engine_result(f"이미 gallery-dl {latest}을(를) 쓰고 있습니다", False)
    tmp = target + ".download"
    digest = hashlib.sha256()
    with urllib.request.urlopen(wheel_info["url"], timeout=NETWORK_TIMEOUT) as resp, open(tmp, "wb") as fp:
        while chunk := resp.read(65536):
            digest.update(chunk)
            fp.write(chunk)
    expected = wheel_info.get("digests", {}).get("sha256")
    if expected and digest.hexdigest() != expected:
        os.remove(tmp)
        raise RuntimeError("받은 파일이 손상됐습니다 (체크섬 불일치). 다시 시도하세요")
    if not _wheel_ok(tmp):
        os.remove(tmp)
        raise RuntimeError("받은 파일이 올바른 gallery-dl 설치 파일이 아닙니다")
    os.replace(tmp, target)
    _write_current(engine_dir, name)
    return _engine_result(f"gallery-dl {latest}을(를) 받았습니다. 앱을 다시 시작하면 적용됩니다", True)


def reset_engine() -> str:
    """앱에 들어 있는 기본 엔진으로 되돌린다. 지금 쓰는 엔진 파일은 다음 시작 때 지운다 (재시작 후 적용).

    반환: update_engine()과 같은 JSON.
    """
    engine_dir = _engine_dir()
    pending = _read_current(engine_dir)
    if not pending and not _state["engine_wheel"]:
        return _engine_result("이미 기본 엔진을 쓰고 있습니다", False)
    _write_current(engine_dir, "")
    if not _state["engine_wheel"]:
        return _engine_result("받아 둔 업데이트를 취소했습니다. 기본 엔진을 계속 씁니다", False)
    return _engine_result("기본 엔진으로 되돌렸습니다. 앱을 다시 시작하면 적용됩니다", True)


# ---------------------------------------------------------------------------
# 같은 프로세스 안에서 gallery-dl 실행
# ---------------------------------------------------------------------------


def _setup_logging_once() -> None:
    """gallery-dl main()의 initialize_logging()과 같은 준비 (소문자 레벨 이름, gallery-dl 로거 클래스)."""
    if _state.get("logging_ready"):
        return
    from gallery_dl import output

    for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL):
        logging.addLevelName(level, logging.getLevelName(level).lower())
    logging.Logger.manager.setLoggerClass(output.Logger)
    _state["logging_ready"] = True


class _LineHandler(logging.Handler):
    """gallery-dl 로그를 PC 버전과 같은 '[이름][레벨] 메시지' 줄로 넘긴다."""

    def __init__(self, on_line):
        super().__init__(logging.INFO)
        self.on_line = on_line
        self.setFormatter(logging.Formatter(LOG_FORMAT, style="{"))

    def emit(self, record):
        try:
            record.levelname = record.levelname.lower()
            for line in self.format(record).splitlines():
                if line.strip():
                    self.on_line(line)
        except StopRequested:
            raise
        except Exception:  # noqa: BLE001 — 로그 하나 때문에 다운로드가 멈추면 안 된다
            pass


def _make_runner_class():
    import x_media_downloader as xmd

    class InProcessRunner(xmd.ProcessRunner):
        """x_media_downloader.download()가 넘기는 명령줄을 해석해 gallery-dl을 같은 프로세스에서 실행한다."""

        def __init__(self):
            super().__init__()
            self._stop_event = threading.Event()
            self._thread_id = None

        def run(self, cmd, on_line):
            config_path = cmd[cmd.index("-c") + 1]
            url = cmd[-1]
            with self._lock:
                if self.stopped:
                    return -1
                self._thread_id = threading.get_ident()

            from gallery_dl import config, exception, job, output

            _setup_logging_once()
            # 이전 실행의 설정(예: 빠른 새로고침의 skip)이 남지 않도록 매번 비우고 다시 읽는다
            config.clear()
            config.load([config_path], strict=True)
            config.set(("cache",), "file", os.path.join(_files_dir(), "cache", "gallery-dl.sqlite3"))
            os.makedirs(os.path.join(_files_dir(), "cache"), exist_ok=True)

            def write(text):
                for line in text.splitlines():
                    if line.strip():
                        on_line(line)

            saved_write, saved_sleep = output.stdout_write, time.sleep
            download_thread = threading.get_ident()

            def interruptible_sleep(seconds):
                # 요청 한도 대기(최대 15분)도 중지 버튼에 바로 반응하도록. time.sleep은 프로세스 전체에서
                # 공유되므로 다운로드 스레드만 바꾸고, 다른 스레드는 원래 sleep을 그대로 쓴다.
                if threading.get_ident() != download_thread:
                    return saved_sleep(seconds)
                if self._stop_event.wait(max(0.0, seconds)):
                    raise StopRequested()
            handler = _LineHandler(on_line)
            root = logging.getLogger()
            saved_level = root.level
            output.stdout_write = write
            time.sleep = interruptible_sleep
            root.addHandler(handler)
            root.setLevel(logging.INFO)
            try:
                return job.DownloadJob(url).run()
            except exception.NoExtractorError:
                on_line(f"[gallery-dl][error] 지원하지 않는 주소입니다: {url}")
                return 64
            except exception.ControlException:
                return 0
            except StopRequested:
                return 130
            finally:
                with self._lock:
                    self._thread_id = None
                output.stdout_write, time.sleep = saved_write, saved_sleep
                root.removeHandler(handler)
                root.setLevel(saved_level)

        def stop(self):
            with self._lock:
                self.stopped = True
                self._stop_event.set()
                if self._thread_id is not None:
                    import ctypes

                    ctypes.pythonapi.PyThreadState_SetAsyncExc(
                        ctypes.c_ulong(self._thread_id), ctypes.py_object(StopRequested)
                    )

    return InProcessRunner


def parse_target(raw: str) -> str:
    """입력값/공유 문구 → 대상 (잘못되면 ValueError, Kotlin에는 PyException으로 전달)."""
    import x_media_downloader as xmd

    return xmd.parse_target(raw)


def run_download(staging_dir: str, options_json: str, listener) -> str:
    """다운로드를 실행하고 결과를 JSON 문자열로 돌려준다. 호출한 스레드에서 끝날 때까지 실행된다.

    options_json: {"target": 입력값, "media", "retweets", "quick_refresh", "auth_token", "ct0"}
    listener: Kotlin 객체. onEvent(kind, text) / onFile(absolute_path, folder) 를 부른다.
      - kind: file / skip / error / warning / info (PC 버전과 같음)
      - onFile: 받은 파일을 사진 앱(MediaStore)에 옮기라는 신호. folder는 bookmarks 또는 계정 아이디.
    """
    import x_media_downloader as xmd

    xmd.HINTS.update(ANDROID_HINTS)
    xmd.SHOW_OUTPUT_DIR = False  # 사용자가 열 수 없는 앱 내부 폴더라 보여주지 않는다
    opts_in = json.loads(options_json)
    if not _run_lock.acquire(blocking=False):
        raise RuntimeError("이미 다운로드가 진행 중입니다")
    try:
        opts = xmd.Options(
            target=xmd.parse_target(opts_in.get("target", "")),
            output_dir=staging_dir,
            media=opts_in.get("media", xmd.MEDIA_ALL),
            retweets=bool(opts_in.get("retweets", False)),
            quick_refresh=bool(opts_in.get("quick_refresh", True)),
            cookie_mode=xmd.COOKIE_MANUAL,
            auth_token=opts_in.get("auth_token", ""),
            ct0=opts_in.get("ct0", ""),
            remember_login=False,
        )
        base = xmd.output_base(opts)

        def on_event(kind, text):
            if kind == "file":
                rel = text
                folder = rel.replace("\\", "/").split("/", 1)[0] if "/" in rel.replace("\\", "/") else ""
                listener.onFile(os.path.join(str(base), rel), folder)
            listener.onEvent(kind, text)

        runner = _make_runner_class()()
        _current["runner"] = runner
        try:
            result = xmd.download(opts, on_event, runner)
        except StopRequested:  # 중지 요청이 gallery-dl 밖(정리 코드)에서 도착한 경우
            result = xmd.Result(returncode=130, stopped=True)
        finally:
            _current["runner"] = None
        return json.dumps(
            {
                "target": opts.target,
                "downloaded": result.downloaded,
                "skipped": result.skipped,
                "errors": result.errors,
                "returncode": result.returncode,
                "stopped": result.stopped,
                "auth_error": result.auth_error,
                "quick": result.quick,
                "summary": result.summary(),
            },
            ensure_ascii=False,
        )
    finally:
        _run_lock.release()


def stop() -> bool:
    runner = _current["runner"]
    if runner is None:
        return False
    runner.stop()
    return True
