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

    INPUT_KEYBOARD  = 1
    VK_F15          = 0x7E
    KEYEVENTF_KEYUP = 0x0002

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ('wVk',         ctypes.c_ushort),
            ('wScan',       ctypes.c_ushort),
            ('dwFlags',     ctypes.c_ulong),
            ('time',        ctypes.c_ulong),
            ('dwExtraInfo', ctypes.c_ulong * 2),
        ]

    class _INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [('ki', _KEYBDINPUT)]
        _anonymous_ = ('_u',)
        _fields_ = [('type', ctypes.c_ulong), ('_u', _U)]

    inputs = (_INPUT * 2)(
        _INPUT(type=INPUT_KEYBOARD, ki=_KEYBDINPUT(wVk=VK_F15, dwFlags=0)),
        _INPUT(type=INPUT_KEYBOARD, ki=_KEYBDINPUT(wVk=VK_F15, dwFlags=KEYEVENTF_KEYUP)),
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
