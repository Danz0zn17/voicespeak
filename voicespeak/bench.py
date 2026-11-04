"""Bench helpers: self-test speech while a box is unclaimed, and the
"switches seen" flag reported to the app.

Self-test: until a family connects the box, every press says what the input
is ("Red button", "Next board", "Controller bottom button. Red button.") so
wiring can be checked on the bench. Long holds keep their setup actions
(pairing mode, speak the code). Once the box is claimed, presses speak
phrases as usual.

Pure apart from the flag file, so it is unit-testable on any OS.
"""

from __future__ import annotations

from pathlib import Path

from . import config
from .models import (
    Action,
    BT_PAIR, NEXT_BOARD, PREV_BOARD, REPEAT_LAST, SCAN_NEXT, SCAN_PREV, SPEAK_CELL,
    SPEAK_CODE, SYNC,
)

# Linux gamepad codes by position, so the name is right for any brand
# (Xbox A / PlayStation cross are both the bottom button).
HID_BUTTONS = {
    304: "bottom button", 305: "right button", 307: "top button", 308: "left button",
    310: "left shoulder", 311: "right shoulder", 312: "left trigger", 313: "right trigger",
    314: "select", 315: "start", 316: "home", 317: "left stick press", 318: "right stick press",
}
HID_AXES = {0: ("stick right", "stick left"), 1: ("stick down", "stick up"),
            3: ("right stick right", "right stick left"), 4: ("right stick down", "right stick up")}


def action_name(action: Action | None) -> str:
    if action is None:
        return "Not used"
    kind = action.kind
    if kind == SPEAK_CELL:
        return {0: "Red button", 1: "Blue button"}.get(action.target, f"Phrase {(action.target or 0) + 1}")
    return {
        SCAN_NEXT: "More phrases", SCAN_PREV: "More phrases, back",
        NEXT_BOARD: "Next board", PREV_BOARD: "Previous board", REPEAT_LAST: "Repeat",
        SYNC: "Sync", BT_PAIR: "Pair a controller", SPEAK_CODE: "Say the code",
    }.get(kind, kind.replace("_", " ").capitalize())


def describe_input(input_id: str, action: Action | None) -> str:
    """What the box says for one press in self-test mode."""
    role = action_name(action)
    parts = input_id.split(":")
    if parts[0] == "gpio":
        return role if action else f"Switch on pin {parts[1]}. {role}."
    if parts[0] == "hid":
        if len(parts) >= 4 and parts[1] == "abs":
            try:
                hi, lo = HID_AXES.get(int(parts[2]), ("axis up", "axis down"))
            except ValueError:
                hi, lo = "axis up", "axis down"
            where = hi if parts[3] == "hi" else lo
        else:
            try:
                where = HID_BUTTONS.get(int(parts[1]), f"button {parts[1]}")
            except ValueError:
                where = "button"
        return f"Controller {where}. {role}."
    return role


class SwitchesSeen:
    """True once any GPIO switch has been pressed on this box, kept on disk so
    the app can tell real switches from GPIO merely being available."""

    def __init__(self, path: Path | None = None):
        self.path = path or (config.DATA_DIR / "switches_seen")
        try:
            self.seen = self.path.exists()
        except OSError:
            self.seen = False

    def note(self, input_id: str) -> bool:
        """Call for every press. Returns True the first time a switch is seen."""
        if self.seen or not input_id.startswith("gpio:"):
            return False
        self.seen = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.touch()
        except OSError as e:
            print(f"Could not save the switches flag ({e}).")
        return True


def is_hold(input_id: str) -> bool:
    return input_id.endswith(":hold")


def self_test_line(input_id: str, action: Action | None) -> str | None:
    """In self-test mode: the line to say for this press, or None when the
    press should run as usual (long holds keep their setup actions)."""
    if is_hold(input_id):
        return None
    return describe_input(input_id, action)
