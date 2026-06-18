"""USB and Bluetooth HID gamepads via evdev (Linux only).

Buttons yield "hid:<code>". Analog axes that cross a threshold yield
"hid:abs:<code>:hi" / ":lo" with a cooldown to avoid repeats. Codes are never
interpreted here - they are mapped to actions by the input map.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

from .base import InputSource

try:
    import evdev
    from evdev import ecodes
    HAVE_EVDEV = True
except ImportError:  # not on a Pi / dev machine
    HAVE_EVDEV = False

AXIS_HI = 200
AXIS_LO = 50
AXIS_COOLDOWN = 0.4


def find_gamepad() -> "evdev.InputDevice | None":
    if not HAVE_EVDEV:
        return None
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        caps = dev.capabilities()
        # A gamepad exposes key events; prefer ones with a known gamepad name.
        name = dev.name.lower()
        if ecodes.EV_KEY in caps and (
            "controller" in name or "gamepad" in name or "joystick" in name
            or "dualsense" in name or "xbox" in name or "8bitdo" in name
        ):
            return dev
    # fall back to the first device that has gamepad buttons
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if ecodes.EV_KEY in dev.capabilities():
            return dev
    return None


class HidSource(InputSource):
    name = "hid"

    def __init__(self, device: "evdev.InputDevice | None" = None):
        if not HAVE_EVDEV:
            raise RuntimeError("evdev not available (not a Linux/Pi host)")
        self.device = device or find_gamepad()
        if self.device is None:
            raise RuntimeError("No HID gamepad found (pair or plug one in)")
        print(f"Using controller: {self.device.name}")
        self._last_axis = 0.0

    def events(self) -> Iterator[str]:
        for event in self.device.read_loop():
            if event.type == ecodes.EV_KEY and event.value == 1:
                yield f"hid:{event.code}"
            elif event.type == ecodes.EV_ABS:
                now = time.time()
                if now - self._last_axis < AXIS_COOLDOWN:
                    continue
                if event.value > AXIS_HI:
                    self._last_axis = now
                    yield f"hid:abs:{event.code}:hi"
                elif event.value < AXIS_LO:
                    self._last_axis = now
                    yield f"hid:abs:{event.code}:lo"
