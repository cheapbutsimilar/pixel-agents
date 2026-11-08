#!/usr/bin/env python3
"""X(트위터) 미디어 다운로더.

내 북마크 또는 특정 계정의 모든 게시물에서 사진/동영상을 내려받는다.

실제 수집과 다운로드는 gallery-dl(https://github.com/mikf/gallery-dl)이 맡고,
이 파일은 설정을 만들어 gallery-dl을 실행하고 진행 상황을 보여주는 얇은 래퍼다.
X 내부 API가 바뀌어 다운로드가 실패하면 gallery-dl만 최신으로 올리면 된다:

    python -m pip install --upgrade gallery-dl

사용법:
    python x_media_downloader.py                  # GUI 실행 (휴대폰·서버에서는 글자 메뉴)
    python x_media_downloader.py bookmarks        # 내 북마크 (CLI)
    python x_media_downloader.py @계정아이디      # 특정 계정 (CLI)
    python x_media_downloader.py --help           # 전체 옵션
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter import font as tkfont
    from tkinter.scrolledtext import ScrolledText
except ImportError:  # 일부 리눅스 배포판은 python3-tk 패키지를 따로 설치해야 함
    tk = None

APP_TITLE = "X 미디어 다운로더"
SETTINGS_FILE = Path.home() / ".x-media-downloader" / "settings.json"

# 안드로이드 공용 '다운로드' 폴더. Termux 홈 폴더는 앱 전용이라 갤러리·내 파일 앱에서 보이지 않는다.
ANDROID_DOWNLOAD_DIR = Path("/storage/emulated/0/Download")


def is_android() -> bool:
    """안드로이드(Termux)에서 실행 중인지."""
    return hasattr(sys, "getandroidapilevel") or "com.termux" in os.environ.get("PREFIX", "")


def default_output_dir() -> str:
    if is_android():
        return str(ANDROID_DOWNLOAD_DIR / "x-media")
    return str(Path.home() / "Downloads" / "x-media")


DEFAULT_OUTPUT_DIR = default_output_dir()

BOOKMARKS = "bookmarks"

MEDIA_ALL = "all"
MEDIA_PHOTOS = "photos"
MEDIA_VIDEOS = "videos"

COOKIE_MANUAL = "manual"
COOKIE_BROWSER = "browser"
COOKIE_FILE = "file"

BROWSERS = ("firefox", "chrome", "edge", "brave", "opera", "vivaldi", "chromium", "safari")

# 빠른 새로고침: 전체 받기를 한 번 끝낸 대상은, 이미 받은 파일이 이만큼 연속으로 나오면 멈춘다.
# 북마크(북마크한 순서)와 계정 타임라인(게시 순서) 모두 최신 항목이 맨 앞에 오므로 그 뒤는 이미 받은 것이다.
QUICK_REFRESH_SKIP_LIMIT = 20

# 받은 기록 폴더: <저장 폴더>/.download-history/
#   <대상>.sqlite3  받은 파일 목록 (게시물 ID 기준, gallery-dl archive)
#   <대상>.json     전체 받기를 끝낸 범위 (빠른 새로고침을 써도 되는지 판단)
HISTORY_DIR_NAME = ".download-history"

# 저장 경로: <저장 폴더>/bookmarks/... 또는 <저장 폴더>/<계정아이디>/...
FILENAME_FORMAT = "{date:%Y%m%d}_{author[name]}_{tweet_id}_{num}.{extension}"

LOG_MAX_LINES = 3000
GUI_POLL_MS = 100

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows에서 하위 프로세스 콘솔 창이 뜨지 않게

_SCREEN_NAME = re.compile(r"[A-Za-z0-9_]+")
_X_HOSTS = {
    "x.com",
    "www.x.com",
    "mobile.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
}
# x.com/<여기> 자리에 올 수 있지만 계정이 아닌 경로
_NON_USER_PATHS = {
    "home",
    "explore",
    "notifications",
    "messages",
    "search",
    "settings",
    "compose",
    "hashtag",
    "i",
    "intent",
    "login",
    "logout",
    "signup",
}
_LOG_LINE = re.compile(r"^\[[^\]]*\]\[(\w+)\]")


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------


@dataclass
class Options:
    target: str = BOOKMARKS  # BOOKMARKS 또는 계정 아이디(@ 없이)
    output_dir: str = DEFAULT_OUTPUT_DIR
    media: str = MEDIA_ALL  # MEDIA_ALL / MEDIA_PHOTOS / MEDIA_VIDEOS
    retweets: bool = False  # 계정 모드에서 리트윗한 게시물의 미디어도 받기
    quick_refresh: bool = True  # 전체 받기를 끝낸 대상은 새로 생긴 것만 확인
    cookie_mode: str = COOKIE_MANUAL
    auth_token: str = ""
    ct0: str = ""
    browser: str = "firefox"
    cookies_file: str = ""
    remember_login: bool = True


def load_settings() -> Options:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Options()
    if not isinstance(data, dict):
        return Options()
    defaults = Options()
    values = {}
    for f in fields(Options):
        value = data.get(f.name)
        if isinstance(value, type(getattr(defaults, f.name))):
            values[f.name] = value
    return Options(**values)


def save_settings(opts: Options) -> None:
    data = asdict(opts)
    if not opts.remember_login:
        data["auth_token"] = data["ct0"] = ""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    # 로그인 쿠키가 들어 있으므로 본인만 읽을 수 있게 만든다
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_FILE)


# ---------------------------------------------------------------------------
# 입력 해석 / gallery-dl 설정 생성
# ---------------------------------------------------------------------------


def parse_target(raw: str) -> str:
    """입력값을 BOOKMARKS 또는 계정 아이디로 바꾼다. 해석할 수 없으면 ValueError.

    허용: bookmarks, 북마크, https://x.com/i/bookmarks, @아이디, 아이디,
    https://x.com/아이디, twitter.com/아이디/media 등
    """
    text = raw.strip()
    if not text:
        raise ValueError("대상 계정을 입력하세요.")
    if text.lower() in ("bookmarks", "bookmark", "북마크"):
        return BOOKMARKS

    if text.startswith("@"):
        text = text[1:]
    elif "/" in text or "." in text:  # 아이디에는 / 와 . 이 들어갈 수 없으니 URL로 본다
        url = text if "://" in text else "https://" + text
        parsed = urlparse(url)
        if (parsed.hostname or "").lower() not in _X_HOSTS:
            raise ValueError(f"X(트위터) 주소가 아닙니다: {raw}")
        parts = [p for p in parsed.path.split("/") if p]
        if parts[:2] == ["i", "bookmarks"]:
            return BOOKMARKS
        if not parts or parts[0].lower() in _NON_USER_PATHS:
            raise ValueError(f"주소에서 계정 아이디를 찾을 수 없습니다: {raw}")
        text = parts[0]

    if not _SCREEN_NAME.fullmatch(text):
        raise ValueError(f"올바른 계정 아이디가 아닙니다: {raw}")
    return text


def target_url(target: str) -> str:
    if target == BOOKMARKS:
        return "https://x.com/i/bookmarks"
    # 프로필 주소를 주면 gallery-dl이 미디어 탭을 먼저 훑고, 그보다 오래된 게시물은
    # 검색으로 이어서 찾아 계정의 전체 게시물을 대상으로 한다.
    return f"https://x.com/{target}"


def clean_cookie_value(value: str, name: str) -> str:
    """복사·붙여넣기 실수(따옴표, 'auth_token=' 접두어, 공백)를 정리한다."""
    value = value.strip().strip("\"'").strip()
    prefix = name + "="
    if value.startswith(prefix):
        value = value[len(prefix) :].strip()
    return value.rstrip(";").strip()


def cookies_setting(opts: Options):
    """gallery-dl 'cookies' 설정값: dict(직접 입력) / list(브라우저) / str(cookies.txt 경로)."""
    if opts.cookie_mode == COOKIE_MANUAL:
        token = clean_cookie_value(opts.auth_token, "auth_token")
        if not token:
            raise ValueError(
                "auth_token 쿠키 값을 입력하세요.\n"
                "(x.com 로그인 → F12 → Application/저장소 → Cookies → https://x.com)"
            )
        cookies = {"auth_token": token}
        ct0 = clean_cookie_value(opts.ct0, "ct0")
        if ct0:
            cookies["ct0"] = ct0
        return cookies

    if opts.cookie_mode == COOKIE_BROWSER:
        browser = opts.browser.strip().lower()
        if browser not in BROWSERS:
            raise ValueError(f"지원하지 않는 브라우저입니다: {opts.browser}")
        # [브라우저, 프로필, 키링, 컨테이너, 도메인] — x.com 쿠키만 읽는다
        return [browser, None, None, None, ".x.com"]

    if opts.cookie_mode == COOKIE_FILE:
        if not opts.cookies_file.strip():
            raise ValueError("cookies.txt 파일을 선택하세요.")
        path = Path(opts.cookies_file.strip()).expanduser()
        if not path.is_file():
            raise ValueError(f"cookies.txt 파일을 찾을 수 없습니다: {path}")
        return str(path.resolve())

    raise ValueError(f"알 수 없는 쿠키 방식입니다: {opts.cookie_mode}")


def output_base(opts: Options) -> Path:
    return Path(opts.output_dir.strip()).expanduser().resolve()


def history_paths(base_dir: Path, target: str) -> tuple:
    """대상별 (받은 기록 DB, 상태 파일) 경로. 계정 아이디는 대소문자를 구분하지 않는다."""
    key = BOOKMARKS if target == BOOKMARKS else target.lower()
    directory = base_dir / HISTORY_DIR_NAME
    return directory / f"{key}.sqlite3", directory / f"{key}.json"


def run_scope(opts: Options) -> dict:
    """이번 실행이 받으려는 범위 (전체 받기 완료 기록과 비교용)."""
    return {"media": opts.media, "retweets": bool(opts.retweets and opts.target != BOOKMARKS)}


def scope_covered(done_scopes: list, scope: dict) -> bool:
    """끝낸 전체 받기 중 이번 범위를 모두 포함하는 것이 있으면 True.

    예) '사진만'으로 전체를 받은 뒤 '사진 + 동영상'으로 바꾸면 예전 동영상은 받은 적이 없으므로 False.
    """
    for done in done_scopes:
        media_ok = done.get("media") in (MEDIA_ALL, scope["media"])
        retweets_ok = bool(done.get("retweets")) or not scope["retweets"]
        if media_ok and retweets_ok:
            return True
    return False


def load_completed_scopes(state_path: Path) -> list:
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    scopes = data.get("full_scans") if isinstance(data, dict) else None
    return [s for s in scopes if isinstance(s, dict)] if isinstance(scopes, list) else []


def record_full_scan(state_path: Path, scope: dict) -> None:
    scopes = load_completed_scopes(state_path)
    if scope not in scopes:
        scopes.append(scope)
    state_path.write_text(json.dumps({"full_scans": scopes}, indent=2), encoding="utf-8")


def build_config(opts: Options, quick_refresh: bool = False) -> dict:
    """Options → gallery-dl 설정(JSON). 잘못된 입력이면 ValueError.

    quick_refresh=True면 이미 받은 파일이 연속으로 나올 때 멈춘다 (download()가 안전할 때만 켠다).
    """
    if opts.media not in (MEDIA_ALL, MEDIA_PHOTOS, MEDIA_VIDEOS):
        raise ValueError(f"알 수 없는 미디어 종류입니다: {opts.media}")
    if not opts.output_dir.strip():
        raise ValueError("저장 폴더를 지정하세요.")

    is_bookmarks = opts.target == BOOKMARKS
    twitter = {
        "cookies": cookies_setting(opts),
        "directory": [BOOKMARKS] if is_bookmarks else ["{user[name]}"],
        "filename": FILENAME_FORMAT,
        # 리트윗은 원본 게시물의 ID·날짜로 저장('original'). 북마크에는 해당 없음
        "retweets": "original" if (opts.retweets and not is_bookmarks) else False,
        "quoted": False,  # 인용된 남의 게시물은 받지 않음
        "text-tweets": False,
        "cards": False,
        "articles": False,
        "videos": opts.media != MEDIA_PHOTOS,
    }
    if opts.media == MEDIA_VIDEOS:
        # GIF도 X에서는 mp4 동영상으로 제공된다
        twitter["file-filter"] = "type in ('video', 'animated_gif')"

    base_dir = output_base(opts)
    archive_path, _ = history_paths(base_dir, opts.target)
    extractor = {
        "base-directory": str(base_dir),
        # 받은 기록(게시물 ID 기준): 파일을 옮기거나 지워도, 작성자가 아이디를 바꿔 파일 이름이
        # 달라져도 다시 받지 않는다. 'skip'도 기록해 기록이 생기기 전에 받아 둔 파일도 등록한다.
        "archive": str(archive_path),
        "archive-event": "file,skip",
        "twitter": twitter,
    }
    if quick_refresh:
        extractor["skip"] = f"abort:{QUICK_REFRESH_SKIP_LIMIT}"

    return {
        "extractor": extractor,
        # 받은 파일은 경로 한 줄, 건너뛴 파일은 '# 경로' 한 줄로 출력된다
        "output": {"mode": "pipe", "progress": False},
    }


def gallery_dl_command(config_path: str, url: str) -> list:
    # --config-ignore: 사용자의 기존 gallery-dl 설정 파일이 결과를 바꾸지 않도록 무시
    return [sys.executable, "-m", "gallery_dl", "--config-ignore", "-c", config_path, url]


def upgrade_command() -> list:
    return [sys.executable, "-m", "pip", "install", "--upgrade", "gallery-dl"]


def engine_version() -> str | None:
    """설치된 gallery-dl 버전 (없으면 None). 업데이트 직후에도 정확하도록 별도 프로세스로 확인."""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "gallery_dl", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    version = out.stdout.strip()
    return version if out.returncode == 0 and version else None


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def _strip_extended_prefix(path: str) -> str:
    return path[4:] if path.startswith("\\\\?\\") else path


def classify_line(line: str) -> tuple:
    """gallery-dl 출력 한 줄 → (종류, 표시할 텍스트).

    종류: 'file'(다운로드 완료), 'skip'(이미 받음), 'error', 'warning', 'info'
    """
    if line.startswith("# "):
        return "skip", _strip_extended_prefix(line[2:])
    match = _LOG_LINE.match(line)
    if match:
        level = match.group(1).lower()
        if level in ("error", "critical"):
            return "error", line
        if level == "warning":
            return "warning", line
        return "info", line
    if os.path.isabs(line) or line.startswith("\\\\?\\"):
        return "file", _strip_extended_prefix(line)
    return "info", line


def describe_exit(code: int) -> str:
    """gallery-dl 종료 코드(오류 종류별 비트 OR)를 사람이 읽을 설명으로."""
    if code == 0:
        return "완료"
    hints = []
    if code & 16:
        hints.append(
            "로그인 쿠키가 만료됐거나 잘못됐습니다. x.com에 다시 로그인한 뒤 auth_token/ct0를 새로 복사하세요. "
            "(계정 모드라면 비공개 계정이거나 나를 차단한 계정일 수도 있습니다)"
        )
    if code & 8:
        hints.append("X가 자동화 요청을 막았습니다. 잠시 후 다시 시도하세요.")
    if code & 4:
        hints.append(
            "X에서 데이터를 받지 못했습니다. 인터넷 연결과 계정 아이디를 확인하고, 계속 실패하면 "
            "'엔진 업데이트'(또는 --upgrade-engine)로 gallery-dl을 최신 버전으로 올린 뒤 다시 시도하세요."
        )
    if code & (32 | 64):
        hints.append("설정 또는 주소 오류입니다. 로그의 [error] 줄을 확인하세요.")
    if not hints:
        hints.append("로그의 [error] 줄을 확인하세요.")
    return f"오류 (종료 코드 {code}) — " + " ".join(hints)


class ProcessRunner:
    """서브프로세스를 실행해 출력을 한 줄씩 콜백으로 넘긴다. stop()은 다른 스레드에서 호출 가능."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self.stopped = False

    def run(self, cmd: list, on_line: Callable[[str], None]) -> int:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        with self._lock:
            if self.stopped:
                return -1
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=_NO_WINDOW,
            )
        proc = self._proc
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if line:
                    on_line(line)
        except BaseException:  # Ctrl+C 등으로 중단되면 하위 프로세스도 정리
            proc.kill()
            raise
        finally:
            proc.stdout.close()
        return proc.wait()

    def stop(self) -> None:
        with self._lock:
            self.stopped = True
            if self._proc is not None and self._proc.poll() is None:
                self._proc.terminate()


