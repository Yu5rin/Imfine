import sys
import threading

_ES_CONTINUOUS       = 0x80000000
_ES_SYSTEM_REQUIRED  = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


def _set_execution_state(active: bool) -> None:
    if sys.platform != 'win32':
        return
    import ctypes
    flags = _ES_CONTINUOUS
    if active:
        flags |= _ES_DISPLAY_REQUIRED | _ES_SYSTEM_REQUIRED
    ctypes.windll.kernel32.SetThreadExecutionState(flags)


def _send_heartbeat() -> None:
    if sys.platform != 'win32':
        return
    import ctypes
    u32 = ctypes.windll.user32
    # F15 キー (VK=0x7E) — GetLastInputInfo をリセット、画面上の変化なし
    u32.keybd_event(0x7E, 0, 0, 0)          # key down
    u32.keybd_event(0x7E, 0, 2, 0)          # key up
    # マウス微小移動 — Teams 独自の検出にも対応
    u32.mouse_event(0x0001,  1, 0, 0, 0)    # MOUSEEVENTF_MOVE +1px
    u32.mouse_event(0x0001, -1, 0, 0, 0)    # -1px (戻す)


class Controller:
    IDLE    = 'idle'
    RUNNING = 'running'
    STOPPED = 'stopped'

    def __init__(self, ui: dict) -> None:
        self._ui = ui
        self.state = self.IDLE
        self._stop_ev = threading.Event()

    def start(self) -> None:
        if self.state == self.RUNNING:
            return
        self.state = self.RUNNING
        _set_execution_state(True)
        # stop 直後に start しても旧ループが生き残らないよう毎回新しい Event を使う
        self._stop_ev = threading.Event()
        threading.Thread(target=self._loop, args=(self._stop_ev,),
                         daemon=True).start()
        self._notify('動作中')

    def stop(self) -> None:
        self._stop_ev.set()
        _set_execution_state(False)
        self.state = self.STOPPED
        self._notify('停止しました')

    def _loop(self, stop_ev: threading.Event) -> None:
        while not stop_ev.wait(30):
            if self.state == self.RUNNING and stop_ev is self._stop_ev:
                _send_heartbeat()

    def _notify(self, msg: str) -> None:
        if cb := self._ui.get('status'):
            cb(msg)
