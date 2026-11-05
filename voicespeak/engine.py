"""The logic engine: holds board state and turns Actions into speech.

Pure Python, no hardware or network imports, so it is unit-testable on any OS.
Fixes the legacy bugs: scan starts at the first cell (no off-by-one) and the
scan pointer resets when the board changes.

Boards can be swapped from the background sync thread (replace_boards); a lock
keeps that swap atomic with respect to a press being handled.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from .models import (
    Action, Board,
    BT_PAIR, NEXT_BOARD, PREV_BOARD, REPEAT_LAST, SCAN_NEXT, SCAN_PREV, SPEAK_CELL,
    SYNC,
)


class Engine:
    def __init__(
        self,
        boards: list[Board],
        tts,
        on_sync: Callable[[], list[Board]] | None = None,
        on_pair: Callable[[], None] | None = None,
    ):
        if not boards:
            raise ValueError("Engine needs at least one board")
        self.boards = boards
        self.tts = tts
        self.on_sync = on_sync
        self.on_pair = on_pair
        self._lock = threading.RLock()
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

    def _scan(self, step: int) -> None:
        """Move the scan pointer by step, skipping empty slots, and speak."""
        cells = self.board.cells
        n = len(cells)
        if not any(c.phrase for c in cells):
            return
        # From the unset state (-1) forward lands on the first spoken cell,
        # backward on the last one.
        idx = self.scan_idx
        if idx == -1:
            idx = -1 if step > 0 else n
        for _ in range(n):
            idx = (idx + step) % n
            if cells[idx].phrase:
                break
        self.scan_idx = idx
        self._speak(cells[idx].phrase)

    def scan_next(self) -> None:
        self._scan(1)

    def scan_prev(self) -> None:
        self._scan(-1)

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

    def replace_boards(self, boards: list[Board]) -> None:
        """Swap in new boards (background sync). Silent: no prompt interrupts
        the user. Stays on the same board by name when it still exists."""
        if not boards:
            return
        with self._lock:
            current = self.board.name
            self.boards = boards
            names = [b.name for b in boards]
            self.board_idx = names.index(current) if current in names else 0
            self.scan_idx = -1

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
            with self._lock:
                self.boards = boards
                self.board_idx = 0
                self.scan_idx = -1
            self._say_system("Phrases synced.")

    def dispatch(self, action: Action) -> None:
        if action.kind == BT_PAIR:
            if self.on_pair:
                self.on_pair()
            return
        with self._lock:
            self._dispatch(action)

    def _dispatch(self, action: Action) -> None:
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