@dataclass
class Result:
    downloaded: int = 0
    skipped: int = 0
    errors: int = 0
    returncode: int = 0
    stopped: bool = False
    quick: bool = False  # 빠른 새로고침으로 실행됐는지

    def summary(self) -> str:
        counts = f"받음 {self.downloaded}개 · 건너뜀(이미 받음) {self.skipped}개"
        if self.stopped:
            return f"중지됨 — {counts}"
        return f"{describe_exit(self.returncode)} — {counts}"


def download(
    opts: Options,
    on_event: Callable[[str, str], None],
    runner: ProcessRunner | None = None,
) -> Result:
    """gallery-dl로 다운로드를 실행한다. on_event(종류, 텍스트)로 진행 상황을 알린다.

    입력이 잘못됐으면 아무것도 실행하지 않고 ValueError를 던진다.

    빠른 새로고침은 같은(또는 더 넓은) 범위로 전체 받기를 끝까지 마친 기록이 있을 때만 켠다.
    처음 받기가 중간에 끊긴 상태에서 켜면 앞쪽의 이미 받은 파일에서 멈춰 뒤쪽을 영영 못 받기 때문이다.
    """
    base_dir = output_base(opts)
    archive_path, state_path = history_paths(base_dir, opts.target)
    scope = run_scope(opts)
    quick = opts.quick_refresh and scope_covered(load_completed_scopes(state_path), scope)
    config = build_config(opts, quick_refresh=quick)  # 입력 검증 — 실패하면 아무것도 만들지 않음
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    runner = runner or ProcessRunner()
    result = Result(quick=quick)

    def handle(line: str) -> None:
        kind, text = classify_line(line)
        if kind in ("file", "skip"):
            if kind == "file":
                result.downloaded += 1
            else:
                result.skipped += 1
            try:  # 저장 폴더 기준 상대 경로로 짧게 표시 (휴대폰 화면에서도 읽기 쉽게)
                text = str(Path(text).relative_to(base_dir))
            except ValueError:
                pass
        elif kind == "error":
            result.errors += 1
        on_event(kind, text)

    # 설정 파일에 로그인 쿠키가 들어가므로 본인만 읽을 수 있는 임시 파일(mkstemp는 0600)에 쓰고 끝나면 지운다
    fd, config_path = tempfile.mkstemp(prefix="x-media-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(config, fp, ensure_ascii=False)
        url = target_url(opts.target)
        on_event("info", f"시작: {url}  →  {base_dir}")
        if quick:
            on_event(
                "info",
                f"빠른 새로고침: 새로 생긴 것만 받고, 이미 받은 파일이 연속 {QUICK_REFRESH_SKIP_LIMIT}개 나오면 멈춥니다.",
            )
        else:
            on_event("info", "전체 확인: 처음부터 끝까지 확인합니다. (이미 받은 파일은 건너뜀)")
        result.returncode = runner.run(gallery_dl_command(config_path, url), handle)
    finally:
        try:
            os.remove(config_path)
        except OSError:
            pass
    result.stopped = runner.stopped

    if not quick and result.returncode == 0 and not result.stopped:
        try:
            record_full_scan(state_path, scope)
        except OSError as exc:
            on_event("warning", f"전체 받기 완료 기록을 저장하지 못했습니다: {exc}")
        else:
            if opts.quick_refresh:
                on_event("info", "전체 받기를 끝냈습니다. 다음부터는 새로 생긴 것만 빠르게 확인합니다.")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="x_media_downloader.py",
        description=(
            "X(트위터) 북마크 또는 특정 계정의 사진/동영상을 내려받습니다. "
            "인자 없이 실행하면 GUI가, GUI를 쓸 수 없는 휴대폰(Termux)·서버에서는 글자 메뉴가 열립니다."
        ),
        epilog=(
            "로그인 쿠키를 한 번 GUI나 --save로 저장해 두면 이후엔 생략할 수 있습니다. "
            "auth_token은 환경변수 X_AUTH_TOKEN / X_CT0 로도 줄 수 있습니다."
        ),
    )
    p.add_argument("target", nargs="?", help="'bookmarks' 또는 계정 아이디(@name) / 프로필 주소")
    p.add_argument("-o", "--out", metavar="폴더", help=f"저장 폴더 (기본: {DEFAULT_OUTPUT_DIR})")
    p.add_argument("--only", choices=(MEDIA_PHOTOS, MEDIA_VIDEOS), help="사진만 또는 동영상만 받기")
    p.add_argument("--retweets", action="store_true", help="계정 모드에서 리트윗한 게시물의 미디어도 받기")
    p.add_argument(
        "--full",
        action="store_true",
        help=(
            "빠른 새로고침을 끄고 처음부터 끝까지 다시 확인 (이미 받은 파일은 그래도 건너뜀). "
            "기본은 전체 받기를 한 번 끝낸 대상이면 새로 생긴 것만 확인"
        ),
    )
    auth = p.add_argument_group("로그인 쿠키 (셋 중 하나)")
    auth.add_argument("--auth-token", metavar="값", help="x.com 쿠키 auth_token 값")
    auth.add_argument("--ct0", metavar="값", help="x.com 쿠키 ct0 값 (권장)")
    auth.add_argument("--browser", choices=BROWSERS, help="이 브라우저에 로그인된 쿠키 사용")
    auth.add_argument("--cookies", metavar="파일", help="Netscape 형식 cookies.txt 파일")
    p.add_argument("--save", action="store_true", help="이번 설정(로그인 쿠키 포함)을 저장해 다음에 재사용")
    p.add_argument("--gui", action="store_true", help="GUI 실행")
    p.add_argument("--menu", action="store_true", help="글자 메뉴로 실행")
    p.add_argument("--upgrade-engine", action="store_true", help="gallery-dl을 최신 버전으로 업데이트")
    return p


