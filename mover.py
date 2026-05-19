import threading
import time

import pyautogui

pyautogui.FAILSAFE = False


class Mover:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._skip_next_wait = False
        self.count = 0
        self.on_count = None
        self.on_before_move = None
        self.on_after_move = None
        self.on_countdown = None

    def start(self, x1: int, y1: int, x2: int, y2: int, duration: float, interval: float) -> None:
        self._stop_event.clear()
        self._pause_event.clear()
        self._skip_next_wait = False
        self.count = 0
        self._thread = threading.Thread(
            target=self._run,
            args=(x1, y1, x2, y2, duration, interval),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._pause_event.clear()

    def pause(self) -> None:
        self._skip_next_wait = True
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def _run(self, x1: int, y1: int, x2: int, y2: int, duration: float, interval: float) -> None:
        pts = [(x1, y1), (x2, y2)]
        idx = 0
        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                time.sleep(0.05)
                continue

            if not self._skip_next_wait:
                elapsed = 0.0
                last_shown = -1
                while elapsed < interval:
                    if self._stop_event.is_set():
                        return
                    if self._pause_event.is_set():
                        break
                    remaining = interval - elapsed
                    cur = int(remaining)
                    if cur != last_shown:
                        if self.on_countdown:
                            self.on_countdown(remaining)
                        last_shown = cur
                    time.sleep(0.05)
                    elapsed += 0.05
                if self._stop_event.is_set() or self._pause_event.is_set():
                    continue
            else:
                self._skip_next_wait = False

            if self.on_before_move:
                self.on_before_move()
            pyautogui.moveTo(pts[idx][0], pts[idx][1], duration=duration)
            if self.on_after_move:
                self.on_after_move()

            self.count += 1
            idx ^= 1
            if self.on_count:
                self.on_count(self.count)
