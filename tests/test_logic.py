"""停止時刻の入力・文言・配色・スタートアップ登録・例外の記録のテスト。

Tk に依存しない関数だけを確かめる (tkinter の無い環境でも動く)。
"""
import datetime
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import applog  # noqa: E402
import settings  # noqa: E402
import startup  # noqa: E402
import stoptimer  # noqa: E402
import theme  # noqa: E402

DT = datetime.datetime


class TimeInputTests(unittest.TestCase):
    """B4: 入力中は整形せず、確定で丸める。"""

    def test_入力中に受け付けるのは数字2桁まで(self):
        for text in ('', '0', '7', '17', '23', '99'):
            with self.subTest(text=text):
                self.assertTrue(stoptimer.is_time_input_allowed(text))
        for text in ('123', 'a', '1a', ' 1', '-1', '１'):
            with self.subTest(text=text):
                self.assertFalse(stoptimer.is_time_input_allowed(text))

    def test_17の7を消して8を打つと18になる(self):
        # 以前は 1 文字ごとに2桁へ整形していたため、'1' が '01' になり、
        # カーソルの後ろに 8 が入って '018' → '23' になっていた
        text = '17'
        text = text[:1]          # 7 を消す
        self.assertTrue(stoptimer.is_time_input_allowed(text))
        text = text + '8'        # 8 を打つ
        self.assertTrue(stoptimer.is_time_input_allowed(text))
        self.assertEqual(stoptimer.normalize_time_field(text, 23, 17), '18')

    def test_確定で範囲内に丸めて2桁にする(self):
        self.assertEqual(stoptimer.normalize_time_field('7', 23, 17), '07')
        self.assertEqual(stoptimer.normalize_time_field('25', 23, 17), '23')
        self.assertEqual(stoptimer.normalize_time_field('75', 59, 0), '59')
        self.assertEqual(stoptimer.normalize_time_field('00', 59, 30), '00')

    def test_空欄は元の値に戻す(self):
        self.assertEqual(stoptimer.normalize_time_field('', 23, 17), '17')
        self.assertEqual(stoptimer.normalize_time_field('x', 59, 5), '05')

    def test_正しい値かどうか(self):
        self.assertTrue(stoptimer.time_field_valid('23', 23))
        self.assertTrue(stoptimer.time_field_valid('0', 23))
        self.assertFalse(stoptimer.time_field_valid('24', 23))
        self.assertFalse(stoptimer.time_field_valid('', 23))


class StopTargetTests(unittest.TestCase):
    def test_今日のその時刻(self):
        self.assertEqual(stoptimer.calc_stop_target(DT(2026, 11, 14, 9, 0), 17, 0),
                         DT(2026, 11, 14, 17, 0))

    def test_過ぎていれば翌日(self):
        self.assertEqual(stoptimer.calc_stop_target(DT(2026, 11, 14, 18, 0), 17, 0),
                         DT(2026, 11, 15, 17, 0))

    def test_ちょうどなら翌日(self):
        self.assertEqual(stoptimer.calc_stop_target(DT(2026, 11, 14, 17, 0), 17, 0),
                         DT(2026, 11, 15, 17, 0))

    def test_月末をまたぐ(self):
        self.assertEqual(stoptimer.calc_stop_target(DT(2026, 11, 30, 23, 0), 8, 30),
                         DT(2026, 12, 1, 8, 30))