def options_from_args(args: argparse.Namespace, base: Options) -> Options:
    opts = Options(**asdict(base))
    opts.target = parse_target(args.target)
    if args.out:
        opts.output_dir = args.out
    opts.media = args.only or MEDIA_ALL
    opts.retweets = args.retweets
    opts.quick_refresh = not args.full

    auth_token = args.auth_token or os.environ.get("X_AUTH_TOKEN", "")
    ct0 = args.ct0 or os.environ.get("X_CT0", "")
    if args.browser:
        opts.cookie_mode, opts.browser = COOKIE_BROWSER, args.browser
    elif args.cookies:
        opts.cookie_mode, opts.cookies_file = COOKIE_FILE, args.cookies
    elif auth_token:
        # 새 auth_token에 저장돼 있던 다른 세션의 ct0를 섞지 않는다
        opts.cookie_mode, opts.auth_token, opts.ct0 = COOKIE_MANUAL, auth_token, ct0
    elif ct0:
        opts.ct0 = ct0
    return opts


_CLI_PREFIX = {"file": "[받음] ", "skip": "[건너뜀] ", "error": "", "warning": "", "info": ""}


def _console_safe_output() -> None:
    # 한국어 Windows 콘솔(cp949)에서 이모지 등이 섞인 로그가 출력 오류를 내지 않도록
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def _termux_command(name: str) -> None:
    """Termux 보조 명령(termux-wake-lock 등)이 있으면 실행한다. 실패해도 다운로드에는 영향 없음."""
    if not shutil.which(name):
        return
    try:
        subprocess.run([name], timeout=15, stdin=subprocess.DEVNULL, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass


def run_download_console(opts: Options) -> int:
    """터미널(명령줄·글자 메뉴)에서 다운로드를 실행하고 진행 상황을 출력한다."""
    if engine_version() is None:
        print("gallery-dl이 설치되어 있지 않습니다:  python -m pip install gallery-dl", file=sys.stderr)
        return 2

    runner = ProcessRunner()

    def on_event(kind: str, text: str) -> None:
        print(_CLI_PREFIX[kind] + text, flush=True)

    # 휴대폰 화면이 꺼져도 다운로드가 멈추지 않도록 (Termux 알림에 표시됨)
    android = is_android()
    if android:
        _termux_command("termux-wake-lock")
    try:
        result = download(opts, on_event, runner)
    except KeyboardInterrupt:
        runner.stop()
        print("\n중지됨")
        return 130
    except OSError as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        if android and isinstance(exc, PermissionError):
            print("저장소 권한이 없습니다. Termux에서 termux-setup-storage 를 실행하고 '허용'을 누르세요.", file=sys.stderr)
        return 1
    finally:
        if android:
            _termux_command("termux-wake-unlock")
    print(result.summary())
    return 0 if result.returncode == 0 else 1


def run_cli(args: argparse.Namespace) -> int:
    _console_safe_output()
    try:
        opts = options_from_args(args, load_settings())
        build_config(opts)  # 실행 전에 입력 검증
    except ValueError as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2
    if args.save:
        save_settings(opts)
        print(f"설정 저장: {SETTINGS_FILE}")
    return run_download_console(opts)


# ---------------------------------------------------------------------------
# 글자 메뉴 (휴대폰 Termux·서버처럼 GUI를 쓸 수 없는 곳)
# ---------------------------------------------------------------------------

MEDIA_LABELS = {MEDIA_ALL: "사진 + 동영상", MEDIA_PHOTOS: "사진만", MEDIA_VIDEOS: "동영상만(GIF 포함)"}
_YES = ("y", "yes", "ㅇ", "예", "네", "응")


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{prompt}{suffix}: ").strip() or default


def _ask_yes(prompt: str, default: bool) -> bool:
    answer = input(f"{prompt} ({'Y/n' if default else 'y/N'}): ").strip().lower()
    return default if not answer else answer in _YES


def _has_login(opts: Options) -> bool:
    try:
        cookies_setting(opts)
    except ValueError:
        return False
    return True


def _menu_login(opts: Options) -> None:
    print(
        "\n[로그인 쿠키 입력]\n"
        "x.com에 로그인된 브라우저의 쿠키 auth_token, ct0 값이 필요합니다. (README '로그인 쿠키 준비' 참고)\n"
        "Termux에서는 화면을 길게 눌러 '붙여넣기'(Paste)를 고르면 됩니다.\n"
    )
    while True:
        token = clean_cookie_value(_ask("auth_token"), "auth_token")
        if token:
            break
        print("auth_token은 꼭 필요합니다.")
    opts.cookie_mode = COOKIE_MANUAL
    opts.auth_token = token
    opts.ct0 = clean_cookie_value(_ask("ct0 (권장, 없으면 그냥 Enter)"), "ct0")
    opts.remember_login = _ask_yes("이 기기에 로그인 정보를 저장할까요?", True)


def _menu_options(opts: Options) -> None:
    print("\n[옵션] 그대로 두려면 Enter")
    choices = {"1": MEDIA_ALL, "2": MEDIA_PHOTOS, "3": MEDIA_VIDEOS}
    current = next((k for k, v in choices.items() if v == opts.media), "1")
    picked = _ask("받을 종류  1) 사진 + 동영상  2) 사진만  3) 동영상만", current)
    opts.media = choices.get(picked, opts.media)
    opts.retweets = _ask_yes("계정 모드에서 리트윗한 게시물도 받을까요?", opts.retweets)
    opts.quick_refresh = _ask_yes("빠른 새로고침을 쓸까요? (전체를 한 번 받은 뒤에는 새로 생긴 것만 확인)", opts.quick_refresh)
    opts.output_dir = _ask("저장 폴더", opts.output_dir)


def _save_quietly(opts: Options) -> None:
    try:
        save_settings(opts)
    except OSError as exc:
        print(f"(설정 저장 실패: {exc})")


def run_menu() -> int:
    _console_safe_output()
    opts = load_settings()
    try:
        while True:
            login = "저장됨" if _has_login(opts) else "없음"
            print(
                f"\n===== {APP_TITLE} =====\n"
                f"저장 폴더: {opts.output_dir}\n"
                f"받을 종류: {MEDIA_LABELS.get(opts.media, opts.media)} · 로그인: {login}\n"
                "  1) 내 북마크 받기\n"
                "  2) 특정 계정의 모든 게시물 받기\n"
                "  3) 로그인 쿠키 입력/변경\n"
                "  4) 옵션 (종류·리트윗·빠른 새로고침·저장 폴더)\n"
                "  5) 엔진 업데이트 (갑자기 안 될 때)\n"
                "  0) 끝내기"
            )
            choice = input("번호: ").strip()
            if choice in ("1", "2"):
                if not _has_login(opts):
                    _menu_login(opts)
                if choice == "1":
                    opts.target = BOOKMARKS
                else:
                    last = "" if opts.target == BOOKMARKS else opts.target
                    try:
                        opts.target = parse_target(_ask("계정 아이디 또는 프로필 주소 (예: @nasa)", last))
                    except ValueError as exc:
                        print(f"입력 오류: {exc}")
                        continue
                try:
                    build_config(opts)
                except ValueError as exc:
                    print(f"입력 오류: {exc}")
                    continue
                _save_quietly(opts)
                print()
                run_download_console(opts)
            elif choice == "3":
                _menu_login(opts)
                _save_quietly(opts)
            elif choice == "4":
                _menu_options(opts)
                _save_quietly(opts)
            elif choice == "5":
                run_upgrade_cli()
            elif choice in ("0", "q", "Q"):
                return 0
            else:
                print("1~5 또는 0을 입력하세요.")
    except (EOFError, KeyboardInterrupt):
        print()
        return 0


def run_upgrade_cli() -> int:
    return ProcessRunner().run(upgrade_command(), print)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


def open_folder(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class App:
    def __init__(self, root) -> None:
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.runner: ProcessRunner | None = None
        self.counts = {"file": 0, "skip": 0, "error": 0}

        root.title(APP_TITLE)
        root.minsize(680, 640)

        opts = load_settings()
        self.v_target_kind = tk.StringVar(value="bookmarks" if opts.target == BOOKMARKS else "user")
        self.v_username = tk.StringVar(value="" if opts.target == BOOKMARKS else opts.target)
        self.v_cookie_mode = tk.StringVar(value=opts.cookie_mode)
        self.v_auth_token = tk.StringVar(value=opts.auth_token)
        self.v_ct0 = tk.StringVar(value=opts.ct0)
        self.v_show_tokens = tk.BooleanVar(value=False)
        self.v_browser = tk.StringVar(value=opts.browser)
        self.v_cookies_file = tk.StringVar(value=opts.cookies_file)
        self.v_remember = tk.BooleanVar(value=opts.remember_login)
        self.v_media = tk.StringVar(value=opts.media)
        self.v_retweets = tk.BooleanVar(value=opts.retweets)
        self.v_quick_refresh = tk.BooleanVar(value=opts.quick_refresh)
        self.v_output_dir = tk.StringVar(value=opts.output_dir)
        self.v_status = tk.StringVar(value="대기 중")
        self.v_engine = tk.StringVar(value="엔진: 확인 중…")

        self._build()
        self._on_target_kind()
        self._on_cookie_mode()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(GUI_POLL_MS, self._drain_events)
        self._check_engine()

    # -- 화면 구성 ---------------------------------------------------------

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        # 1. 대상
        f_target = ttk.LabelFrame(main, text="1. 어디서 받을까요?", padding=8)
        f_target.grid(row=0, column=0, sticky="ew", **pad)
        f_target.columnconfigure(2, weight=1)
        ttk.Radiobutton(
            f_target, text="내 북마크", value="bookmarks", variable=self.v_target_kind, command=self._on_target_kind
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            f_target, text="특정 계정의 모든 게시물:", value="user", variable=self.v_target_kind, command=self._on_target_kind
        ).grid(row=0, column=1, sticky="w", padx=(16, 4))
        self.e_username = ttk.Entry(f_target, textvariable=self.v_username)
        self.e_username.grid(row=0, column=2, sticky="ew")
        ttk.Label(f_target, text="예: @nasa 또는 https://x.com/nasa", foreground="gray").grid(
            row=1, column=2, sticky="w"
        )

        # 2. 로그인
        f_auth = ttk.LabelFrame(main, text="2. 로그인 쿠키 (북마크·계정 모두 X 로그인이 필요합니다)", padding=8)
        f_auth.grid(row=1, column=0, sticky="ew", **pad)
        f_auth.columnconfigure(0, weight=1)
        modes = ttk.Frame(f_auth)
        modes.grid(row=0, column=0, sticky="w")
        for text, value in (
            ("직접 입력 (권장)", COOKIE_MANUAL),
            ("브라우저에서 가져오기", COOKIE_BROWSER),
            ("cookies.txt 파일", COOKIE_FILE),
        ):
            ttk.Radiobutton(
                modes, text=text, value=value, variable=self.v_cookie_mode, command=self._on_cookie_mode
            ).pack(side="left", padx=(0, 12))

        self.f_manual = ttk.Frame(f_auth)
        self.f_manual.columnconfigure(1, weight=1)
        ttk.Label(self.f_manual, text="auth_token").grid(row=0, column=0, sticky="w")
        self.e_auth = ttk.Entry(self.f_manual, textvariable=self.v_auth_token, show="•")
        self.e_auth.grid(row=0, column=1, sticky="ew", padx=4, pady=2)
        ttk.Label(self.f_manual, text="ct0").grid(row=1, column=0, sticky="w")
        self.e_ct0 = ttk.Entry(self.f_manual, textvariable=self.v_ct0, show="•")
        self.e_ct0.grid(row=1, column=1, sticky="ew", padx=4, pady=2)
        ttk.Checkbutton(self.f_manual, text="보이기", variable=self.v_show_tokens, command=self._on_show_tokens).grid(
            row=0, column=2, rowspan=2
        )
        ttk.Label(
            self.f_manual,
            text="PC 브라우저로 x.com 로그인 → F12 → Application(애플리케이션) → Cookies → https://x.com 에서 복사",
            foreground="gray",
            wraplength=600,
        ).grid(row=2, column=0, columnspan=3, sticky="w")

        self.f_browser = ttk.Frame(f_auth)
        ttk.Label(self.f_browser, text="브라우저").pack(side="left")
        ttk.Combobox(self.f_browser, textvariable=self.v_browser, values=BROWSERS, state="readonly", width=12).pack(
            side="left", padx=6
        )
        ttk.Label(
            self.f_browser,
            text="그 브라우저에서 x.com에 로그인돼 있어야 합니다. 크롬/엣지는 보안 정책 때문에 실패할 수 있어 Firefox를 권장합니다.",
            foreground="gray",
            wraplength=480,
        ).pack(side="left")

        self.f_file = ttk.Frame(f_auth)
        self.f_file.columnconfigure(0, weight=1)
        ttk.Entry(self.f_file, textvariable=self.v_cookies_file).grid(row=0, column=0, sticky="ew")
        ttk.Button(self.f_file, text="찾기…", command=self._pick_cookies_file).grid(row=0, column=1, padx=4)

        ttk.Checkbutton(
            f_auth, text=f"로그인 정보 저장 ({SETTINGS_FILE})", variable=self.v_remember
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))

        # 3. 옵션
        f_opts = ttk.LabelFrame(main, text="3. 옵션", padding=8)
        f_opts.grid(row=2, column=0, sticky="ew", **pad)
        f_opts.columnconfigure(1, weight=1)
        media = ttk.Frame(f_opts)
        media.grid(row=0, column=0, columnspan=4, sticky="w")
        for text, value in (("사진 + 동영상", MEDIA_ALL), ("사진만", MEDIA_PHOTOS), ("동영상만(GIF 포함)", MEDIA_VIDEOS)):
            ttk.Radiobutton(media, text=text, value=value, variable=self.v_media).pack(side="left", padx=(0, 12))
        self.c_retweets = ttk.Checkbutton(
            f_opts, text="리트윗한 게시물의 미디어도 받기 (계정 모드)", variable=self.v_retweets
        )
        self.c_retweets.grid(row=1, column=0, columnspan=4, sticky="w")
        ttk.Checkbutton(
            f_opts,
            text="빠른 새로고침 (전체를 한 번 받은 뒤에는 새로 생긴 것만 확인)",
            variable=self.v_quick_refresh,
        ).grid(row=2, column=0, columnspan=4, sticky="w")
        ttk.Label(f_opts, text="저장 폴더").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f_opts, textvariable=self.v_output_dir).grid(row=3, column=1, sticky="ew", padx=4, pady=(6, 0))
        ttk.Button(f_opts, text="찾기…", command=self._pick_output_dir).grid(row=3, column=2, pady=(6, 0))
        ttk.Button(f_opts, text="열기", command=self._open_output_dir).grid(row=3, column=3, padx=(4, 0), pady=(6, 0))

        # 실행 버튼
        f_run = ttk.Frame(main)
        f_run.grid(row=3, column=0, sticky="ew", **pad)
        self.b_start = ttk.Button(f_run, text="다운로드 시작", command=self._start)
        self.b_start.pack(side="left")
        self.b_stop = ttk.Button(f_run, text="중지", command=self._stop, state="disabled")
        self.b_stop.pack(side="left", padx=6)
        self.b_upgrade = ttk.Button(f_run, text="엔진 업데이트", command=self._upgrade)
        self.b_upgrade.pack(side="right")
        ttk.Label(f_run, textvariable=self.v_engine, foreground="gray").pack(side="right", padx=6)

        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold")
        ttk.Label(main, textvariable=self.v_status, font=bold).grid(
            row=4, column=0, sticky="w", **pad
        )

        self.log = ScrolledText(main, height=14, wrap="none", state="disabled")
        self.log.grid(row=5, column=0, sticky="nsew", **pad)
        main.rowconfigure(5, weight=1)
        self.log.tag_configure("error", foreground="#d32f2f")
        self.log.tag_configure("warning", foreground="#e68a00")
        self.log.tag_configure("skip", foreground="gray")
        self.log.tag_configure("file", foreground="#2e7d32")

    # -- 폼 동작 -----------------------------------------------------------

    def _on_target_kind(self) -> None:
        is_user = self.v_target_kind.get() == "user"
        self.e_username.configure(state="normal" if is_user else "disabled")
        self.c_retweets.configure(state="normal" if is_user else "disabled")
        if is_user:
            self.e_username.focus_set()

    def _on_cookie_mode(self) -> None:
        frames = {COOKIE_MANUAL: self.f_manual, COOKIE_BROWSER: self.f_browser, COOKIE_FILE: self.f_file}
        for mode, frame in frames.items():
            if mode == self.v_cookie_mode.get():
                frame.grid(row=1, column=0, sticky="ew", pady=(6, 0))
            else:
                frame.grid_remove()

    def _on_show_tokens(self) -> None:
        show = "" if self.v_show_tokens.get() else "•"
        self.e_auth.configure(show=show)
        self.e_ct0.configure(show=show)

    def _pick_cookies_file(self) -> None:
        path = filedialog.askopenfilename(
            title="cookies.txt 선택", filetypes=[("cookies.txt", "*.txt"), ("모든 파일", "*.*")]
        )
        if path:
            self.v_cookies_file.set(path)

    def _pick_output_dir(self) -> None:
        path = filedialog.askdirectory(title="저장 폴더 선택", initialdir=self.v_output_dir.get() or str(Path.home()))
        if path:
            self.v_output_dir.set(path)

    def _open_output_dir(self) -> None:
        try:
            open_folder(str(Path(self.v_output_dir.get()).expanduser()))
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"폴더를 열 수 없습니다: {exc}")

    def _read_form(self) -> Options:
        target = BOOKMARKS if self.v_target_kind.get() == "bookmarks" else parse_target(self.v_username.get())
        return Options(
            target=target,
            output_dir=self.v_output_dir.get().strip(),
            media=self.v_media.get(),
            retweets=self.v_retweets.get(),
            quick_refresh=self.v_quick_refresh.get(),
            cookie_mode=self.v_cookie_mode.get(),
            auth_token=self.v_auth_token.get(),
            ct0=self.v_ct0.get(),
            browser=self.v_browser.get(),
            cookies_file=self.v_cookies_file.get().strip(),
            remember_login=self.v_remember.get(),
        )

    # -- 실행 --------------------------------------------------------------

    def _set_running(self, running: bool) -> None:
        self.b_start.configure(state="disabled" if running else "normal")
        self.b_upgrade.configure(state="disabled" if running else "normal")
        self.b_stop.configure(state="normal" if running else "disabled")

    def _start(self) -> None:
        if self.runner is not None:
            return
        try:
            opts = self._read_form()
            build_config(opts)  # 입력 검증
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        try:
            save_settings(opts)
        except OSError as exc:
            self._append("warning", f"설정 저장 실패: {exc}")

        self.counts = {"file": 0, "skip": 0, "error": 0}
        self._append("info", "-" * 60)
        self.v_status.set("다운로드 중…")
        self.runner = ProcessRunner()
        self._set_running(True)
        runner = self.runner
        threading.Thread(target=self._download_worker, args=(opts, runner), daemon=True).start()

    def _download_worker(self, opts: Options, runner: ProcessRunner) -> None:
        try:
            result = download(opts, lambda kind, text: self.events.put(("line", kind, text)), runner)
            self.events.put(("done", result.summary(), result.returncode == 0 or result.stopped))
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 화면에 보여주고 버튼을 되살린다
            self.events.put(("line", "error", f"실행 실패: {exc}"))
            self.events.put(("done", f"실행 실패: {exc}", False))

    def _stop(self) -> None:
        if self.runner is not None:
            self.runner.stop()
            self.v_status.set("중지하는 중…")

    def _upgrade(self) -> None:
        if self.runner is not None:
            return
        self._append("info", "-" * 60)
        self._append("info", "gallery-dl 업데이트: " + " ".join(upgrade_command()))
        self.v_status.set("엔진 업데이트 중…")
        self.runner = ProcessRunner()
        self._set_running(True)
        runner = self.runner

        def worker() -> None:
            try:
                code = runner.run(upgrade_command(), lambda line: self.events.put(("line", "info", line)))
            except OSError as exc:
                self.events.put(("line", "error", f"업데이트 실패: {exc}"))
                code = 1
            ok = code == 0
            self.events.put(("done", "엔진 업데이트 완료" if ok else f"엔진 업데이트 실패 (코드 {code})", ok))
            self.events.put(("engine", engine_version()))

        threading.Thread(target=worker, daemon=True).start()

    def _check_engine(self) -> None:
        threading.Thread(target=lambda: self.events.put(("engine", engine_version())), daemon=True).start()

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "line":
                    _, kind, text = event
                    if kind in self.counts:
                        self.counts[kind] += 1
                        self.v_status.set(
                            f"다운로드 중… 받음 {self.counts['file']}개 · 건너뜀 {self.counts['skip']}개"
                            + (f" · 오류 {self.counts['error']}개" if self.counts["error"] else "")
                        )
                    self._append(kind, text)
                elif event[0] == "done":
                    _, summary, ok = event
                    self.runner = None
                    self._set_running(False)
                    self.v_status.set(summary)
                    self._append("info" if ok else "error", summary)
                elif event[0] == "engine":
                    version = event[1]
                    self.v_engine.set(f"엔진: gallery-dl {version}" if version else "엔진: 미설치 → '엔진 업데이트'")
        except queue.Empty:
            pass
        self.root.after(GUI_POLL_MS, self._drain_events)

    def _append(self, kind: str, text: str) -> None:
        prefix = "(이미 받음) " if kind == "skip" else ""
        self.log.configure(state="normal")
        self.log.insert("end", prefix + text + "\n", kind)
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > LOG_MAX_LINES:
            self.log.delete("1.0", f"{lines - LOG_MAX_LINES}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        if self.runner is not None:
            if not messagebox.askyesno(APP_TITLE, "진행 중인 작업을 중지하고 종료할까요?"):
                return
            self.runner.stop()
        self.root.destroy()


def run_gui() -> int:
    if tk is None:
        print(
            "tkinter가 없어 GUI를 열 수 없습니다. (리눅스: sudo apt install python3-tk)\n"
            "명령줄로 사용하려면:  python x_media_downloader.py --help",
            file=sys.stderr,
        )
        return 2
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


def gui_available() -> bool:
    if tk is None or is_android():
        return False
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


def main(argv: list | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.upgrade_engine:
        return run_upgrade_cli()
    if args.menu:
        return run_menu()
    if args.gui:
        return run_gui()
    if args.target:
        return run_cli(args)
    return run_gui() if gui_available() else run_menu()


if __name__ == "__main__":
    sys.exit(main())
