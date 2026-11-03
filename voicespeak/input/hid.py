"""USB and Bluetooth HID gamepads via evdev (Linux only), with hotplug.

Buttons yield "hid:<code>". Analog axes that cross a threshold yield
"hid:abs:<code>:hi" / ":lo" with a cooldown to avoid repeats. A button held
for HOLD_SECONDS also yields "hid:<code>:hold". Codes are never interpreted
here - they are mapped to actions by the input map.

Controllers are picked up whenever they appear (plugged in, paired, or a
trusted controller switched back on) and dropped when they disappear, so the
service never needs a restart for a new controller. No extra dependency:
/dev/input is rescanned every RESCAN_SECONDS.
"""

from __future__ import annotations

import select
import threading
import time
from collections.abc import Iterator

from .base import HOLD_SECONDS, InputSource

try:
    import evdev
    from evdev import ecodes
    HAVE_EVDEV = True
except ImportError:  # not on a Pi / dev machine
    HAVE_EVDEV = False

AXIS_HI = 200
AXIS_LO = 50
AXIS_COOLDOWN = 0.4
RESCAN_SECONDS = 2.0

# Linux joystick (BTN_JOYSTICK 0x120) through gamepad (BTN_THUMBR 0x13e) buttons.
GAMEPAD_KEY_RANGE = range(0x120, 0x140)
GAMEPAD_WORDS = ("controller", "gamepad", "joystick", "dualsense", "dualshock", "xbox", "8bitdo")


def is_gamepad(name: str, key_codes: list[int]) -> bool:
    """Gamepad buttons, or a gamepad-like name with keys. Keyboards and power
    buttons have neither, so they are never grabbed as a controller."""
    if any(code in GAMEPAD_KEY_RANGE for code in key_codes):
        return True
    lower = name.lower()
    return bool(key_codes) and any(word in lower for word in GAMEPAD_WORDS)


class HidSource(InputSource):
    name = "hid"

    def __init__(self, rescan_seconds: float = RESCAN_SECONDS):
        if not HAVE_EVDEV:
            raise RuntimeError("evdev not available (not a Linux/Pi host)")
        self.rescan_seconds = rescan_seconds
        self._devices: dict[str, "evdev.InputDevice"] = {}
        self._ignored: set[str] = set()
        self._lock = threading.Lock()
        self._closed = False
        self.rescan()
        if not self._devices:
            print("No controller yet. One will be used as soon as it connects.")

    def rescan(self) -> None:
        for path in evdev.list_devices():
            if path in self._devices or path in self._ignored:
                continue
            try:
                dev = evdev.InputDevice(path)
                keys = dev.capabilities().get(ecodes.EV_KEY, [])
            except OSError:
                continue
            if is_gamepad(dev.name, keys):
                with self._lock:
                    self._devices[path] = dev
                print(f"Controller connected: {dev.name}")
            else:
                self._ignored.add(path)
                dev.close()

    def connected_names(self) -> list[str]:
        with self._lock:
            return [d.name for d in self._devices.values()]

    def _drop(self, path: str) -> None:
        with self._lock:
            dev = self._devices.pop(path, None)
        if dev is not None:
            print(f"Controller disconnected: {dev.name}")
            try:
                dev.close()
            except OSError:
                pass
        # Event node numbers get reused; forget it so a new device there is checked.
        self._ignored.discard(path)

    def events(self) -> Iterator[str]:
        held: dict[tuple[str, int], float] = {}  # (path, code) -> press time
        last_axis: dict[str, float] = {}
        last_scan = time.time()
        while not self._closed:
            now = time.time()
            if now - last_scan >= self.rescan_seconds:
                self.rescan()
                last_scan = now
            with self._lock:
                by_fd = {dev.fd: (path, dev) for path, dev in self._devices.items()}
            if not by_fd:
                time.sleep(0.25)
                continue
            # Short timeout so a hold fires while the button is still down.
            ready, _, _ = select.select(list(by_fd), [], [], 0.25)
            for fd in ready:
                path, dev = by_fd[fd]
                try:
                    yield from self._read(path, dev, held, last_axis)
                except BlockingIOError:
                    pass
                except OSError:  # unplugged or out of range
                    self._drop(path)
                    for key in [k for k in held if k[0] == path]:
                        del held[key]
            now = time.time()
            for (path, code), pressed_at in list(held.items()):
                if now - pressed_at >= HOLD_SECONDS:
                    del held[(path, code)]
                    yield f"hid:{code}:hold"

    def _read(self, path, dev, held, last_axis) -> Iterator[str]:
        for event in dev.read():
            if event.type == ecodes.EV_KEY and event.value == 1:
                held[(path, event.code)] = time.time()
                yield f"hid:{event.code}"
            elif event.type == ecodes.EV_KEY and event.value == 0:
                held.pop((path, event.code), None)
            elif event.type == ecodes.EV_ABS:
                now = time.time()
                if now - last_axis.get(path, 0.0) < AXIS_COOLDOWN:
                    continue
                if event.value > AXIS_HI:
                    last_axis[path] = now
                    yield f"hid:abs:{event.code}:hi"
                elif event.value < AXIS_LO:
                    last_axis[path] = now
                    yield f"hid:abs:{event.code}:lo"

    def close(self) -> None:
        self._closed = True
        for path in list(self._devices):
            self._drop(path)