class TextTests(unittest.TestCase):
    """U6 / U10: 状態表示とトレイの文言。"""

    def test_今日なら時刻だけ(self):
        self.assertEqual(stoptimer.stop_note(DT(2026, 11, 14, 17, 0), DT(2026, 11, 14, 9, 0)),
                         '17:00 に自動で OFF にします')

    def test_翌日なら明日(self):
        self.assertEqual(stoptimer.stop_note(DT(2026, 11, 15, 8, 5), DT(2026, 11, 14, 22, 0)),
                         '明日 08:05 に自動で OFF にします')

    def test_自動で止めた後(self):
        self.assertEqual(stoptimer.stopped_note(DT(2026, 11, 14, 17, 0)),
                         '17:00 に自動で OFF にしました')

    def test_トレイの情報行(self):
        now = DT(2026, 11, 14, 22, 0)
        self.assertEqual(stoptimer.tray_stop_label(None, now, 17, 0), '17:00 に自動で OFF')
        self.assertEqual(stoptimer.tray_stop_label(DT(2026, 11, 15, 17, 0), now, 17, 0),
                         '明日 17:00 に自動で OFF')

    def test_ツールチップ(self):
        self.assertEqual(stoptimer.tray_title(False, '17:00 に自動で OFF'), "I'm fine - OFF")
        self.assertEqual(stoptimer.tray_title(True, '17:00 に自動で OFF'),
                         "I'm fine - ON（17:00 に自動で OFF）")
        self.assertEqual(stoptimer.tray_title(True, None), "I'm fine - ON")
        # Windows のツールチップは 127 文字まで
        self.assertLess(len(stoptimer.tray_title(True, '明日 17:00 に自動で OFF')), 128)

    def test_経過時間(self):
        self.assertEqual(stoptimer.format_elapsed(0), '0:00:00')
        self.assertEqual(stoptimer.format_elapsed(5025), '1:23:45')
        self.assertEqual(stoptimer.format_elapsed(-3), '0:00:00')


class ResumeTests(unittest.TestCase):
    """B10: 更新の再起動が停止時刻をまたいだら ON に戻さない。"""

    def test_停止時刻の前なら_ON_に戻して経過時間も引き継ぐ(self):
        d = stoptimer.resume_decision(DT(2026, 11, 14, 16, 59), '2026-11-14T17:00:00',
                                      '2026-11-14T09:00:00')
        self.assertTrue(d['start'])
        self.assertEqual(d['stop_target'], DT(2026, 11, 14, 17, 0))
        self.assertEqual(d['start_time'], DT(2026, 11, 14, 9, 0))

    def test_停止時刻を過ぎていれば_ON_にしない(self):
        d = stoptimer.resume_decision(DT(2026, 11, 14, 17, 0, 30), '2026-11-14T17:00:00',
                                      '2026-11-14T09:00:00')
        self.assertFalse(d['start'])
        self.assertEqual(d['stopped_at'], DT(2026, 11, 14, 17, 0))

    def test_停止時刻が無ければ_ON_に戻す(self):
        d = stoptimer.resume_decision(DT(2026, 11, 14, 17, 0), None, None)
        self.assertTrue(d['start'])
        self.assertIsNone(d['stop_target'])
        self.assertIsNone(d['start_time'])

    def test_壊れた値は無視する(self):
        d = stoptimer.resume_decision(DT(2026, 11, 14, 17, 0), 'abc', 'xyz')
        self.assertTrue(d['start'])
        self.assertIsNone(d['stop_target'])

    def test_未来の開始時刻は使わない(self):
        d = stoptimer.resume_decision(DT(2026, 11, 14, 9, 0), None, '2026-11-15T09:00:00')
        self.assertIsNone(d['start_time'])


class ThemeTests(unittest.TestCase):
    def test_トグルの白い文字のコントラスト比は_4_5_以上(self):
        for name, t in theme.THEMES.items():
            for key in ('TOGGLE_ON', 'TOGGLE_OFF'):
                with self.subTest(theme=name, key=key):
                    self.assertGreaterEqual(theme.contrast_ratio('#FFFFFF', t[key]), 4.5)

    def test_文字のコントラスト比は_4_5_以上(self):
        for name, t in theme.THEMES.items():
            # ACCENT は状態表示 (背景 BG の上) にだけ使う
            for fg, bg in (('TEXT', 'BG'), ('TEXT', 'SURFACE'), ('MUTED', 'BG'),
                           ('MUTED', 'SURFACE'), ('ACCENT', 'BG')):
                with self.subTest(theme=name, fg=fg, bg=bg):
                    self.assertGreaterEqual(theme.contrast_ratio(t[fg], t[bg]), 4.5)

    def test_両テーマのキーがそろっている(self):
        self.assertEqual(set(theme.THEMES['light']), set(theme.THEMES['dark']))

    def test_テーマの選択(self):
        self.assertTrue(theme.resolve_dark('dark'))
        self.assertFalse(theme.resolve_dark('light'))
        with mock.patch.object(theme, 'system_prefers_dark', return_value=True):
            self.assertTrue(theme.resolve_dark('system'))

    @unittest.skipIf(sys.platform == 'win32', 'Windows ではレジストリを読む')
    def test_Windows_以外ではライト(self):
        self.assertFalse(theme.system_prefers_dark())


