"""Engine logic tests - pure Python, no hardware. Run: python3 -m pytest -q

Covers the bugs fixed during consolidation: scan starts at the first cell
(no off-by-one) and the scan pointer resets on board change.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from voice_speak.engine import Engine
from voice_speak.models import (
    Action, Board, Cell,
    NEXT_BOARD, REPEAT_LAST, SCAN_NEXT, SCAN_PREV, SPEAK_CELL, SYNC,
)


class FakeTTS:
    def __init__(self):
        self.spoken = []
        self.system = []

    def speak(self, text):
        self.spoken.append(text)

    def speak_system(self, text):
        self.system.append(text)


def make_engine(on_sync=None):
    boards = [
        Board("Kitchen", [Cell("Apple", "Apple"), Cell("Juice", "Juice")]),
        Board("Feelings", [Cell("Happy", "I am happy")]),
    ]
    tts = FakeTTS()
    return Engine(boards, tts, on_sync=on_sync), tts


def test_scan_starts_at_first_cell():
    eng, tts = make_engine()
    eng.dispatch(Action(SCAN_NEXT))
    assert tts.spoken == ["Apple"]  # not "Juice" - off-by-one is fixed


def test_scan_wraps():
    eng, tts = make_engine()
    eng.dispatch(Action(SCAN_NEXT))  # Apple
    eng.dispatch(Action(SCAN_NEXT))  # Juice
    eng.dispatch(Action(SCAN_NEXT))  # wrap -> Apple
    assert tts.spoken == ["Apple", "Juice", "Apple"]


def test_scan_prev():
    eng, tts = make_engine()
    eng.dispatch(Action(SCAN_PREV))  # -1 -> wraps to last (Juice)
    assert tts.spoken == ["Juice"]


def test_board_change_resets_scan():
    eng, tts = make_engine()
    eng.dispatch(Action(SCAN_NEXT))   # Kitchen -> Apple
    eng.dispatch(Action(NEXT_BOARD))  # -> Feelings, scan reset
    eng.dispatch(Action(SCAN_NEXT))   # should be first cell of Feelings
    assert tts.spoken == ["Apple", "I am happy"]
    assert eng.scan_idx == 0


def test_speak_cell_bounds():
    eng, tts = make_engine()
    eng.dispatch(Action(SPEAK_CELL, target=0))
    eng.dispatch(Action(SPEAK_CELL, target=99))  # out of range - ignored
    assert tts.spoken == ["Apple"]


def test_repeat_last():
    eng, tts = make_engine()
    eng.dispatch(Action(SPEAK_CELL, target=1))  # Juice
    eng.dispatch(Action(REPEAT_LAST))
    assert tts.spoken == ["Juice", "Juice"]


def test_empty_phrase_not_spoken():
    boards = [Board("B", [Cell("blank", "")])]
    tts = FakeTTS()
    eng = Engine(boards, tts)
    eng.dispatch(Action(SPEAK_CELL, target=0))
    assert tts.spoken == []


def test_sync_replaces_boards():
    def on_sync():
        return [Board("New", [Cell("Hi", "Hello")])]

    eng, tts = make_engine(on_sync=on_sync)
    eng.dispatch(Action(SYNC))
    assert eng.board.name == "New"
    assert "Phrases synced." in tts.system


def test_sync_failure_recovers():
    def on_sync():
        raise RuntimeError("offline")

    eng, tts = make_engine(on_sync=on_sync)
    eng.dispatch(Action(SYNC))
    assert eng.board.name == "Kitchen"  # unchanged
    assert "Sync failed." in tts.system


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
