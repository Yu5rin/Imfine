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

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [('dx', ctypes.c_long), ('dy', ctypes.c_long),
                    ('mouseData', ctypes.c_ulong), ('dwFlags', ctypes.c_ulong),
                    ('time', ctypes.c_ulong), ('dwExtraInfo', ctypes.c_ulong)]

    class _INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [('mi', _MOUSEINPUT)]
        _anonymous_ = ('_u',)
        _fields_ = [('type', ctypes.c_ulong), ('_u', _U)]

    MOUSEEVENTF_MOVE = 0x0001
    inputs = (_INPUT * 2)(
        _INPUT(type=0, mi=_MOUSEINPUT(dx=1,  dy=0, dwFlags=MOUSEEVENTF_MOVE)),
        _INPUT(type=0, mi=_MOUSEINPUT(dx=-1, dy=0, dwFlags=MOUSEEVENTF_MOVE)),
    )
    ctypes.windll.user32.SendInput(2, inputs, ctypes.sizeof(_INPUT))


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
        self._stop_ev.clear()
        threading.Thread(target=self._loop, daemon=True).start()
        self._notify('動作中')

    def stop(self) -> None:
        self._stop_ev.set()
        _set_execution_state(False)
        self.state = self.STOPPED
        self._notify('停止しました')

    def _loop(self) -> None:
        while not self._stop_ev.wait(30):
            if self.state == self.RUNNING:
                _send_heartbeat()

    def _notify(self, msg: str) -> None:
        if cb := self._ui.get('status'):
            cb(msg)
