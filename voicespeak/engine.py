"""The logic engine: holds board state and turns Actions into speech.

Pure Python, no hardware or network imports, so it is unit-testable on any OS.
Fixes the legacy bugs: scan starts at the first cell (no off-by-one) and the
scan pointer resets when the board changes.
"""

from __future__ import annotations

from collections.abc import Callable

from .models import (
    Action, Board,
    NEXT_BOARD, PREV_BOARD, REPEAT_LAST, SCAN_NEXT, SCAN_PREV, SPEAK_CELL, SYNC,
)


class Engine:
    def __init__(
        self,
        boards: list[Board],
        tts,
        on_sync: Callable[[], list[Board]] | None = None,
    ):
        if not boards:
            raise ValueError("Engine needs at least one board")
        self.boards = boards
        self.tts = tts
        self.on_sync = on_sync
        self.board_idx = 0
        self.scan_idx = -1  # -1 so the first SCAN_NEXT lands on cell 0
        self.last_phrase = ""

    @property
    def board(self) -> Board:
        return self.boards[self.board_idx]

    def _speak(self, phrase: str) -> None:
        if not phrase:
            return
        self.last_phrase = phrase
        self.tts.speak(phrase)

    def _say_system(self, phrase: str) -> None:
        self.tts.speak_system(phrase)

    def speak_cell(self, idx: int | None) -> None:
        if idx is None:
            return
        cells = self.board.cells
        if 0 <= idx < len(cells):
            self._speak(cells[idx].phrase)

    def scan_next(self) -> None:
        cells = self.board.cells
        if not cells:
            return
        # From the unset state (-1) the first press lands on the first cell.
        self.scan_idx = 0 if self.scan_idx == -1 else (self.scan_idx + 1) % len(cells)
        self._speak(cells[self.scan_idx].phrase)

    def scan_prev(self) -> None:
        cells = self.board.cells
        if not cells:
            return
        # From the unset state (-1) the first press lands on the last cell.
        self.scan_idx = len(cells) - 1 if self.scan_idx == -1 else (self.scan_idx - 1) % len(cells)
        self._speak(cells[self.scan_idx].phrase)

    def next_board(self) -> None:
        self.board_idx = (self.board_idx + 1) % len(self.boards)
        self.scan_idx = -1
        self._say_system(f"Board: {self.board.name}")

    def prev_board(self) -> None:
        self.board_idx = (self.board_idx - 1) % len(self.boards)
        self.scan_idx = -1
        self._say_system(f"Board: {self.board.name}")

    def repeat_last(self) -> None:
        if self.last_phrase:
            self.tts.speak(self.last_phrase)

    def sync(self) -> None:
        if not self.on_sync:
            return
        try:
            boards = self.on_sync()
        except Exception as e:  # noqa: BLE001 - report and recover
            print(f"Sync error: {e}")
            self._say_system("Sync failed.")
            return
        if boards:
            self.boards = boards
            self.board_idx = 0
            self.scan_idx = -1
            self._say_system("Phrases synced.")

    def dispatch(self, action: Action) -> None:
        if action.kind == SPEAK_CELL:
            self.speak_cell(action.target)
        elif action.kind == SCAN_NEXT:
            self.scan_next()
        elif action.kind == SCAN_PREV:
            self.scan_prev()
        elif action.kind == NEXT_BOARD:
            self.next_board()
        elif action.kind == PREV_BOARD:
            self.prev_board()
        elif action.kind == REPEAT_LAST:
            self.repeat_last()
        elif action.kind == SYNC:
            self.sync()
