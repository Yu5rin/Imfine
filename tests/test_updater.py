"""updater.py のうち、外へ出ずに確かめられる判断を固定するテスト。

実行: リポジトリの直下で `python -m unittest discover -s tests`
(pytest が入っていれば `python -m pytest tests` でも動く)。

ネットワークには出ない。リダイレクトの確認は 127.0.0.1 に立てた HTTP サーバーで行う。
"""
import http.server
import os
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import updater  # noqa: E402

# 2026-09-25 に v1.13.2 の exe で確かめた、実際のリダイレクトの形
REAL_DOWNLOAD_URL = 'https://github.com/Yu5rin/Imfine/releases/download/v1.13.2/ImFine.exe'
REAL_REDIRECT_URL = ('https://release-assets.githubusercontent.com/'
                     'github-production-release-asset/1240746648/xxxx?sp=r&sig=yyyy')


class _Quiet(unittest.TestCase):
    """update.log へ書き込まないようにする。"""

    def setUp(self):
        patcher = mock.patch.object(updater, '_log')
        self.log = patcher.start()
        self.addCleanup(patcher.stop)


class IsAllowedUrlTests(_Quiet):
    def test_https_の許可ホストは通す(self):
        self.assertTrue(updater._is_allowed_url(REAL_DOWNLOAD_URL, updater.ALLOWED_DOWNLOAD_HOSTS))
        self.assertTrue(updater._is_allowed_url(
            'https://api.github.com/repos/Yu5rin/Imfine/releases/latest',
            (updater.ALLOWED_API_HOST,)))

    def test_http_は通さない(self):
        self.assertFalse(updater._is_allowed_url(
            'http://github.com/Yu5rin/Imfine/releases/download/v1/ImFine.exe',
            updater.ALLOWED_DOWNLOAD_HOSTS))

    def test_紛らわしいホストは通さない(self):
        for url in (
            'https://github.com.attacker.example/ImFine.exe',
            'https://evil-github.com/ImFine.exe',
            'https://release-assets.githubusercontent.com.attacker.example/x',
            'https://attacker.example/?github.com',
            'https://github.com@attacker.example/ImFine.exe',
        ):
            with self.subTest(url=url):
                self.assertFalse(updater._is_allowed_url(url, updater.ALLOWED_DOWNLOAD_REDIRECT_HOSTS))

    def test_最初のダウンロードURLは_github_com_に限る(self):
        # browser_download_url は常に github.com。配信用ホストはリダイレクト先としてだけ許す
        self.assertFalse(updater._is_allowed_url(REAL_REDIRECT_URL, updater.ALLOWED_DOWNLOAD_HOSTS))


class RedirectHandlerTests(_Quiet):
    """リダイレクト先の判断。"""

    def _redirect(self, hosts, from_url, to_url, code=302):
        handler = updater._AllowedHostRedirectHandler(hosts)
        req = urllib.request.Request(from_url)
        return handler.redirect_request(req, None, code, 'Found', {}, to_url)

    def test_実際の配信先へのリダイレクトは辿る(self):
        # コメントにあった objects.githubusercontent.com だけを許していたら、ここで更新が止まる
        new_req = self._redirect(updater.ALLOWED_DOWNLOAD_REDIRECT_HOSTS,
                                 REAL_DOWNLOAD_URL, REAL_REDIRECT_URL)
        self.assertIsNotNone(new_req)
        self.assertEqual(new_req.full_url, REAL_REDIRECT_URL)

    def test_以前の配信先へのリダイレクトも辿る(self):
        new_req = self._redirect(updater.ALLOWED_DOWNLOAD_REDIRECT_HOSTS, REAL_DOWNLOAD_URL,
                                 'https://objects.githubusercontent.com/github-production-release-asset/x')
        self.assertIsNotNone(new_req)

    def test_301_307_308_でも同じように確かめる(self):
        for code in (301, 303, 307, 308):
            with self.subTest(code=code):
                with self.assertRaises(updater.DisallowedRedirect):
                    self._redirect(updater.ALLOWED_DOWNLOAD_REDIRECT_HOSTS, REAL_DOWNLOAD_URL,
                                   'https://attacker.example/ImFine.exe', code=code)

    def test_許可されていないホストへのリダイレクトは断る(self):
        for to_url in (
            'https://attacker.example/ImFine.exe',
            'https://release-assets.githubusercontent.com.attacker.example/x',
            'http://release-assets.githubusercontent.com/x',  # https でない
        ):
            with self.subTest(to_url=to_url):
                with self.assertRaises(updater.DisallowedRedirect) as cm:
                    self._redirect(updater.ALLOWED_DOWNLOAD_REDIRECT_HOSTS, REAL_DOWNLOAD_URL, to_url)
                self.assertEqual(cm.exception.filename, to_url)

    def test_APIのリダイレクトは_api_github_com_に限る(self):
        hosts = (updater.ALLOWED_API_HOST,)
        api = 'https://api.github.com/repos/Yu5rin/Imfine/releases/latest'
        # リポジトリ名の変更で返る 301 の行き先
        self.assertIsNotNone(self._redirect(
            hosts, api, 'https://api.github.com/repositories/1240746648/releases/latest', code=301))
        with self.assertRaises(updater.DisallowedRedirect):
            self._redirect(hosts, api, 'https://github.com/Yu5rin/Imfine', code=301)


