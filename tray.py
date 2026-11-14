"""タスクトレイのアイコンとメニュー。

pystray のアイコンは別のスレッドで動く (クリックの判定タイマーやメニューの
コールバックも別スレッドから呼ばれる)。Tk はメインスレッド以外から触っては
いけないため、ここでは Tk に一切触れず、操作は commands のキューに積むだけにする。
キューはアプリのメインスレッドの定期処理が取り出して実行する。

アイコンは起動から終了まで出したままにする (トレイに格納するたびに作り直さない)。
"""
import sys
import threading

# キューに積む命令
TOGGLE = 'toggle'              # ON/OFF を切り替える
OPEN = 'open'                  # ウィンドウを開く
SETTINGS = 'settings'          # 設定を開く
CHECK_UPDATE = 'check_update'  # 更新を確認する
OPEN_DATA = 'open_data'        # データフォルダを開く
QUIT = 'quit'                  # 終了する (ON のときだけ確認)

_WM_LBUTTONUP = 0x0202
_WM_LBUTTONDBLCLK = 0x0203
_WM_RBUTTONUP = 0x0205


class ClickDetector:
    """トレイアイコンの左クリック1回 (ON/OFF) とダブルクリック (ウィンドウを開く) を見分ける。

    1回目のクリックでは、ダブルクリックの間隔だけ待ってから on_single を呼ぶ。
    その間にダブルクリックが来れば待ちを取り消して on_double を呼ぶ。
    on_single は Timer のスレッドから、on_double はアイコンのスレッドから呼ばれる。
    """

    def __init__(self, on_single, on_double, delay_sec, timer_factory=threading.Timer):
        self._on_single = on_single
        self._on_double = on_double
        self._delay_sec = delay_sec  # 数値か、数値を返す関数
        self._timer_factory = timer_factory
        self._lock = threading.Lock()
        self._click_timer = None
        self._ignore_next_up = False

    def _delay(self) -> float:
        d = self._delay_sec
        return float(d() if callable(d) else d)

    def cancel(self) -> None:
        with self._lock:
            t, self._click_timer = self._click_timer, None
        if t:
            t.cancel()

    def left_up(self) -> None:
        with self._lock:
            if self._ignore_next_up:
                # ダブルクリックの2回目のボタンを離したときの通知は無視する
                self._ignore_next_up = False
                return
        self.cancel()
        timer = None

        def fire():
            with self._lock:
                if self._click_timer is not timer:
                    return  # 取り消された
                self._click_timer = None
            self._on_single()

        timer = self._timer_factory(self._delay(), fire)
        timer.daemon = True
        with self._lock:
            self._click_timer = timer
        timer.start()

    def double(self) -> None:
        self.cancel()
        with self._lock:
            self._ignore_next_up = True
        self._on_double()


def _double_click_time() -> float:
    if sys.platform != 'win32':
        return 0.5
    try:
        import ctypes
        return ctypes.windll.user32.GetDoubleClickTime() / 1000.0
    except Exception:
        return 0.5


def build_menu_items(state_ref, post, version: str, item_cls, separator):
    """メニューの項目を作る (pystray の MenuItem と SEPARATOR を渡す)。

    state_ref() は現在の状態の dict ({'running': bool, 'stop_label': str|None}) を返す。
    文言・チェック・表示は呼び出されるたびに state_ref() から読む。
    post(cmd) はキューに命令を積む関数。項目のコールバックはこれだけを呼ぶ。
    """
    def act(cmd):
        return lambda icon, item: post(cmd)

    return (
        item_cls('ON', act(TOGGLE),
                 checked=lambda item: bool(state_ref().get('running'))),
        item_cls(lambda item: state_ref().get('stop_label') or '', None,
                 enabled=False,
                 visible=lambda item: bool(state_ref().get('stop_label'))),
        separator,
        item_cls('ウィンドウを開く', act(OPEN), default=True),
        item_cls('設定…', act(SETTINGS)),
        separator,
        item_cls('更新を確認', act(CHECK_UPDATE)),
        item_cls('データフォルダを開く', act(OPEN_DATA)),
        item_cls(f"I'm fine v{version}", None, enabled=False),
        separator,
        item_cls('終了', act(QUIT)),
    )


