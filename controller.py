import sys
import threading
import time

from pynput import mouse as _mouse

from mover import Mover

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


class _Monitor:
    def __init__(self, on_user_move) -> None:
        self._on_user_move = on_user_move
        self._listener: _mouse.Listener | None = None
        self.active = False

    def start(self) -> None:
        self.active = True
        self._listener = _mouse.Listener(on_move=self._handle)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        self.active = False
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _handle(self, x: int, y: int) -> None:
        if self.active and self._on_user_move:
            self._on_user_move()


class Controller:
    IDLE = 'idle'
    RUNNING = 'running'
    PAUSED = 'paused'
    STOPPED = 'stopped'

    def __init__(self, ui: dict) -> None:
        self._ui = ui
        self.state = self.IDLE
        self._interval = 60.0
        self._auto_moving = False
        self._countdown_gen = 0
        self._last_user_move = 0.0

        self._mover = Mover()
        self._mover.on_before_move = lambda: setattr(self, '_auto_moving', True)
        self._mover.on_after_move = lambda: setattr(self, '_auto_moving', False)
        self._mover.on_count = self._on_count
        self._mover.on_countdown = self._on_mover_countdown

        self._monitor = _Monitor(self._on_user_move)

    def start(self, x1: int, y1: int, x2: int, y2: int, duration: float, interval: float,
              mode: str = 'ab', wiggle_px: int = 5) -> None:
        if self.state in (self.RUNNING, self.PAUSED):
            return
        self._interval = interval
        self.state = self.RUNNING
        self._mover.start(x1, y1, x2, y2, duration, interval, mode, wiggle_px)
        self._monitor.start()
        _set_execution_state(True)
        self._notify(f'移動まであと {int(interval)}秒')

    def stop(self) -> None:
        self._mover.stop()
        self._monitor.stop()
        self._cancel_countdown()
        _set_execution_state(False)
        self.state = self.STOPPED
        self._notify('停止しました')

    def _on_mover_countdown(self, remaining: float) -> None:
        if self.state == self.RUNNING:
            self._notify(f'移動まであと {int(remaining)}秒')

    def _on_count(self, count: int) -> None:
        if self.state == self.RUNNING:
            self._notify(f'動作中… 往復回数: {count}')

    def _on_user_move(self) -> None:
        if self._auto_moving:
            return
        self._last_user_move = time.monotonic()
        if self.state == self.RUNNING:
            self.state = self.PAUSED
            self._mover.pause()
            self._start_countdown()

    def _start_countdown(self) -> None:
        self._countdown_gen += 1
        gen = self._countdown_gen
        threading.Thread(target=self._countdown_loop, args=(gen,), daemon=True).start()

    def _cancel_countdown(self) -> None:
        self._countdown_gen += 1

    def _countdown_loop(self, gen: int) -> None:
        while True:
            if self._countdown_gen != gen:
                return
            elapsed = time.monotonic() - self._last_user_move
            remaining = self._interval - elapsed
            if remaining <= 0:
                break
            self._notify(f'一時停止中 / 再開まであと {int(remaining) + 1}秒')
            time.sleep(0.5)
        if self._countdown_gen == gen and self.state == self.PAUSED:
            self.state = self.RUNNING
            self._mover.resume()
            self._notify(f'動作中… 往復回数: {self._mover.count}')

    def _notify(self, msg: str) -> None:
        if cb := self._ui.get('status'):
            cb(msg)
