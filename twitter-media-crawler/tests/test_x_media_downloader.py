"""x_media_downloader 단위 테스트 (네트워크 불필요).

실행:  python -m unittest discover -s tests -v
"""

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import x_media_downloader as xmd  # noqa: E402


def make_opts(**kwargs):
    defaults = {"auth_token": "TOKEN", "ct0": "CSRF", "output_dir": tempfile.gettempdir()}
    defaults.update(kwargs)
    return xmd.Options(**defaults)


class ParseTargetTest(unittest.TestCase):
    def test_bookmarks(self):
        for raw in ("bookmarks", "Bookmarks", " 북마크 ", "https://x.com/i/bookmarks", "x.com/i/bookmarks/"):
            self.assertEqual(xmd.parse_target(raw), xmd.BOOKMARKS, raw)

    def test_usernames(self):
        cases = {
            "nasa": "nasa",
            "@NASA": "NASA",
            "  @user_01 ": "user_01",
            "https://x.com/nasa": "nasa",
            "https://twitter.com/nasa/media": "nasa",
            "x.com/nasa?lang=ko": "nasa",
            "https://x.com/nasa?s=21&t=abc": "nasa",  # X 앱 '프로필 공유' 링크
            "www.x.com/nasa/": "nasa",
        }
        for raw, expected in cases.items():
            self.assertEqual(xmd.parse_target(raw), expected, raw)

    def test_post_links(self):
        cases = {
            "https://x.com/nasa/status/1850000000000000001?s=46&t=xyz": "nasa/status/1850000000000000001",
            "https://mobile.twitter.com/NASA/status/123/photo/1": "NASA/status/123",
            "이 게시물 봐 https://x.com/nasa/status/42?s=20 ㅋㅋ": "nasa/status/42",  # 공유 문구에 섞인 링크
            "nasa/status/42": "nasa/status/42",  # 저장된 설정의 내부 형식
        }
        for raw, expected in cases.items():
            self.assertEqual(xmd.parse_target(raw), expected, raw)
        self.assertEqual(xmd.split_post("nasa/status/42"), ("nasa", "42"))
        self.assertIsNone(xmd.split_post("nasa"))
        self.assertIsNone(xmd.split_post(xmd.BOOKMARKS))
        self.assertEqual(xmd.target_url("nasa/status/42"), "https://x.com/nasa/status/42")

    def test_invalid(self):
        for raw in ("", "   ", "@", "bad name", "한글", "https://example.com/nasa", "https://x.com/", "https://x.com/home", "x.com/i/lists/1"):
            with self.assertRaises(ValueError, msg=raw):
                xmd.parse_target(raw)

    def test_target_url(self):
        self.assertEqual(xmd.target_url(xmd.BOOKMARKS), "https://x.com/i/bookmarks")
        self.assertEqual(xmd.target_url("nasa"), "https://x.com/nasa")


class CookiesTest(unittest.TestCase):
    def test_clean_cookie_value(self):
        self.assertEqual(xmd.clean_cookie_value('  "abc123"  ', "auth_token"), "abc123")
        self.assertEqual(xmd.clean_cookie_value("auth_token=abc123;", "auth_token"), "abc123")
        self.assertEqual(xmd.clean_cookie_value("ct0= xyz ", "ct0"), "xyz")

    def test_manual(self):
        self.assertEqual(
            xmd.cookies_setting(make_opts(auth_token=" auth_token=T ", ct0="'C'")),
            {"auth_token": "T", "ct0": "C"},
        )
        self.assertEqual(xmd.cookies_setting(make_opts(ct0="")), {"auth_token": "TOKEN"})
        with self.assertRaises(ValueError):
            xmd.cookies_setting(make_opts(auth_token="  "))

    def test_browser(self):
        opts = make_opts(cookie_mode=xmd.COOKIE_BROWSER, browser="Firefox")
        self.assertEqual(xmd.cookies_setting(opts), ["firefox", None, None, None, ".x.com"])
        with self.assertRaises(ValueError):
            xmd.cookies_setting(make_opts(cookie_mode=xmd.COOKIE_BROWSER, browser="netscape"))

    def test_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as fp:
            path = fp.name
        try:
            opts = make_opts(cookie_mode=xmd.COOKIE_FILE, cookies_file=path)
            self.assertEqual(xmd.cookies_setting(opts), str(Path(path).resolve()))
        finally:
            os.remove(path)
        with self.assertRaises(ValueError):
            xmd.cookies_setting(make_opts(cookie_mode=xmd.COOKIE_FILE, cookies_file=path))
        with self.assertRaises(ValueError):
            xmd.cookies_setting(make_opts(cookie_mode=xmd.COOKIE_FILE, cookies_file=""))


