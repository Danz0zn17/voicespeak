"""Background sync change detection - no network. Run: python3 -m pytest -q"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from voicespeak import sync
from voicespeak.engine import Engine
from voicespeak.models import Action, Board, Cell, SCAN_NEXT, SPEAK_CELL
from voicespeak.sync import BackgroundSync, boards_digest


class FakeTTS:
    def __init__(self):
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)

    def speak_system(self, text):
        pass


def boards(phrase="Apple"):
    return [Board("Kitchen", [Cell("A", phrase)]), Board("Feelings", [Cell("H", "Happy")])]


def make_syncer(monkeypatch, fetch, current=None):
    monkeypatch.setattr(sync, "_save_local", lambda b: None)
    applied, cached = [], []
    syncer = BackgroundSync(
        60, current or boards(), apply=applied.append,
        precache=cached.extend, fetch=fetch,
    )
    return syncer, applied, cached


def test_digest_stable_and_content_sensitive():
    assert boards_digest(boards()) == boards_digest(boards())
    assert boards_digest(boards()) != boards_digest(boards("Pear"))


def test_unchanged_content_is_not_applied(monkeypatch):
    syncer, applied, _ = make_syncer(monkeypatch, fetch=boards)
    assert syncer.tick() is False
    assert applied == []


def test_changed_content_is_precached_then_applied(monkeypatch):
    syncer, applied, cached = make_syncer(monkeypatch, fetch=lambda: boards("Pear"))
    assert syncer.tick() is True
    assert applied[0][0].cells[0].phrase == "Pear"
    assert "Pear" in cached
    assert syncer.tick() is False  # same content again - no second swap


def test_offline_keeps_boards_and_logs_once(monkeypatch, capsys):
    def offline():
        raise ConnectionError("no route")

    syncer, applied, _ = make_syncer(monkeypatch, fetch=offline)
    syncer.tick()
    syncer.tick()
    out = capsys.readouterr().out
    assert out.count("offline") == 1
    assert applied == []


def test_unclaimed_state(monkeypatch):
    def unclaimed():
        raise RuntimeError("Device not claimed yet - claim it from the dashboard")

    syncer, _, _ = make_syncer(monkeypatch, fetch=unclaimed)
    syncer.tick()
    assert syncer.state == "unclaimed"


def test_replace_boards_keeps_current_board_by_name():
    tts = FakeTTS()
    eng = Engine(boards(), tts)
    eng.board_idx = 1  # Feelings
    eng.dispatch(Action(SCAN_NEXT))
    eng.replace_boards([Board("New", [Cell("N", "N")]), Board("Feelings", [Cell("S", "Sad")])])
    assert eng.board.name == "Feelings"
    assert eng.scan_idx == -1
    eng.dispatch(Action(SCAN_NEXT))
    assert tts.spoken[-1] == "Sad"


def test_replace_boards_falls_back_to_first():
    eng = Engine(boards(), FakeTTS())
    eng.board_idx = 1
    eng.replace_boards([Board("Only", [Cell("O", "O")])])
    assert eng.board.name == "Only"


# ---- fixed button slots (Yes/No must never swap)

def rows(*phrases):
    cats = [{"id": "c1", "name": "Answers"}]
    return cats, [{"category_id": "c1", "input_type": t, "text": x} for t, x in phrases]


def test_slots_map_by_input_type():
    cats, phs = rows(("analog_left", "Apple"), ("button_o", "No"), ("button_x", "Yes"))
    cells = sync._adapt(cats, phs)[0].cells
    assert [c.phrase for c in cells] == ["Yes", "No", "Apple"]


def test_empty_red_slot_stays_empty_and_blue_stays_blue():
    cats, phs = rows(("button_o", "No"), ("analog_left", "Water"))
    board = sync._adapt(cats, phs)[0]
    assert board.cells[0].phrase == ""
    assert board.cells[1].phrase == "No"
    tts = FakeTTS()
    eng = Engine([board], tts)
    eng.dispatch(Action(SPEAK_CELL, target=0))   # red: silent, never "No"
    assert tts.spoken == []
    eng.dispatch(Action(SPEAK_CELL, target=1))
    assert tts.spoken == ["No"]


def test_empty_blue_slot_stays_empty():
    cats, phs = rows(("button_x", "Yes"), ("button_o", "  "), ("analog_left", "Juice"))
    cells = sync._adapt(cats, phs)[0].cells
    assert [c.phrase for c in cells] == ["Yes", "", "Juice"]


def test_scan_skips_empty_slots():
    cats, phs = rows(("button_o", "No"), ("analog_left", "Water"))
    tts = FakeTTS()
    eng = Engine(sync._adapt(cats, phs), tts)
    for _ in range(3):
        eng.dispatch(Action(SCAN_NEXT))
    assert tts.spoken == ["No", "Water", "No"]


def test_scan_prev_skips_empty_slots():
    from voicespeak.models import SCAN_PREV
    tts = FakeTTS()
    eng = Engine([Board("B", [Cell("r", ""), Cell("b", "No"), Cell("w", "Water")])], tts)
    for _ in range(3):
        eng.dispatch(Action(SCAN_PREV))
    assert tts.spoken == ["Water", "No", "Water"]


def test_board_with_only_empty_slots_is_dropped():
    cats = [{"id": "a", "name": "Empty"}, {"id": "b", "name": "Full"}]
    phs = [{"category_id": "b", "input_type": "button_x", "text": "Yes"}]
    assert [b.name for b in sync._adapt(cats, phs)] == ["Full"]
