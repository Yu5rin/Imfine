import threading
import time

import pyautogui

pyautogui.FAILSAFE = True


class Mover:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self.count = 0
        self.on_count = None
        self.on_emergency_stop = None
        self.on_before_move = None
        self.on_after_move = None

    def start(self, x1: int, y1: int, x2: int, y2: int, duration: float, interval: float) -> None:
        self._stop_event.clear()
        self._pause_event.clear()
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
            try:
                if self.on_before_move:
                    self.on_before_move()
                pyautogui.moveTo(pts[idx][0], pts[idx][1], duration=duration)
                if self.on_after_move:
                    self.on_after_move()
            except pyautogui.FailSafeException:
                if self.on_after_move:
                    self.on_after_move()
                if self.on_emergency_stop:
                    self.on_emergency_stop()
                return

            self.count += 1
            idx ^= 1
            if self.on_count:
                self.on_count(self.count)

            elapsed = 0.0
            while elapsed < interval and not self._stop_event.is_set() and not self._pause_event.is_set():
                time.sleep(0.05)
                elapsed += 0.05
