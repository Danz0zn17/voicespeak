"""Core data models, independent of cloud schema or hardware.

A Board is a named screen of Cells. A Cell is one speakable tile. An InputMap
binds a physical input id (e.g. "gpio:17" or "hid:304") to an Action.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Action kinds
SPEAK_CELL = "speak_cell"   # target = cell index on the current board
SCAN_NEXT = "scan_next"     # advance the scan pointer and speak that cell
SCAN_PREV = "scan_prev"     # step the scan pointer back and speak that cell
NEXT_BOARD = "next_board"
PREV_BOARD = "prev_board"
REPEAT_LAST = "repeat_last"
SYNC = "sync"

ACTION_KINDS = {
    SPEAK_CELL, SCAN_NEXT, SCAN_PREV, NEXT_BOARD, PREV_BOARD, REPEAT_LAST, SYNC,
}


@dataclass
class Cell:
    label: str
    phrase: str
    position: int = 0
    symbol_url: str = ""
    color: str = ""


@dataclass
class Board:
    name: str
    cells: list[Cell] = field(default_factory=list)


@dataclass
class Action:
    kind: str
    target: int | None = None  # cell index for SPEAK_CELL

    @staticmethod
    def from_dict(d: dict) -> "Action":
        kind = d["kind"]
        if kind not in ACTION_KINDS:
            raise ValueError(f"Unknown action kind: {kind}")
        return Action(kind=kind, target=d.get("target"))
