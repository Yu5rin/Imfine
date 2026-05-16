from pynput import mouse as _mouse


class Monitor:
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
