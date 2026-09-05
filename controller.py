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
    u32.keybd_event(0x7E, 0, 0, 0)
    u32.keybd_event(0x7E, 0, 2, 0)
    u32.mouse_event(0x0001,  1, 0, 0, 0)
    u32.mouse_event(0x0001, -1, 0, 0, 0)


class Controller:
    IDLE    = 'idle'
    RUNNING = 'running'
    STOPPED = 'stopped'

    def __init__(self, ui=None) -> None:
        # ui 引数は後方互換のために残しているが使用しない
        # (以前は self._ui.get('status') が常に None を返す死んだコードだった)。
        self.state = self.IDLE
        self._stop_ev = threading.Event()

    def start(self) -> None:
        if self.state == self.RUNNING:
            return
        self.state = self.RUNNING
        _set_execution_state(True)
        self._stop_ev = threading.Event()
        threading.Thread(target=self._loop, args=(self._stop_ev,),
                         daemon=True).start()

    def stop(self) -> None:
        self._stop_ev.set()
        _set_execution_state(False)
        self.state = self.STOPPED

    def _loop(self, stop_ev: threading.Event) -> None:
        while not stop_ev.wait(30):
            if self.state == self.RUNNING and stop_ev is self._stop_ev:
                _send_heartbeat()