def _make_icon_class(pystray):
    """Windows ではクリックの扱いを変えたアイコンのクラス、それ以外は pystray.Icon。"""
    if sys.platform != 'win32':
        return pystray.Icon
    import pystray._win32

    class _WinIcon(pystray._win32.Icon):
        def __init__(self, *args, clicks: ClickDetector = None, **kwargs):
            super().__init__(*args, **kwargs)
            self._clicks = clicks

        def _on_notify(self, wparam, lparam):
            # アイコンのスレッドで呼ばれる
            if self._clicks is not None and lparam == _WM_LBUTTONDBLCLK:
                self._clicks.double()
            elif self._clicks is not None and lparam == _WM_LBUTTONUP:
                self._clicks.left_up()
            else:
                if lparam == _WM_RBUTTONUP:
                    # メニューの文言・チェックを開く直前に作り直す。メニューの
                    # ハンドルはこのスレッドだけで作り・壊すようにし、表示中の
                    # メニューをメインスレッドから壊すことが無いようにする。
                    try:
                        self.update_menu()
                    except Exception:
                        pass
                super()._on_notify(wparam, lparam)

    return _WinIcon


class Tray:
    """トレイアイコン。start / refresh / notify / stop はメインスレッドから呼ぶこと。"""

    def __init__(self, post, version: str, image_for):
        self._post = post            # 命令をキューに積む関数 (どのスレッドからでも呼べる)
        self._version = version
        self._image_for = image_for  # image_for(running) -> PIL.Image
        self._state = {'running': False, 'stop_label': None}
        self._running_shown = None
        self._pending_notes: list = []
        self._clicks: ClickDetector | None = None
        self.icon = None

    @property
    def available(self) -> bool:
        return self.icon is not None

    def _state_ref(self) -> dict:
        return self._state

    def start(self, running: bool, stop_label: str | None, title: str) -> bool:
        """アイコンを出す。pystray が使えない・作れないときは False (落とさない)。"""
        try:
            import pystray
        except Exception:
            return False
        try:
            self._state = {'running': running, 'stop_label': stop_label}
            menu = pystray.Menu(*build_menu_items(
                self._state_ref, self._post, self._version,
                pystray.MenuItem, pystray.Menu.SEPARATOR))
            cls = _make_icon_class(pystray)
            kwargs = {}
            if sys.platform == 'win32':
                self._clicks = ClickDetector(
                    on_single=lambda: self._post(TOGGLE),
                    on_double=lambda: self._post(OPEN),
                    delay_sec=_double_click_time)
                kwargs['clicks'] = self._clicks
            icon = cls("I'm fine", self._image_for(running), title, menu, **kwargs)
            self._running_shown = running
            # 表示 (visible = True) は pystray の既定の setup に任せる。
            # ここで visible = True にすると、アイコンのウィンドウがまだ別スレッドで
            # 作られていないうちに Shell_NotifyIcon が hWnd=None で呼ばれて黙って
            # 失敗し、しかも visible だけが True になって setup 側の表示も素通りする。
            icon.run_detached()
        except Exception:
            import applog
            applog.log_exception(*sys.exc_info(), where='トレイアイコンの作成')
            self.icon = None
            return False
        self.icon = icon
        return True

    def refresh(self, running: bool, stop_label: str | None, title: str) -> None:
        """状態が変わったら呼ぶ。アイコンの絵・ツールチップ・メニューを合わせる。"""
        new_state = {'running': running, 'stop_label': stop_label}
        changed = new_state != self._state
        self._state = new_state
        icon = self.icon
        if icon is None:
            return
        try:
            if self._running_shown != running:
                icon.icon = self._image_for(running)
                self._running_shown = running
            if icon.title != title:
                icon.title = title
            if changed and sys.platform != 'win32' and icon.visible:
                # Windows ではメニューを開く直前にアイコンのスレッドで作り直す
                icon.update_menu()
        except Exception:
            pass

    def notify(self, message: str) -> None:
        """通知を出す。アイコンがまだ表示されていなければ、表示されてから出す。"""
        if self.icon is None:
            return
        self._pending_notes.append(message)
        self.flush()

    def flush(self) -> None:
        """出せずにいた通知を出す (メインスレッドの定期処理から呼ぶ)。"""
        icon = self.icon
        if icon is None or not self._pending_notes:
            return
        try:
            if not icon.visible:
                return
            while self._pending_notes:
                icon.notify(self._pending_notes.pop(0))
        except Exception:
            self._pending_notes.clear()

    def stop(self) -> None:
        icon, self.icon = self.icon, None
        if self._clicks is not None:
            self._clicks.cancel()
        if icon is None:
            return
        try:
            icon.stop()
        except Exception:
            pass