class BuildConfigTest(unittest.TestCase):
    def test_bookmarks(self):
        cfg = xmd.build_config(make_opts(target=xmd.BOOKMARKS, retweets=True))
        tw = cfg["extractor"]["twitter"]
        self.assertEqual(tw["directory"], ["bookmarks"])
        self.assertFalse(tw["retweets"])  # 북마크에는 의미 없음
        self.assertTrue(tw["videos"])
        self.assertNotIn("file-filter", tw)
        self.assertNotIn("skip", cfg["extractor"])
        self.assertEqual(tw["filename"], xmd.FILENAME_FORMAT)
        self.assertEqual(cfg["output"]["mode"], "pipe")
        self.assertTrue(os.path.isabs(cfg["extractor"]["base-directory"]))

    def test_user(self):
        cfg = xmd.build_config(make_opts(target="NASA", retweets=True), quick_refresh=True)
        tw = cfg["extractor"]["twitter"]
        self.assertEqual(tw["directory"], ["{user[name]}"])
        self.assertEqual(tw["retweets"], "original")
        self.assertEqual(cfg["extractor"]["skip"], f"abort:{xmd.QUICK_REFRESH_SKIP_LIMIT}")

    def test_history_archive(self):
        cfg = xmd.build_config(make_opts(target="NASA"))
        base = Path(cfg["extractor"]["base-directory"])
        # 계정 아이디는 대소문자 구분 없이 같은 기록을 쓴다
        self.assertEqual(cfg["extractor"]["archive"], str(base / ".download-history" / "nasa.sqlite3"))
        self.assertEqual(cfg["extractor"]["archive-event"], "file,skip")
        self.assertNotIn("skip", cfg["extractor"])  # quick_refresh 기본값 False
        cfg = xmd.build_config(make_opts(target=xmd.BOOKMARKS))
        self.assertTrue(cfg["extractor"]["archive"].endswith(os.path.join(".download-history", "bookmarks.sqlite3")))

    def test_media_filters(self):
        photos = xmd.build_config(make_opts(media=xmd.MEDIA_PHOTOS))["extractor"]["twitter"]
        self.assertFalse(photos["videos"])
        self.assertNotIn("file-filter", photos)
        videos = xmd.build_config(make_opts(media=xmd.MEDIA_VIDEOS))["extractor"]["twitter"]
        self.assertTrue(videos["videos"])
        self.assertIn("animated_gif", videos["file-filter"])

    def test_invalid(self):
        with self.assertRaises(ValueError):
            xmd.build_config(make_opts(media="gifs"))
        with self.assertRaises(ValueError):
            xmd.build_config(make_opts(output_dir="  "))

    def test_config_is_json_serializable(self):
        json.dumps(xmd.build_config(make_opts(cookie_mode=xmd.COOKIE_BROWSER)))

    def test_command(self):
        cmd = xmd.gallery_dl_command("/tmp/c.json", "https://x.com/nasa")
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[1:], ["-m", "gallery_dl", "--config-ignore", "-c", "/tmp/c.json", "https://x.com/nasa"])