class StartupTests(unittest.TestCase):
    """B12: 登録値が今の exe と違えば書き直す。"""

    def test_同じなら書き直さない(self):
        cmd = startup.expected_command(True, r'C:\Tools\ImFine.exe', '')
        self.assertEqual(cmd, '"C:\\Tools\\ImFine.exe"')
        self.assertFalse(startup.needs_rewrite(cmd, cmd))
        # 大文字小文字の違いだけなら同じ場所
        self.assertFalse(startup.needs_rewrite('"c:\\tools\\imfine.exe"', cmd))

    def test_場所がずれていれば書き直す(self):
        cmd = startup.expected_command(True, r'C:\New\ImFine.exe', '')
        self.assertTrue(startup.needs_rewrite('"C:\\Old\\ImFine.exe"', cmd))

    def test_登録が無ければ書かない(self):
        self.assertFalse(startup.needs_rewrite(None, '"x"'))
        self.assertFalse(startup.needs_rewrite('', '"x"'))

    def test_sync_は登録済みで場所がずれていれば書き直す(self):
        with mock.patch.object(startup, 'read_registered', return_value='"C:\\Old\\ImFine.exe"'), \
                mock.patch.object(startup, 'current_command', return_value='"C:\\New\\ImFine.exe"'), \
                mock.patch.object(startup, 'write') as write, \
                mock.patch.object(sys, 'frozen', True, create=True):
            self.assertTrue(startup.sync())
        write.assert_called_once_with('"C:\\New\\ImFine.exe"')

    def test_sync_はソース実行では書き直さない(self):
        with mock.patch.object(startup, 'read_registered', return_value='"C:\\Old\\ImFine.exe"'), \
                mock.patch.object(startup, 'current_command', return_value='"python" "main.py"'), \
                mock.patch.object(startup, 'write') as write, \
                mock.patch.object(sys, 'frozen', False, create=True):
            self.assertTrue(startup.sync())
        write.assert_not_called()

    def test_sync_は未登録なら何もしない(self):
        with mock.patch.object(startup, 'read_registered', return_value=None), \
                mock.patch.object(startup, 'write') as write:
            self.assertFalse(startup.sync())
        write.assert_not_called()


class AppLogTests(unittest.TestCase):
    """B15: 想定外の例外を data\\app.log に日時つきで残す。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        p = mock.patch.object(settings, '_DATA_DIR', self.dir)
        p.start()
        self.addCleanup(p.stop)
        self.log = self.dir / applog.LOG_NAME

    def test_例外をトレースバックつきで書く(self):
        try:
            raise ValueError('テストの例外')
        except ValueError:
            applog.log_exception(*sys.exc_info(), where='テスト')
        text = self.log.read_text(encoding='utf-8')
        self.assertIn('想定外のエラー (テスト)', text)
        self.assertIn('ValueError: テストの例外', text)
        self.assertRegex(text, r'^\[\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\]')

    def test_上限を超えたら切り詰める(self):
        self.log.write_bytes(b'x' * 100 + b'\n' + b'y' * (applog.LOG_MAX_BYTES + 10) + b'\n')
        applog.write('新しい行')
        size = self.log.stat().st_size
        self.assertLess(size, applog.LOG_MAX_BYTES)
        self.assertIn('新しい行', self.log.read_text(encoding='utf-8'))

    def test_書けなくても例外を出さない(self):
        with mock.patch.object(settings, '_DATA_DIR', self.dir / 'missing' / 'dir'):
            applog.write('x')  # 例外にならないこと

    def test_スレッドの例外も書く(self):
        old = threading.excepthook
        self.addCleanup(setattr, threading, 'excepthook', old)
        old_sys = sys.excepthook
        self.addCleanup(setattr, sys, 'excepthook', old_sys)
        applog.install_hooks()

        def boom():
            raise RuntimeError('スレッドで失敗')

        t = threading.Thread(target=boom, name='test-thread')
        t.start()
        t.join()
        text = self.log.read_text(encoding='utf-8')
        self.assertIn('スレッド test-thread', text)
        self.assertIn('RuntimeError: スレッドで失敗', text)


if __name__ == '__main__':
    unittest.main()
