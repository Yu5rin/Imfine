"""settings.py の保存先 (data フォルダ) の決定・フォールバック・引き継ぎのテスト。

本物の %APPDATA% やホームを汚さないよう、すべて一時ディレクトリと
環境変数・sys.executable・sys.frozen のモックで行う。
"""
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import settings  # noqa: E402
import updater  # noqa: E402

REPO_DIR = pathlib.Path(settings.__file__).resolve().parent


class _Env(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name).resolve()
        self.home = self.tmp / 'home'
        self.appdata = self.tmp / 'appdata'
        self.exe_dir = self.tmp / 'app'
        for d in (self.home, self.appdata, self.exe_dir):
            d.mkdir()
        self.fake_base = self.appdata  # _appdata_base() の戻り値
        for p in (
            mock.patch.object(settings, '_appdata_base', lambda: self.fake_base),
            mock.patch.object(settings, '_DATA_DIR', None),
            mock.patch.object(sys, 'executable', str(self.exe_dir / 'ImFine.exe')),
        ):
            p.start()
            self.addCleanup(p.stop)

    def frozen(self):
        p = mock.patch.object(sys, 'frozen', True, create=True)
        p.start()
        self.addCleanup(p.stop)

    def put(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


class DataDirTests(_Env):
    def test_frozen_uses_data_next_to_exe(self):
        self.frozen()
        d = settings.data_dir()
        self.assertEqual(d, self.exe_dir / 'data')
        self.assertTrue(d.is_dir())

    def test_source_run_uses_repo_data(self):
        with mock.patch.object(settings, '_can_write_dir', return_value=True):
            self.assertEqual(settings.data_dir(), REPO_DIR / 'data')

    def test_falls_back_to_appdata_when_not_writable(self):
        self.frozen()
        with mock.patch.object(settings, '_can_write_dir', return_value=False):
            d = settings.data_dir()
        self.assertEqual(d, self.appdata / 'ImFine')
        self.assertTrue(d.is_dir())
        self.assertFalse((self.exe_dir / 'data' / 'x').exists())

    def test_can_write_dir_really_checks(self):
        ok = self.tmp / 'ok'
        self.assertTrue(settings._can_write_dir(ok))
        self.assertEqual(os.listdir(ok), [])  # 判定用の一時ファイルは残さない
        blocker = self.tmp / 'file'
        blocker.write_text('x')
        self.assertFalse(settings._can_write_dir(blocker / 'data'))

    def test_result_is_cached(self):
        self.frozen()
        first = settings.data_dir()
        with mock.patch.object(settings, '_can_write_dir') as m:
            self.assertEqual(settings.data_dir(), first)
        m.assert_not_called()


class MigrationTests(_Env):
    def setUp(self):
        super().setUp()
        self.frozen()
        self.new = self.exe_dir / 'data' / 'settings.json'
        self.imfine = self.appdata / 'ImFine' / 'settings.json'
        self.mouser = self.appdata / 'Mouser' / 'settings.json'

    def test_copies_from_imfine_and_keeps_original(self):
        self.put(self.imfine, '{"theme": "dark"}')
        self.put(self.mouser, '{"theme": "light"}')
        self.assertEqual(settings._get_path(), self.new)
        self.assertEqual(self.new.read_text(encoding='utf-8'), '{"theme": "dark"}')
        self.assertTrue(self.imfine.exists())
        self.assertTrue(self.mouser.exists())
        self.assertEqual(settings.load()['theme'], 'dark')

    def test_copies_from_mouser_when_no_imfine(self):
        self.put(self.mouser, '{"theme": "dark"}')
        settings._get_path()
        self.assertEqual(self.new.read_text(encoding='utf-8'), '{"theme": "dark"}')
        self.assertTrue(self.mouser.exists())

    def test_does_not_overwrite_existing(self):
        self.put(self.new, '{"theme": "light"}')
        self.put(self.imfine, '{"theme": "dark"}')
        settings._get_path()
        self.assertEqual(self.new.read_text(encoding='utf-8'), '{"theme": "light"}')

    def test_fallback_to_appdata_does_not_copy_onto_itself(self):
        self.put(self.imfine, '{"theme": "dark"}')
        with mock.patch.object(settings, '_can_write_dir', return_value=False):
            self.assertEqual(settings._get_path(), self.imfine)
        self.assertEqual(self.imfine.read_text(encoding='utf-8'), '{"theme": "dark"}')

    def test_fallback_still_migrates_from_mouser(self):
        self.put(self.mouser, '{"theme": "dark"}')
        with mock.patch.object(settings, '_can_write_dir', return_value=False):
            self.assertEqual(settings._get_path(), self.imfine)
        self.assertEqual(self.imfine.read_text(encoding='utf-8'), '{"theme": "dark"}')

    def test_save_and_update_write_to_data(self):
        settings.update(theme='dark')
        self.assertTrue(self.new.exists())
        self.assertFalse(self.imfine.exists())


class LogTests(_Env):
    def test_log_written_to_data_dir(self):
        self.frozen()
        updater._log('テスト')
        log = self.exe_dir / 'data' / 'update.log'
        self.assertIn('テスト', log.read_text(encoding='utf-8'))
        self.assertFalse((self.appdata / 'ImFine').exists())


class UpdaterKeepsDataTests(_Env):
    def test_cleanup_leaves_data_alone(self):
        self.frozen()
        data = settings.data_dir()
        (data / 'settings.json').write_text('{}')
        exe = pathlib.Path(sys.executable)
        exe.write_text('x')
        pathlib.Path(str(exe) + '.old').write_text('old')
        with mock.patch.object(updater, '_log'):
            updater.recover_or_cleanup()
        self.assertFalse(pathlib.Path(str(exe) + '.old').exists())
        self.assertTrue((data / 'settings.json').exists())


if __name__ == '__main__':
    unittest.main()
