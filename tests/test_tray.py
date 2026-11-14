"""タスクトレイの処理のテスト (pystray は偽物に差し替える)。

トレイのコールバックは別スレッドで動くため、Tk に触らずキューに積むだけで
あること、アイコンの表示 (visible = True) を pystray の setup に任せていることを確かめる。
"""
import os
import queue
import sys
import threading
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import tray  # noqa: E402


class _FakeTimer:
    """threading.Timer の代わり。fire() を呼ぶまで発火しない。"""

    instances: list = []

    def __init__(self, delay, fn):
        self.delay = delay
        self.fn = fn
        self.daemon = False
        self.started = False
        self.cancelled = False
        _FakeTimer.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.fn()


class ClickDetectorTests(unittest.TestCase):
    def setUp(self):
        _FakeTimer.instances = []
        self.events = []
        self.c = tray.ClickDetector(
            on_single=lambda: self.events.append('single'),
            on_double=lambda: self.events.append('double'),
            delay_sec=0.5, timer_factory=_FakeTimer)

    def test_1回のクリックは待ってから単発(self):
        self.c.left_up()
        t = _FakeTimer.instances[-1]
        self.assertTrue(t.daemon)  # B9: 終了を妨げない
        self.assertEqual(t.delay, 0.5)
        self.assertEqual(self.events, [])
        t.fire()
        self.assertEqual(self.events, ['single'])

    def test_ダブルクリックは単発を取り消す(self):
        self.c.left_up()
        first = _FakeTimer.instances[-1]
        self.c.double()
        self.c.left_up()  # 2回目のボタンを離した通知は無視する
        first.fire()
        self.assertTrue(first.cancelled)
        self.assertEqual(self.events, ['double'])
        self.assertEqual(len(_FakeTimer.instances), 1)

    def test_取り消し後に古いタイマーが発火しても何もしない(self):
        self.c.left_up()
        old = _FakeTimer.instances[-1]
        self.c.left_up()  # 新しいタイマーに置き換わる
        new = _FakeTimer.instances[-1]
        old.cancelled = False  # cancel が間に合わず発火してしまった場合
        old.fire()
        self.assertEqual(self.events, [])
        new.fire()
        self.assertEqual(self.events, ['single'])

    def test_cancel_は二重に呼んでもよい(self):
        self.c.left_up()
        self.c.cancel()
        self.c.cancel()
        self.assertTrue(_FakeTimer.instances[-1].cancelled)


class _Item:
    """pystray.MenuItem の代わり。"""

    def __init__(self, text, action, checked=None, radio=False, default=False,
                 visible=True, enabled=True):
        self._text, self.action = text, action
        self._checked, self.default = checked, default
        self._visible, self._enabled = visible, enabled

    def _v(self, x):
        return x(self) if callable(x) else x

    @property
    def text(self):
        return self._v(self._text)

    @property
    def checked(self):
        return self._v(self._checked) if self._checked is not None else None

    @property
    def visible(self):
        return self._v(self._visible)

    @property
    def enabled(self):
        return self._v(self._enabled)


SEP = object()


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.state = {'running': True, 'stop_label': '17:00 に自動で OFF'}
        self.posted = []
        self.items = tray.build_menu_items(lambda: self.state, self.posted.append,
                                           '1.16.0', _Item, SEP)

    def _by_text(self, text):
        return next(i for i in self.items if i is not SEP and i.text == text)

    def test_並びと区切り線(self):
        texts = ['---' if i is SEP else i.text for i in self.items]
        self.assertEqual(texts, [
            'ON', '17:00 に自動で OFF', '---',
            'ウィンドウを開く', '設定…', '---',
            '更新を確認', 'データフォルダを開く', "I'm fine v1.16.0", '---',
            '終了'])

    def test_ON_のチェックは状態に追従する(self):
        on = self._by_text('ON')
        self.assertTrue(on.checked)
        self.state = {'running': False, 'stop_label': None}
        self.assertFalse(on.checked)

    def test_情報行は押せず_未設定なら出さない(self):
        info = self.items[1]
        self.assertFalse(info.enabled)
        self.assertTrue(info.visible)
        self.state = {'running': False, 'stop_label': None}
        self.assertFalse(info.visible)
        self.assertFalse(self._by_text("I'm fine v1.16.0").enabled)

    def test_既定の項目はウィンドウを開く(self):
        self.assertTrue(self._by_text('ウィンドウを開く').default)

    def test_コールバックはキューに積むだけ(self):
        expected = {
            'ON': tray.TOGGLE, 'ウィンドウを開く': tray.OPEN, '設定…': tray.SETTINGS,
            '更新を確認': tray.CHECK_UPDATE, 'データフォルダを開く': tray.OPEN_DATA,
            '終了': tray.QUIT,
        }
        for text, cmd in expected.items():
            self._by_text(text).action(object(), object())
        self.assertEqual(self.posted, list(expected.values()))


