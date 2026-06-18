"""Input abstraction.

Every input source yields opaque string ids like "hid:304" or "gpio:17". The
engine never knows about a specific controller - the dashboard/setup binds ids
to actions in the input map. This is what makes the device universal.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator


class InputSource:
    """Subclasses implement events() yielding input-id strings."""

    name = "input"

    def events(self) -> Iterator[str]:
        raise NotImplementedError

    def close(self) -> None:
        pass


def merge(sources: list[InputSource]) -> Iterator[str]:
    """Run every source on its own thread, yield ids from a shared queue."""
    q: queue.Queue[str] = queue.Queue()

    def pump(src: InputSource) -> None:
        try:
            for input_id in src.events():
                q.put(input_id)
        except Exception as e:  # noqa: BLE001 - one source dying must not kill all
            print(f"Input source '{src.name}' stopped: {e}")

    for src in sources:
        threading.Thread(target=pump, args=(src,), daemon=True).start()

    while True:
        yield q.get()