class _RedirectingServer:
    """どのパスにも 302 で location を返すだけのサーバー。"""

    def __init__(self, location):
        self.hits = []
        hits = self.hits

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                if self.path == '/final':
                    body = b'final'
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(302)
                self.send_header('Location', location(self.server.server_port))
                self.send_header('Content-Length', '0')
                self.end_headers()

            def log_message(self, *args):
                pass

        self.httpd = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        self.port = self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class OpenWiringTests(_Quiet):
    """_open が実際にリダイレクトのたびに行き先を確かめていること。

    urllib.request.urlopen を直接呼んでいたころは、ここでリダイレクトを黙って辿っていた。
    """

    def test_許可されていない行き先へは接続しない(self):
        # 行き先は同じサーバーの /final だが、http なので許可されない。
        # 確かめずに辿っていれば /final へ2回目のリクエストが来る
        with _RedirectingServer(lambda port: f'http://127.0.0.1:{port}/final') as srv:
            with self.assertRaises(updater.DisallowedRedirect):
                updater._open(f'http://127.0.0.1:{srv.port}/start', {}, 5, ('127.0.0.1',))
            self.assertEqual(srv.hits, ['/start'])

    def test_既定の_urlopen_なら辿ってしまう(self):
        # 上のテストが「サーバーの作りのせいで辿らなかった」のではないことの対照
        with _RedirectingServer(lambda port: f'http://127.0.0.1:{port}/final') as srv:
            with urllib.request.urlopen(f'http://127.0.0.1:{srv.port}/start', timeout=5) as resp:
                self.assertEqual(resp.read(), b'final')
            self.assertEqual(srv.hits, ['/start', '/final'])


