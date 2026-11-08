"""android_bridge 테스트: 실제 gallery-dl을 같은 프로세스에서 돌리고, X API만 가짜(mock_x)로 바꾼다.

실행 (gallery-dl이 설치된 데스크톱 파이썬):
    python -m unittest discover -s twitter-media-crawler/android/pytests -v
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PY_SRC = HERE.parent / "app" / "src" / "main" / "python"
sys.path.insert(0, str(PY_SRC))
sys.path.insert(0, str(HERE))

import android_bridge as bridge  # noqa: E402
import mock_x  # noqa: E402

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")


class MediaServer(BaseHTTPRequestHandler):
    delay = 0.0
    requests = []

    def do_GET(self):
        MediaServer.requests.append(self.path)
        if MediaServer.delay:
            time.sleep(MediaServer.delay)
        body = self.path.encode()
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4" if ".mp4" in self.path else "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class Listener:
    """Kotlin 쪽 리스너 흉내. onFile에서 '사진 앱으로 옮기기'처럼 스테이징 파일을 지울 수 있다."""

    def __init__(self, publish=False):
        self.events, self.files = [], []
        self.publish = publish
        self.first_file = threading.Event()

    def onEvent(self, kind, text):  # noqa: N802 — Kotlin 메서드 이름
        self.events.append((kind, text))

    def onFile(self, path, folder):  # noqa: N802
        self.files.append((path, folder))
        assert os.path.isfile(path), path
        if self.publish:
            os.remove(path)
        self.first_file.set()

    def kinds(self, kind):
        return [t for k, t in self.events if k == kind]


class BridgeTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MediaServer)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        # bridge.init()은 앱 전용 임시 폴더를 전역(tempfile.tempdir)으로 지정한다. 테스트마다 원래대로 돌린다.
        tempfile.tempdir = None
        self.addCleanup(setattr, tempfile, "tempdir", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.files_dir = os.path.join(self.tmp.name, "files")
        self.staging = os.path.join(self.files_dir, "staging")
        os.makedirs(self.files_dir)
        bridge.init(self.files_dir)
        MediaServer.delay = 0.0
        MediaServer.requests = []

    def run_bridge(self, target, listener=None, scenario="normal", **opts):
        mock_x.install(self.base_url, scenario, **opts.pop("mock", {}))
        listener = listener or Listener()
        options = {"target": target, "auth_token": "a" * 40, "ct0": "csrf"}
        options.update(opts)
        result = json.loads(bridge.run_download(self.staging, json.dumps(options), listener))
        return result, listener

    def staged_media(self):
        root = Path(self.staging)
        return sorted(
            str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and ".download-history" not in p.parts
        )


class DownloadTest(BridgeTestBase):
    def test_bookmarks_full_run(self):
        result, lst = self.run_bridge("bookmarks")
        self.assertEqual(result["returncode"], 0, lst.events)
        self.assertEqual((result["downloaded"], result["skipped"], result["stopped"]), (4, 0, False))
        self.assertEqual({f for _, f in lst.files}, {"bookmarks"})
        self.assertEqual(len(self.staged_media()), 4)
        # 동영상은 가장 높은 화질
        video = [p for p, _ in lst.files if p.endswith("1850000000000000002_1.mp4")][0]
        self.assertEqual(Path(video).read_bytes(), b"/vid/v1_high.mp4")
        # 로그인 쿠키가 X API 요청에 쓰였다
        self.assertTrue(all(c["auth_token"] == "a" * 40 and c["csrf"] == "csrf" for c in mock_x.STATE["calls"]))
        self.assertIn("완료", result["summary"])

    def test_published_files_are_not_downloaded_again(self):
        self.run_bridge("bookmarks", Listener(publish=True))  # 받자마자 사진 앱으로 옮긴 상황
        self.assertEqual(self.staged_media(), [])
        result, _ = self.run_bridge("bookmarks", quick_refresh=False)
        self.assertEqual((result["downloaded"], result["skipped"]), (0, 4))

    def test_media_filters(self):
        result, lst = self.run_bridge("bookmarks", media="photos")
        self.assertEqual(result["downloaded"], 2)
        self.assertTrue(all(p.endswith(".jpg") for p, _ in lst.files))
        self.assertFalse(any(".mp4" in r for r in MediaServer.requests))

    def test_account_and_shared_post(self):
        result, lst = self.run_bridge("https://x.com/nasa/status/1860000000000000002?s=46&t=x")
        self.assertEqual((result["downloaded"], result["target"]), (1, "nasa/status/1860000000000000002"))
        self.assertEqual(lst.files[0][1], "nasa")
        result, _ = self.run_bridge("@nasa")
        self.assertEqual((result["downloaded"], result["skipped"]), (1, 1))  # 공유로 받은 건 중복 안 됨

    def test_log_lines_match_desktop_format(self):
        result, lst = self.run_bridge("bookmarks", scenario="bad_cookie")
        self.assertIn("[twitter][error] 'Could not authenticate you'", lst.kinds("error"))
        self.assertTrue(result["auth_error"])
        self.assertIn("로그인 쿠키", result["summary"])
        self.assertNotEqual(result["returncode"], 0)

    def test_invalid_target_and_missing_cookie(self):
        with self.assertRaises(ValueError):
            self.run_bridge("https://example.com/foo")
        with self.assertRaises(ValueError):
            self.run_bridge("bookmarks", auth_token="")
        # 실패한 뒤에도 다음 실행이 막히지 않는다 (잠금 해제)
        result, _ = self.run_bridge("bookmarks")
        self.assertEqual(result["returncode"], 0)


class IsolationTest(BridgeTestBase):
    def test_quick_refresh_setting_does_not_leak_into_next_run(self):
        result, _ = self.run_bridge("bookmarks", scenario="many")
        self.assertEqual((result["downloaded"], result["quick"]), (30, False))
        quick, _ = self.run_bridge("bookmarks", scenario="many", mock={"new": 2})
        self.assertTrue(quick["quick"])
        self.assertEqual((quick["downloaded"], quick["skipped"]), (2, 20))
        # 같은 프로세스에서 이어서 전체 확인: 앞 실행의 'skip: abort:20'이 남아 있으면 20에서 멈춘다
        full, _ = self.run_bridge("bookmarks", scenario="many", mock={"new": 2}, quick_refresh=False)
        self.assertEqual((full["downloaded"], full["skipped"], full["quick"]), (0, 32, False))

    def test_global_hooks_restored_after_run(self):
        from gallery_dl import output

        before = (output.stdout_write, time.sleep, len(__import__("logging").getLogger().handlers))
        self.run_bridge("bookmarks")
        self.run_bridge("bookmarks", scenario="bad_cookie")
        after = (output.stdout_write, time.sleep, len(__import__("logging").getLogger().handlers))
        self.assertEqual(before, after)


class StopTest(BridgeTestBase):
    def _run_async(self, **kw):
        out = {}

        def target():
            try:
                out["result"], out["listener"] = self.run_bridge("bookmarks", **kw)
            except BaseException as exc:  # noqa: BLE001
                out["error"] = exc

        thread = threading.Thread(target=target)
        thread.start()
        return thread, out

    def test_stop_during_downloads(self):
        MediaServer.delay = 0.7  # 파일마다 느리게
        lst = Listener()
        thread, out = self._run_async(listener=lst)
        self.assertTrue(lst.first_file.wait(20))
        started = time.time()
        self.assertTrue(bridge.stop())
        thread.join(20)
        self.assertFalse(thread.is_alive())
        self.assertLess(time.time() - started, 10)
        self.assertNotIn("error", out, out.get("error"))
        result = out["result"]
        self.assertTrue(result["stopped"])
        self.assertLess(result["downloaded"], 4)
        self.assertIn("중지됨", result["summary"])
        self.assertFalse(bridge.stop())  # 끝난 뒤에는 멈출 것이 없다
        # 중지된 실행은 '전체 받기 완료'로 기록되지 않는다 → 다음은 전체 확인으로 나머지를 받는다
        MediaServer.delay = 0.0
        result, _ = self.run_bridge("bookmarks")
        self.assertFalse(result["quick"])
        self.assertEqual(result["downloaded"] + out["result"]["downloaded"], 4)

    def test_stop_interrupts_rate_limit_wait(self):
        lst = Listener()
        thread, out = self._run_async(listener=lst, mock={"rate_limit_wait": 600})
        deadline = time.time() + 10
        while not any("Waiting until" in t or "rate limit" in t for t in lst.kinds("info")) and time.time() < deadline:
            time.sleep(0.05)
        started = time.time()
        bridge.stop()
        thread.join(15)
        self.assertFalse(thread.is_alive(), "중지가 10분 대기를 끊지 못함")
        self.assertLess(time.time() - started, 5)
        self.assertTrue(out["result"]["stopped"], out)

    def test_stop_does_not_disturb_other_threads(self):
        """중지 처리용 sleep 교체가 다운로드와 무관한 스레드의 sleep까지 끊으면 안 된다."""
        lst = Listener()
        other = {}

        def other_thread():
            try:
                time.sleep(1.5)
                other["ok"] = True
            except BaseException as exc:  # noqa: BLE001
                other["error"] = exc

        thread, out = self._run_async(listener=lst, mock={"rate_limit_wait": 600})
        time.sleep(0.3)
        sleeper = threading.Thread(target=other_thread)
        sleeper.start()
        time.sleep(0.2)
        bridge.stop()
        thread.join(15)
        sleeper.join(5)
        self.assertEqual(other, {"ok": True})
        self.assertTrue(out["result"]["stopped"], out)

    def test_second_run_while_running_is_rejected(self):
        MediaServer.delay = 0.5
        lst = Listener()
        thread, out = self._run_async(listener=lst)
        self.assertTrue(lst.first_file.wait(20))
        with self.assertRaises(RuntimeError):
            self.run_bridge("bookmarks")
        bridge.stop()
        thread.join(20)
        self.assertFalse(thread.is_alive())


class EngineTest(BridgeTestBase):
    def make_wheel(self, version, path):
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("gallery_dl/__init__.py", "")
            zf.writestr("gallery_dl/version.py", f"__version__ = '{version}'\n")
        return Path(path).read_bytes()

    def fake_pypi(self, version, wheel_bytes, sha=None):
        info = {
            "info": {"version": version},
            "urls": [
                {
                    "packagetype": "bdist_wheel",
                    "filename": f"gallery_dl-{version}-py3-none-any.whl",
                    "url": "https://files.example/wheel",
                    "digests": {"sha256": sha or hashlib.sha256(wheel_bytes).hexdigest()},
                }
            ],
        }

        def urlopen(url, timeout=None):
            data = json.dumps(info).encode() if "pypi.org" in url else wheel_bytes
            return io.BytesIO(data)

        return mock.patch("urllib.request.urlopen", side_effect=urlopen)

    def test_update_and_activate_on_next_start(self):
        wheel = self.make_wheel("99.0.0", os.path.join(self.tmp.name, "w.whl"))
        with self.fake_pypi("99.0.0", wheel):
            msg = bridge.update_engine()
        self.assertIn("99.0.0", msg)
        installed = os.path.join(self.files_dir, "engine", "gallery_dl.whl")
        self.assertTrue(os.path.isfile(installed))
        # 앱 재시작(새 파이썬)에서는 업데이트된 엔진이 쓰인다
        code = (
            f"import sys; sys.path.insert(0, {str(PY_SRC)!r}); import android_bridge as b; "
            f"b.init({self.files_dir!r}); print(b.engine_version())"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertIn("99.0.0 (업데이트됨)", out.stdout, out.stderr)
        self.assertIn("기본 엔진으로", bridge.reset_engine())
        self.assertFalse(os.path.exists(installed))

    def test_rejects_corrupt_download(self):
        wheel = self.make_wheel("99.0.0", os.path.join(self.tmp.name, "w.whl"))
        with self.fake_pypi("99.0.0", wheel, sha="0" * 64), self.assertRaises(RuntimeError):
            bridge.update_engine()
        self.assertFalse(os.path.exists(os.path.join(self.files_dir, "engine", "gallery_dl.whl")))

    def test_already_latest(self):
        with self.fake_pypi("1.0.0", b""):
            self.assertIn("이미 최신", bridge.update_engine())

    def test_broken_engine_file_is_ignored_on_start(self):
        engine = os.path.join(self.files_dir, "engine")
        os.makedirs(engine)
        Path(engine, "gallery_dl.whl").write_bytes(b"not a zip")
        code = (
            f"import sys; sys.path.insert(0, {str(PY_SRC)!r}); import android_bridge as b; "
            f"b.init({self.files_dir!r}); print(b.engine_version())"
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertIn("(기본)", out.stdout, out.stderr)


if __name__ == "__main__":
    unittest.main()
