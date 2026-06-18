"""GPIO switches/buttons (Tier 1 - the most accessible input for CP users).

Each configured BCM pin yields "gpio:<pin>" on press. Uses gpiozero, which
handles debounce and pull-ups.
"""

from __future__ import annotations

import queue
from collections.abc import Iterator

from .base import InputSource

try:
    from gpiozero import Button
    HAVE_GPIO = True
except ImportError:  # not on a Pi / dev machine
    HAVE_GPIO = False


class GpioSource(InputSource):
    name = "gpio"

    def __init__(self, pins: list[int], bounce_time: float = 0.05):
        if not HAVE_GPIO:
            raise RuntimeError("gpiozero not available (not a Pi host)")
        if not pins:
            raise RuntimeError("No GPIO pins configured")
        self._q: queue.Queue[str] = queue.Queue()
        self._buttons = []
        for pin in pins:
            btn = Button(pin, bounce_time=bounce_time)
            btn.when_pressed = lambda p=pin: self._q.put(f"gpio:{p}")
            self._buttons.append(btn)
        print(f"Listening on GPIO pins: {pins}")

    def events(self) -> Iterator[str]:
        while True:
            yield self._q.get()

    def close(self) -> None:
        for btn in self._buttons:
            btn.close()