class ClassifyLineTest(unittest.TestCase):
    def test_lines(self):
        abs_path = os.path.join(os.path.abspath(os.sep), "out", "nasa", "a.jpg")
        self.assertEqual(xmd.classify_line(abs_path), ("file", abs_path))
        self.assertEqual(xmd.classify_line("# " + abs_path), ("skip", abs_path))
        self.assertEqual(xmd.classify_line("\\\\?\\C:\\out\\a.jpg"), ("file", "C:\\out\\a.jpg"))
        self.assertEqual(xmd.classify_line("[twitter][error] boom")[0], "error")
        self.assertEqual(xmd.classify_line("[downloader.http][warning] slow")[0], "warning")
        self.assertEqual(xmd.classify_line("[twitter][info] Waiting until 12:00")[0], "info")
        self.assertEqual(xmd.classify_line("Traceback (most recent call last):")[0], "info")

    def test_describe_exit_auth_error_overrides_generic_hint(self):
        msg = xmd.describe_exit(4, auth_error=True)
        self.assertIn("로그인 쿠키", msg)
        self.assertNotIn("인터넷 연결", msg)  # 실제 원인이 아닌 안내로 헷갈리게 하지 않음

    def test_describe_exit(self):
        self.assertEqual(xmd.describe_exit(0), "완료")
        self.assertIn("로그인 쿠키", xmd.describe_exit(16))
        self.assertIn("엔진 업데이트", xmd.describe_exit(4))
        self.assertIn("로그인 쿠키", xmd.describe_exit(4 | 16))
        self.assertIn("[error]", xmd.describe_exit(1))


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(xmd, "SETTINGS_FILE", Path(self.tmp.name) / "sub" / "settings.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_roundtrip(self):
        opts = make_opts(target="nasa", media=xmd.MEDIA_VIDEOS, retweets=True)
        xmd.save_settings(opts)
        self.assertEqual(xmd.load_settings(), opts)
        if os.name == "posix":
            self.assertEqual(xmd.SETTINGS_FILE.stat().st_mode & 0o777, 0o600)

    def test_forget_login(self):
        xmd.save_settings(make_opts(remember_login=False))
        loaded = xmd.load_settings()
        self.assertEqual((loaded.auth_token, loaded.ct0), ("", ""))
        self.assertFalse(loaded.remember_login)

    def test_missing_or_broken(self):
        self.assertEqual(xmd.load_settings(), xmd.Options())
        xmd.SETTINGS_FILE.parent.mkdir(parents=True)
        xmd.SETTINGS_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(xmd.load_settings(), xmd.Options())
        xmd.SETTINGS_FILE.write_text(json.dumps({"media": 3, "retweets": True, "unknown": 1}), encoding="utf-8")
        loaded = xmd.load_settings()
        self.assertEqual(loaded.media, xmd.MEDIA_ALL)  # 잘못된 타입은 기본값
        self.assertTrue(loaded.retweets)


class OptionsFromArgsTest(unittest.TestCase):
    def parse(self, *argv, env=None, base=None):
        args = xmd.build_arg_parser().parse_args(list(argv))
        with mock.patch.dict(os.environ, env or {}, clear=False):
            for key in ("X_AUTH_TOKEN", "X_CT0"):
                if not env or key not in env:
                    os.environ.pop(key, None)
            return xmd.options_from_args(args, base or xmd.Options(auth_token="SAVED", ct0="SAVEDCT0"))

    def test_defaults_use_saved_login(self):
        opts = self.parse("@nasa")
        self.assertEqual(opts.target, "nasa")
        self.assertEqual((opts.cookie_mode, opts.auth_token, opts.ct0), (xmd.COOKIE_MANUAL, "SAVED", "SAVEDCT0"))

    def test_new_token_does_not_reuse_saved_ct0(self):
        opts = self.parse("bookmarks", "--auth-token", "NEW")
        self.assertEqual((opts.auth_token, opts.ct0), ("NEW", ""))
        opts = self.parse("bookmarks", env={"X_AUTH_TOKEN": "ENV", "X_CT0": "ENVCT0"})
        self.assertEqual((opts.auth_token, opts.ct0), ("ENV", "ENVCT0"))

    def test_browser_and_file(self):
        self.assertEqual(self.parse("nasa", "--browser", "firefox").cookie_mode, xmd.COOKIE_BROWSER)
        opts = self.parse("nasa", "--cookies", "c.txt")
        self.assertEqual((opts.cookie_mode, opts.cookies_file), (xmd.COOKIE_FILE, "c.txt"))

    def test_flags(self):
        opts = self.parse("nasa", "--only", "videos", "--retweets", "-o", "out")
        self.assertEqual((opts.media, opts.retweets, opts.quick_refresh, opts.output_dir), ("videos", True, True, "out"))
        self.assertFalse(self.parse("nasa", "--full").quick_refresh)

    def test_bad_target(self):
        with self.assertRaises(ValueError):
            self.parse("bad name")


class FakeRunner(xmd.ProcessRunner):
    def __init__(self, lines, code=0):
        super().__init__()
        self.lines, self.code = lines, code
        self.config = None
        self.config_path = None

    def run(self, cmd, on_line):
        self.config_path = cmd[cmd.index("-c") + 1]
        with open(self.config_path, encoding="utf-8") as fp:
            self.config = json.load(fp)
        for line in self.lines:
            on_line(line)
        return self.code


class DownloadTest(unittest.TestCase):
    def test_counts_and_cleanup(self):
        with tempfile.TemporaryDirectory() as out:
            base = str(Path(out).resolve())
            runner = FakeRunner(
                [
                    os.path.join(base, "nasa", "a.jpg"),
                    os.path.join(base, "nasa", "b.mp4"),
                    "# " + os.path.join(base, "nasa", "c.jpg"),
                    "[twitter][error] something",
                ],
                code=4,
            )
            events = []
            result = xmd.download(make_opts(target="nasa", output_dir=out), lambda k, t: events.append((k, t)), runner)

            self.assertEqual((result.downloaded, result.skipped, result.errors, result.returncode), (2, 1, 1, 4))
            self.assertFalse(result.stopped)
            self.assertIn(("file", os.path.join("nasa", "a.jpg")), events)  # 저장 폴더 기준 상대 경로로 표시
            self.assertIn(("skip", os.path.join("nasa", "c.jpg")), events)
            self.assertEqual(runner.config["extractor"]["twitter"]["cookies"], {"auth_token": "TOKEN", "ct0": "CSRF"})
            self.assertFalse(os.path.exists(runner.config_path), "로그인 쿠키가 든 임시 설정 파일은 지워져야 함")
            self.assertIn("받음 2개", result.summary())

    def test_auth_error_detected_from_log(self):
        with tempfile.TemporaryDirectory() as out:
            runner = FakeRunner(["[twitter][error] 'Could not authenticate you'"], code=4)
            result = xmd.download(make_opts(target=xmd.BOOKMARKS, output_dir=out), lambda k, t: None, runner)
            self.assertTrue(result.auth_error)
            self.assertIn("로그인 쿠키", result.summary())
            self.assertNotIn("인터넷 연결", result.summary())

    def test_cookie_format_warning(self):
        self.assertEqual(xmd.cookie_warnings(make_opts(auth_token="a" * 40)), [])
        self.assertEqual(len(xmd.cookie_warnings(make_opts(auth_token="auth_token"))), 1)
        self.assertEqual(xmd.cookie_warnings(make_opts(cookie_mode=xmd.COOKIE_BROWSER)), [])
        with tempfile.TemporaryDirectory() as out:
            events = []
            xmd.download(make_opts(output_dir=out, auth_token="short"), lambda k, t: events.append((k, t)), FakeRunner([]))
            self.assertTrue(any(k == "warning" and "auth_token" in t for k, t in events))

    def test_invalid_input_runs_nothing(self):
        runner = FakeRunner([])
        with self.assertRaises(ValueError):
            xmd.download(make_opts(auth_token=""), lambda k, t: None, runner)
        self.assertIsNone(runner.config_path)


class ScopeTest(unittest.TestCase):
    def test_scope_covered(self):
        all_rt = {"media": "all", "retweets": True}
        photos = {"media": "photos", "retweets": False}
        self.assertFalse(xmd.scope_covered([], photos))
        self.assertTrue(xmd.scope_covered([all_rt], photos))
        self.assertTrue(xmd.scope_covered([all_rt], {"media": "videos", "retweets": True}))
        self.assertTrue(xmd.scope_covered([photos], photos))
        # 사진만 받았던 대상을 '전체'나 '동영상만'으로 바꾸면 예전 동영상을 받은 적이 없음
        self.assertFalse(xmd.scope_covered([photos], {"media": "all", "retweets": False}))
        self.assertFalse(xmd.scope_covered([photos], {"media": "videos", "retweets": False}))
        # 리트윗 제외로 받았던 대상에 리트윗 포함을 켜면 예전 리트윗은 받은 적이 없음
        self.assertFalse(xmd.scope_covered([{"media": "all", "retweets": False}], {"media": "all", "retweets": True}))

    def test_run_scope_ignores_retweets_for_bookmarks(self):
        self.assertEqual(xmd.run_scope(make_opts(target=xmd.BOOKMARKS, retweets=True))["retweets"], False)
        self.assertEqual(xmd.run_scope(make_opts(target="nasa", retweets=True))["retweets"], True)

    def test_state_file_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "x.json"
            self.assertEqual(xmd.load_completed_scopes(state), [])
            xmd.record_full_scan(state, {"media": "all", "retweets": False})
            xmd.record_full_scan(state, {"media": "all", "retweets": False})  # 중복 기록 안 함
            self.assertEqual(xmd.load_completed_scopes(state), [{"media": "all", "retweets": False}])
            state.write_text("garbage", encoding="utf-8")
            self.assertEqual(xmd.load_completed_scopes(state), [])


class QuickRefreshGatingTest(unittest.TestCase):
    """빠른 새로고침은 전체 받기를 끝까지 마친 뒤에만 켜져야 한다."""

    def run_once(self, out, code=0, stop=False, **kw):
        runner = FakeRunner([], code=code)
        if stop:
            runner.stopped = True
        events = []
        result = xmd.download(make_opts(output_dir=out, **kw), lambda k, t: events.append((k, t)), runner)
        return result, runner.config, events

    def test_first_run_is_full_then_quick(self):
        with tempfile.TemporaryDirectory() as out:
            r1, cfg1, _ = self.run_once(out, target="nasa")
            self.assertFalse(r1.quick)
            self.assertNotIn("skip", cfg1["extractor"])
            r2, cfg2, _ = self.run_once(out, target="NASA")  # 대소문자만 다른 같은 계정
            self.assertTrue(r2.quick)
            self.assertEqual(cfg2["extractor"]["skip"], f"abort:{xmd.QUICK_REFRESH_SKIP_LIMIT}")
            # 다른 대상은 별개
            r3, _, _ = self.run_once(out, target=xmd.BOOKMARKS)
            self.assertFalse(r3.quick)

    def test_failed_or_stopped_full_run_is_not_recorded(self):
        with tempfile.TemporaryDirectory() as out:
            self.run_once(out, code=4, target="nasa")
            self.assertFalse(self.run_once(out, stop=True, code=-15, target="nasa")[0].quick)
            self.assertFalse(self.run_once(out, target="nasa")[0].quick)  # 이번엔 성공 → 기록
            self.assertTrue(self.run_once(out, target="nasa")[0].quick)

    def test_wider_scope_needs_full_run(self):
        with tempfile.TemporaryDirectory() as out:
            self.run_once(out, target="nasa", media=xmd.MEDIA_PHOTOS)
            self.assertTrue(self.run_once(out, target="nasa", media=xmd.MEDIA_PHOTOS)[0].quick)
            self.assertFalse(self.run_once(out, target="nasa", media=xmd.MEDIA_ALL)[0].quick)
            self.assertTrue(self.run_once(out, target="nasa", media=xmd.MEDIA_VIDEOS)[0].quick)

    def test_single_post_uses_account_history_and_never_quick(self):
        with tempfile.TemporaryDirectory() as out:
            self.run_once(out, target="nasa")  # 계정 전체 받기 완료
            r, cfg, _ = self.run_once(out, target="NASA/status/42")
            self.assertFalse(r.quick)
            self.assertNotIn("skip", cfg["extractor"])
            # 계정과 같은 기록을 쓰므로 나중에 계정 전체를 받아도 이 게시물은 중복되지 않는다
            self.assertTrue(cfg["extractor"]["archive"].endswith(os.path.join(".download-history", "nasa.sqlite3")))
        with tempfile.TemporaryDirectory() as out:
            self.run_once(out, target="nasa/status/42")
            self.assertFalse(self.run_once(out, target="nasa")[0].quick, "게시물 하나 받은 것을 계정 전체 받기로 기록하면 안 됨")

    def test_quick_refresh_off_always_full(self):
        with tempfile.TemporaryDirectory() as out:
            self.run_once(out, target="nasa")
            r, cfg, _ = self.run_once(out, target="nasa", quick_refresh=False)
            self.assertFalse(r.quick)
            self.assertNotIn("skip", cfg["extractor"])

    def test_invalid_input_creates_nothing(self):
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaises(ValueError):
                xmd.download(make_opts(output_dir=out, auth_token=""), lambda k, t: None, FakeRunner([]))
            self.assertEqual(os.listdir(out), [])


class ProcessRunnerTest(unittest.TestCase):
    def test_streams_lines_and_exit_code(self):
        lines = []
        code = xmd.ProcessRunner().run(
            [sys.executable, "-c", "import sys; print('하나'); print(''); print('둘'); sys.exit(3)"], lines.append
        )
        self.assertEqual((lines, code), (["하나", "둘"], 3))

    def test_stop_before_start(self):
        runner = xmd.ProcessRunner()
        runner.stop()
        self.assertEqual(runner.run([sys.executable, "-c", "print(1)"], lambda line: None), -1)

    def test_stop_while_running(self):
        import threading

        runner = xmd.ProcessRunner()
        started = threading.Event()

        def on_line(line):
            started.set()

        t = threading.Thread(
            target=runner.run,
            args=([sys.executable, "-c", "import time; print('go', flush=True); time.sleep(60)"], on_line),
        )
        t.start()
        self.assertTrue(started.wait(10))
        runner.stop()
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertTrue(runner.stopped)


class AndroidTest(unittest.TestCase):
    def test_detection(self):
        with mock.patch.dict(os.environ, {"PREFIX": "/data/data/com.termux/files/usr"}):
            self.assertTrue(xmd.is_android())
            self.assertEqual(xmd.default_output_dir(), "/storage/emulated/0/Download/x-media")
        if hasattr(sys, "getandroidapilevel"):
            self.skipTest("실제 안드로이드 파이썬")
        with mock.patch.dict(os.environ, {"PREFIX": "/usr"}):
            self.assertFalse(xmd.is_android())
            self.assertEqual(xmd.default_output_dir(), str(Path.home() / "Downloads" / "x-media"))

    def test_gui_available(self):
        with mock.patch.object(xmd, "tk", None):
            self.assertFalse(xmd.gui_available())
        with mock.patch.object(xmd, "tk", object()), mock.patch.object(xmd, "is_android", return_value=True):
            self.assertFalse(xmd.gui_available())
        with mock.patch.object(xmd, "tk", object()), mock.patch.object(xmd, "is_android", return_value=False), \
                mock.patch.object(sys, "platform", "linux"):
            with mock.patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
                self.assertFalse(xmd.gui_available())
            with mock.patch.dict(os.environ, {"DISPLAY": ":0"}):
                self.assertTrue(xmd.gui_available())

    def test_permission_error_hint_on_android(self):
        with mock.patch.object(xmd, "engine_version", return_value="1.0"), \
                mock.patch.object(xmd, "is_android", return_value=True), \
                mock.patch.object(xmd, "_termux_command") as termux, \
                mock.patch.object(xmd, "download", side_effect=PermissionError("denied")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(xmd.run_download_console(make_opts()), 1)
        self.assertIn("termux-setup-storage", err.getvalue())
        # 화면이 꺼져도 멈추지 않게 wake lock을 잡고, 실패해도 반드시 푼다
        self.assertEqual([c.args[0] for c in termux.call_args_list], ["termux-wake-lock", "termux-wake-unlock"])


class MenuTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in (
            mock.patch.object(xmd, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json"),
            mock.patch.object(xmd, "load_settings", return_value=xmd.Options(output_dir=self.tmp.name)),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.stdout = patcher.start()
            self.addCleanup(patcher.stop)
        self.runs = []
        patcher = mock.patch.object(xmd, "run_download_console", side_effect=lambda o: self.runs.append(asdict(o)) or 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def menu(self, *answers):
        with mock.patch("builtins.input", side_effect=list(answers)):
            return xmd.run_menu()

    def test_first_run_asks_login_then_downloads_bookmarks(self):
        self.assertEqual(self.menu("1", " auth_token=TOK; ", "'CT'", "", "0"), 0)
        self.assertEqual(len(self.runs), 1)
        run = self.runs[0]
        self.assertEqual((run["target"], run["auth_token"], run["ct0"], run["remember_login"]), ("bookmarks", "TOK", "CT", True))
        saved = json.loads(xmd.SETTINGS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved["auth_token"], "TOK")

    def test_login_required_and_not_saved_when_declined(self):
        self.menu("3", "", "TOK", "", "n", "0")  # 빈 auth_token은 다시 물어봄
        saved = json.loads(xmd.SETTINGS_FILE.read_text(encoding="utf-8"))
        self.assertEqual((saved["auth_token"], saved["remember_login"]), ("", False))

    def test_account_and_bad_input(self):
        self.menu("3", "TOK", "", "y", "2", "not valid!", "2", "https://x.com/NASA/media", "9", "0")
        self.assertEqual([r["target"] for r in self.runs], ["NASA"])
        self.assertIn("입력 오류", self.stdout.getvalue())
        self.assertIn("1~5 또는 0", self.stdout.getvalue())

    def test_options(self):
        self.menu("4", "3", "y", "n", "", "3", "TOK", "", "y", "1", "0")
        run = self.runs[0]
        self.assertEqual((run["media"], run["retweets"], run["quick_refresh"]), ("videos", True, False))
        self.assertEqual(run["output_dir"], self.tmp.name)  # Enter = 그대로

    def test_eof_and_ctrl_c_exit_cleanly(self):
        with mock.patch("builtins.input", side_effect=EOFError):  # 입력 끝
            self.assertEqual(xmd.run_menu(), 0)
        with mock.patch("builtins.input", side_effect=KeyboardInterrupt):
            self.assertEqual(xmd.run_menu(), 0)


class MainTest(unittest.TestCase):
    def test_no_args_dispatch(self):
        with mock.patch.object(xmd, "run_gui", return_value=0) as gui, mock.patch.object(
            xmd, "run_menu", return_value=0
        ) as menu:
            with mock.patch.object(xmd, "gui_available", return_value=True):
                xmd.main([])
            with mock.patch.object(xmd, "gui_available", return_value=False):
                xmd.main([])
            xmd.main(["--menu"])
            self.assertEqual((gui.call_count, menu.call_count), (1, 2))

    def test_cli_rejects_bad_input_without_running(self):
        with mock.patch.object(xmd, "load_settings", return_value=xmd.Options()), mock.patch.object(
            xmd, "download"
        ) as download:
            self.assertEqual(xmd.main(["@nasa"]), 2)  # 로그인 쿠키 없음
            self.assertEqual(xmd.main(["not valid"]), 2)
            download.assert_not_called()

    def test_parser(self):
        args = xmd.build_arg_parser().parse_args([])
        self.assertIsInstance(args, argparse.Namespace)
        self.assertIsNone(args.target)


if __name__ == "__main__":
    unittest.main()