class _FakeIcon:
    """pystray.Icon の代わり。visible をいつ誰が設定したかを記録する。"""

    created: list = []

    def __init__(self, name, icon=None, title=None, menu=None, **kwargs):
        self.name, self._icon, self.title, self.menu = name, icon, title, menu
        self.kwargs = kwargs
        self._visible = False
        self.visible_set_by = []
        self.notified = []
        self.stopped = False
        self.menu_updates = 0
        self.detached = False
        _FakeIcon.created.append(self)

    @property
    def icon(self):
        return self._icon

    @icon.setter
    def icon(self, value):
        self._icon = value

    @property
    def visible(self):
        return self._visible

    @visible.setter
    def visible(self, value):
        self.visible_set_by.append(threading.current_thread().name)
        self._visible = value

    def run_detached(self, setup=None):
        self.detached = True

    def update_menu(self):
        self.menu_updates += 1

    def notify(self, message, title=None):
        self.notified.append(message)

    def stop(self):
        self.stopped = True


def _fake_pystray():
    m = types.ModuleType('pystray')
    m.Icon = _FakeIcon
    m.MenuItem = _Item
    m.Menu = type('Menu', (), {'SEPARATOR': SEP, '__init__': lambda self, *items: setattr(self, 'items', items)})
    return m


class TrayTests(unittest.TestCase):
    def setUp(self):
        _FakeIcon.created = []
        self.q = queue.Queue()
        patches = [
            mock.patch.dict(sys.modules, {'pystray': _fake_pystray()}),
            mock.patch.object(tray, '_make_icon_class', lambda pystray: _FakeIcon),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.tray = tray.Tray(self.q.put, '1.16.0', lambda running: f'img-{running}')

    def test_表示は_pystray_の_setup_に任せる(self):
        # B2: run_detached の直後に visible = True にしない
        self.assertTrue(self.tray.start(False, None, "I'm fine - OFF"))
        icon = _FakeIcon.created[-1]
        self.assertTrue(icon.detached)
        self.assertEqual(icon.visible_set_by, [])
        self.assertEqual(icon.icon, 'img-False')

    def test_表示される前の通知は表示されてから出す(self):
        self.tray.start(False, None, "I'm fine - OFF")
        icon = _FakeIcon.created[-1]
        self.tray.notify('こんにちは')
        self.assertEqual(icon.notified, [])
        icon._visible = True  # pystray の setup が表示した
        self.tray.flush()
        self.assertEqual(icon.notified, ['こんにちは'])

    def test_状態に合わせて絵とツールチップを変える(self):
        self.tray.start(False, None, "I'm fine - OFF")
        icon = _FakeIcon.created[-1]
        self.tray.refresh(True, '17:00 に自動で OFF', "I'm fine - ON（17:00 に自動で OFF）")
        self.assertEqual(icon.icon, 'img-True')
        self.assertEqual(icon.title, "I'm fine - ON（17:00 に自動で OFF）")

    def test_作れなければ_False_で落ちない(self):
        with mock.patch.object(tray, '_make_icon_class', side_effect=RuntimeError('no tray')), \
                mock.patch('applog.write'):
            self.assertFalse(self.tray.start(False, None, 'x'))
        self.assertFalse(self.tray.available)
        # 使えないトレイへの操作も落ちない
        self.tray.notify('x')
        self.tray.refresh(True, None, 'y')
        self.tray.stop()

    def test_pystray_が無ければ_False(self):
        with mock.patch.dict(sys.modules, {'pystray': None}):
            self.assertFalse(self.tray.start(False, None, 'x'))

    def test_stop_はアイコンを止める(self):
        self.tray.start(False, None, 'x')
        icon = _FakeIcon.created[-1]
        self.tray.stop()
        self.assertTrue(icon.stopped)
        self.assertFalse(self.tray.available)


if __name__ == '__main__':
    unittest.main()
