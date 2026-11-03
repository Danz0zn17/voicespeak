"""Bluetooth controller pairing mode, driven through bluetoothctl (BlueZ).

Scans for ~60 seconds, then pairs, trusts and connects the first gamepad-like
device it finds. Trusting means the controller reconnects on its own after a
reboot. Triggered by a long hold mapped to "bt_pair" in the input map, the
"Pair a controller" command from the app, `python3 -m voicespeak pair`, or
automatically for a few minutes after boot when no controller is connected.

Parsing is pure (tested); everything that touches the radio goes through
_btctl so a dev machine without BlueZ gets a clear error, never a crash.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable

SCAN_SECONDS = 60
AUTO_PAIR_SECONDS = 180
POLL_SECONDS = 2

# One pairing at a time: the boot window, a held button and an app command
# can all ask for it.
_PAIRING = threading.Lock()

_DEVICE_LINE = re.compile(r"Device ((?:[0-9A-F]{2}:){5}[0-9A-F]{2}) (.+)$", re.I)

GAMEPAD_WORDS = (
    "controller", "gamepad", "joystick", "joy-con", "8bitdo", "xbox",
    "dualsense", "dualshock", "wireless controller", "pro controller",
)


def parse_devices(output: str) -> list[tuple[str, str]]:
    """bluetoothctl `devices` / scan output -> [(MAC, name)], de-duplicated."""
    seen: dict[str, str] = {}
    for line in output.splitlines():
        # Strip ANSI colour codes and "[NEW]" / "[CHG]" prefixes.
        line = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        if line.startswith("[CHG]"):  # property change, not a device listing
            continue
        m = _DEVICE_LINE.search(line)
        if not m:
            continue
        mac, name = m.group(1).upper(), m.group(2).strip()
        # A nameless device reports its MAC (with dashes) as the name.
        if mac not in seen or seen[mac] == mac.replace(":", "-"):
            seen[mac] = name
    return list(seen.items())


def is_gamepad_name(name: str) -> bool:
    lower = name.lower()
    return any(word in lower for word in GAMEPAD_WORDS)


def pick_gamepad(
    devices: list[tuple[str, str]], skip: set[str] = frozenset(),
) -> tuple[str, str] | None:
    for mac, name in devices:
        if mac not in skip and is_gamepad_name(name):
            return mac, name
    return None


def _btctl(*args: str, timeout: float = 20) -> str:
    result = subprocess.run(
        ["bluetoothctl", *args], capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout + result.stderr


def _paired() -> set[str]:
    # BlueZ 5.66+ uses "devices Paired"; older releases use "paired-devices".
    out = _btctl("devices", "Paired")
    if "Invalid" in out or "not available" in out:
        out = _btctl("paired-devices")
    return {mac for mac, _ in parse_devices(out)}


def bt_available() -> bool:
    return shutil.which("bluetoothctl") is not None


def pair_controller(
    scan_seconds: int = SCAN_SECONDS,
    stop_when: Callable[[], bool] | None = None,
) -> tuple[bool, str]:
    """Returns (connected, message). Never raises.

    stop_when is polled during the scan; when it turns true (e.g. a trusted
    controller reconnected by itself) the scan ends early with "already".
    """
    if not bt_available():
        return False, "bluetoothctl not found - install bluez (Raspberry Pi OS has it)"
    if not _PAIRING.acquire(blocking=False):
        return False, "Pairing already in progress"
    try:
        return _pair(scan_seconds, stop_when)
    finally:
        _PAIRING.release()


def _pair(scan_seconds: int, stop_when: Callable[[], bool] | None) -> tuple[bool, str]:
    try:
        # Each bluetoothctl call registers its own default agent, which accepts
        # the "just works" pairing that gamepads use.
        _btctl("power", "on")
        _btctl("pairable", "on")
        already = _paired()
        scan = subprocess.Popen(
            ["bluetoothctl", "--timeout", str(scan_seconds), "scan", "on"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + scan_seconds
            found = None
            while time.time() < deadline and found is None:
                time.sleep(POLL_SECONDS)
                if stop_when and stop_when():
                    return False, "already"
                found = pick_gamepad(parse_devices(_btctl("devices")), skip=already)
        finally:
            scan.terminate()
        if found is None:
            return False, "No new controller found"

        mac, name = found
        print(f"Pairing {name} ({mac})...")
        out = _btctl("pair", mac, timeout=30)
        if "Pairing successful" not in out and "AlreadyExists" not in out:
            return False, f"Pairing {name} failed: {out.strip()[-200:]}"
        _btctl("trust", mac)
        out = _btctl("connect", mac, timeout=30)
        if "Connection successful" not in out:
            return False, f"{name} paired but did not connect: {out.strip()[-200:]}"
        return True, f"Connected {name}"
    except Exception as e:  # noqa: BLE001 - pairing must not crash the device
        return False, f"Bluetooth error: {e}"


def run_pairing_mode(tts) -> bool:
    """Spoken pairing flow (button hold, app command, CLI).
    Returns True when a controller connected."""
    if not bt_available():
        print("Pairing unavailable: bluetoothctl not found (bluez not installed).")
        tts.speak_system("Bluetooth is not available on this device.")
        return False
    if _PAIRING.locked():
        tts.speak_system("Already looking for a controller. Turn yours on in pairing mode.")
        return False
    tts.speak_system("Pairing mode. Turn on your controller.")
    ok, message = pair_controller()
    print(message)
    tts.speak_system("Controller connected." if ok else "No controller found.")
    return ok


def should_auto_pair(bt: bool, controllers: list[str]) -> bool:
    """Boot window only when Bluetooth exists and no controller is connected."""
    return bt and not controllers


def auto_pair_window(tts, has_gpio: bool, controllers: Callable[[], list[str]],
                     seconds: int = AUTO_PAIR_SECONDS) -> bool:
    """Quietly look for a controller in pairing mode for a few minutes after boot.

    Only asks out loud when the box has no switches either (otherwise a child
    with switches would hear it every boot). Stops early when a trusted
    controller reconnects on its own. Returns True when a new one paired.
    """
    if not should_auto_pair(bt_available(), controllers()):
        return False
    print(f"No controller connected; looking for one for {seconds // 60} minutes.")
    if not has_gpio:
        tts.speak_system("Turn on your controller in pairing mode.")
    ok, message = pair_controller(seconds, stop_when=lambda: bool(controllers()))
    print(f"Auto-pair: {message}")
    if ok:
        tts.speak_system("Controller connected.")
    return ok