class DownloadAndVerifyTests(_Quiet):
    def _asset(self, url=REAL_DOWNLOAD_URL):
        return {'name': 'ImFine.exe', 'digest': 'sha256:' + '0' * 64,
                'browser_download_url': url}

    def test_ダウンロードはリダイレクト先を確かめる_open_を通す(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(updater, '_open',
                                  side_effect=updater.DisallowedRedirect(
                                      'https://attacker.example/x', 302, 'x', {}, None)) as m:
            self.assertIsNone(updater.download_and_verify(self._asset(), d))
            args = m.call_args.args
            self.assertEqual(args[0], REAL_DOWNLOAD_URL)
            self.assertEqual(args[3], updater.ALLOWED_DOWNLOAD_REDIRECT_HOSTS)
            # 途中のファイルを残さない
            self.assertEqual(os.listdir(d), [])

    def test_最初のURLが許可されていなければ接続しない(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(updater, '_open') as m:
            self.assertIsNone(updater.download_and_verify(self._asset(REAL_REDIRECT_URL), d))
            m.assert_not_called()


class LogTests(_Quiet):
    def test_リダイレクト先はクエリを落として記録する(self):
        # 配信先の URL には署名が付く。update.log へそのまま残さない
        self.assertEqual(
            updater._without_query(REAL_REDIRECT_URL),
            'https://release-assets.githubusercontent.com/'
            'github-production-release-asset/1240746648/xxxx')


class CheckLatestTests(_Quiet):
    def test_確認はリダイレクト先を_api_github_com_に限る(self):
        with mock.patch.object(updater, '_open',
                               side_effect=updater.DisallowedRedirect(
                                   'https://attacker.example/x', 301, 'x', {}, None)) as m:
            self.assertIsNone(updater.check_latest(
                'https://api.github.com/repos/Yu5rin/Imfine/releases/latest'))
            self.assertEqual(m.call_args.args[3], (updater.ALLOWED_API_HOST,))


class RestartEnvTests(_Quiet):
    """B1: 更新後の再起動で、新しいプロセスに旧プロセスの一時フォルダを使い回させない。"""

    def test_PYINSTALLER_RESET_ENVIRONMENT_を渡す(self):
        with mock.patch.dict(os.environ, {'_PYI_ARCHIVE_FILE': r'C:\old\ImFine.exe',
                                          'KEEP_ME': '1'}), \
                mock.patch.object(updater.subprocess, 'Popen') as popen:
            self.assertTrue(updater._spawn_restart(r'C:\app\ImFine.exe', 1234))
        env = popen.call_args.kwargs['env']
        self.assertEqual(env['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        self.assertEqual(env['KEEP_ME'], '1')  # ほかの環境変数は引き継ぐ
        args = popen.call_args.args[0]
        self.assertEqual(args[1:], [updater.AFTER_UPDATE_ARG, '1234'])

    def test_起動に失敗したら_False(self):
        with mock.patch.object(updater.subprocess, 'Popen', side_effect=OSError('x')):
            self.assertFalse(updater._spawn_restart('ImFine.exe', 1))


class _AsyncRun(_Quiet):
    """check_and_apply_async を走らせ、終わるまで待つ。"""

    def run_async(self, **kwargs):
        states = []
        done = threading.Event()

        def on_state(state, info):
            states.append((state, info))
            if state in ('up_to_date', 'failed', 'ready'):
                done.set()

        started = updater.check_and_apply_async(
            '1.16.0', 'https://api.github.com/repos/Yu5rin/Imfine/releases/latest',
            on_state=on_state, **kwargs)
        self.assertTrue(started)
        self.assertTrue(done.wait(5))
        # ロックが外れるまで待つ
        for _ in range(100):
            if not updater.is_running():
                break
            threading.Event().wait(0.01)
        self.assertFalse(updater.is_running())
        return states


class WorkerRobustnessTests(_AsyncRun):
    """B7: 想定外の例外や null の値で、状態表示が固まらない。"""

    def test_想定外の例外でも_failed_を伝えてロックを外す(self):
        with mock.patch.object(updater, 'check_latest', side_effect=RuntimeError('boom')):
            states = self.run_async()
        self.assertEqual(states[-1][0], 'failed')
        self.assertTrue(any('想定外' in str(c.args[0]) for c in self.log.call_args_list))

    def test_tag_name_が_null_なら_failed(self):
        with mock.patch.object(updater, 'check_latest', return_value={'tag_name': None}):
            states = self.run_async()
        self.assertEqual(states[-1][0], 'failed')

    def test_最新なら版の情報も渡す(self):
        with mock.patch.object(updater, 'check_latest', return_value={'tag_name': 'v1.16.0'}):
            states = self.run_async()
        self.assertEqual(states[-1], ('up_to_date', {'latest': 'v1.16.0'}))

    def test_name_や_digest_が_null_でも落ちない(self):
        self.assertIsNone(updater.find_exe_asset({'assets': [{'name': None}]}))
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(updater.download_and_verify(
                {'name': 'ImFine.exe', 'digest': None, 'browser_download_url': None}, d))

    def test_apply_False_なら検証済みのファイルを渡すだけで置き換えない(self):
        release = {'tag_name': 'v9.0.0', 'assets': [{'name': 'ImFine.exe'}]}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(updater, 'check_latest', return_value=release), \
                mock.patch.object(sys, 'frozen', True, create=True), \
                mock.patch.object(sys, 'executable', os.path.join(d, 'ImFine.exe')), \
                mock.patch.object(updater, 'download_and_verify',
                                  return_value=os.path.join(d, 'x.exe')), \
                mock.patch.object(updater, 'apply_update') as apply:
            states = self.run_async(apply=False)
        apply.assert_not_called()
        self.assertEqual([s for s, _ in states], ['checking', 'downloading', 'ready'])
        self.assertEqual(states[-1][1]['latest'], 'v9.0.0')


class ConcurrencyTests(_Quiet):
    """B5: 実行中に呼ばれても並行して走らせない。"""

    def test_実行中は何もしない(self):
        gate = threading.Event()

        def slow(*a, **k):
            gate.wait(5)
            return None

        with mock.patch.object(updater, 'check_latest', side_effect=slow):
            url = 'https://api.github.com/repos/Yu5rin/Imfine/releases/latest'
            self.assertTrue(updater.check_and_apply_async('1.0.0', url))
            self.assertTrue(updater.is_running())
            self.assertFalse(updater.check_and_apply_async('1.0.0', url))
            gate.set()
            for _ in range(200):
                if not updater.is_running():
                    break
                threading.Event().wait(0.01)
        self.assertFalse(updater.is_running())

    def test_URL_が無ければ始めない(self):
        self.assertFalse(updater.check_and_apply_async('1.0.0', ''))
        self.assertFalse(updater.is_running())


class CleanupTests(_Quiet):
    """B13: ダウンロード途中の imfine_update_*.exe を起動時に消す。"""

    def test_途中のファイルだけを消す(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            exe = d / 'ImFine.exe'
            exe.write_text('x')
            leftovers = [d / 'imfine_update_abc.exe', d / 'imfine_update_.exe']
            for p in leftovers:
                p.write_text('partial')
            keep = [d / 'other.exe', d / 'imfine_update_abc.txt']
            for p in keep:
                p.write_text('keep')
            (d / 'ImFine.exe.old').write_text('old')
            with mock.patch.object(sys, 'frozen', True, create=True), \
                    mock.patch.object(sys, 'executable', str(exe)):
                updater.recover_or_cleanup()
            for p in leftovers:
                self.assertFalse(p.exists(), p)
            for p in keep + [exe]:
                self.assertTrue(p.exists(), p)
            self.assertFalse((d / 'ImFine.exe.old').exists())

    def test_ソース実行では何もしない(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / 'imfine_update_x.exe'
            p.write_text('x')
            with mock.patch.object(sys, 'frozen', False, create=True), \
                    mock.patch.object(sys, 'executable', str(pathlib.Path(d) / 'python.exe')):
                updater.recover_or_cleanup()
            self.assertTrue(p.exists())


if __name__ == '__main__':
    unittest.main()
