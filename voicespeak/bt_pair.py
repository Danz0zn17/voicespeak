"""Bluetooth controller pairing mode, driven through bluetoothctl (BlueZ).

Scans for ~60 seconds, then pairs, trusts and connects the first gamepad-like
device it finds. Trusting means the controller reconnects on its own after a
reboot. Triggered by a long hold mapped to "bt_pair" in the input map, or by
`python3 -m voicespeak pair`.

Parsing is pure (tested); everything that touches the radio goes through
_btctl so a dev machine without BlueZ gets a clear error, never a crash.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time

SCAN_SECONDS = 60
POLL_SECONDS = 2

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


def pair_controller(scan_seconds: int = SCAN_SECONDS) -> tuple[bool, str]:
    """Returns (connected, message). Never raises."""
    if shutil.which("bluetoothctl") is None:
        return False, "bluetoothctl not found - install bluez (Raspberry Pi OS has it)"
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
    """Spoken pairing flow. Returns True when a controller connected."""
    if shutil.which("bluetoothctl") is None:
        print("Pairing unavailable: bluetoothctl not found (bluez not installed).")
        tts.speak_system("Bluetooth is not available on this device.")
        return False
    tts.speak_system("Pairing mode. Turn on your controller.")
    ok, message = pair_controller()
    print(message)
    tts.speak_system("Controller connected." if ok else "No controller found.")
    return ok
