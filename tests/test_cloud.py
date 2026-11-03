"""Zero-typing setup logic - no network, no hardware. Run: python3 -m pytest -q"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from voicespeak import bt_pair, cloud
from voicespeak.cloud import (
    CLAIMED, CONNECTED, GREETING, PENDING, UNCLAIMED,
    ClaimState, CloudError, DeviceLink, claim_prompt, code_prompt,
    parse_cpuinfo_serial, poll_interval, spell, status_payload,
)
from voicespeak.input.hid import is_gamepad
from voicespeak.updater import needs_update, pick_latest_tag


# ---- speech formatting

def test_spell_reads_each_character():
    assert spell("k7q2mx") == "K, 7, Q, 2, M, X"
    assert spell(" 4 7-21 ", sep=". ") == "4. 7. 2. 1"


def test_code_and_claim_prompts():
    assert code_prompt("K7Q2MX") == "This box's code is K, 7, Q, 2, M, X."
    assert claim_prompt("4721") == (
        "Someone wants to connect to this VoiceSpeak. Type this number in the app: 4. 7. 2. 1."
    )


# ---- claim state machine

def test_hello_unclaimed_greets_once():
    st = ClaimState(0)
    assert st.on_hello({"pairing_code": "ABC123", "claimed": False}, 0) == [GREETING]
    assert st.state == UNCLAIMED and st.pairing_code == "ABC123"
    assert st.on_sync({"claimed": False}, 10) == []  # not again


def test_hello_already_claimed_is_silent():
    st = ClaimState(0)
    assert st.on_hello({"pairing_code": "X", "claimed": True}, 0) == []
    assert st.state == CLAIMED


def test_pending_claim_speaks_code_then_repeats_every_20s_max_6():
    st = ClaimState(0)
    st.on_hello({"claimed": False}, 0)
    pending = {"claimed": False, "claim_pending": True, "claim_code": "4721"}
    said = st.on_sync(pending, 100)
    assert said == [claim_prompt("4721")] and st.state == PENDING
    assert st.on_sync(pending, 110) == []          # 10s later: too soon
    assert st.on_sync(pending, 120) == [claim_prompt("4721")]
    t, count = 120, 2
    while t < 1000:
        t += 20
        count += len(st.on_sync(pending, t))
    assert count == 6                               # capped


def test_new_claim_code_resets_prompt_count():
    st = ClaimState(0)
    st.on_hello({"claimed": False}, 0)
    for t in range(0, 400, 20):
        st.on_sync({"claim_pending": True, "claim_code": "1111"}, t)
    assert st.on_sync({"claim_pending": True, "claim_code": "1111"}, 500) == []
    assert st.on_sync({"claim_pending": True, "claim_code": "2222"}, 501) == [claim_prompt("2222")]


def test_claim_completes_with_connected():
    st = ClaimState(0)
    st.on_hello({"claimed": False}, 0)
    st.on_sync({"claim_pending": True, "claim_code": "4721"}, 5)
    assert st.on_sync({"claimed": True}, 15) == [CONNECTED]
    assert st.just_connected and st.state == CLAIMED and st.claim_code == ""
    assert st.on_sync({"claimed": True}, 75) == []  # only once


def test_cancelled_claim_goes_back_to_unclaimed_quietly():
    st = ClaimState(0)
    st.on_hello({"claimed": False}, 0)
    st.on_sync({"claim_pending": True, "claim_code": "4721"}, 5)
    assert st.on_sync({"claimed": False}, 15) == []
    assert st.state == UNCLAIMED and st.prompts == 0


def test_claim_without_code_is_not_treated_as_pending():
    st = ClaimState(0)
    st.on_hello({"claimed": False}, 0)
    assert st.on_sync({"claim_pending": True}, 5) == []
    assert st.state == UNCLAIMED


# ---- poll interval

def test_poll_interval_by_state():
    fast_until = 900
    assert poll_interval(UNCLAIMED, 100, fast_until, 60) == 10
    assert poll_interval(UNCLAIMED, 1000, fast_until, 60) == 60
    assert poll_interval(PENDING, 5000, fast_until, 60) == 10   # always fast while pending
    assert poll_interval(CLAIMED, 100, fast_until, 30) == 30
    assert poll_interval(CLAIMED, 100, fast_until, 0) == 60     # 0 never means "spin"


def test_pending_claim_extends_fast_window():
    st = ClaimState(0)
    st.on_hello({"claimed": False}, 0)
    st.on_sync({"claim_pending": True, "claim_code": "1"}, 2000)
    assert st.fast_until == 2000 + cloud.FAST_WINDOW


# ---- status + identity

def test_status_payload_shape():
    s = status_payload("0.3.0", "Raspberry Pi Zero 2 W", 1, ["8BitDo", "8BitDo"], 0)
    assert s == {"sw_version": "0.3.0", "model": "Raspberry Pi Zero 2 W", "gpio": True,
                 "controllers": ["8BitDo"], "bt_available": False}


def test_cpuinfo_serial():
    text = "processor\t: 0\nHardware\t: BCM2835\nSerial\t\t: 00000000abcd1234\nModel\t: Pi\n"
    assert parse_cpuinfo_serial(text) == "00000000abcd1234"
    assert parse_cpuinfo_serial("Serial\t: 0000000000000000\n") is None
    assert parse_cpuinfo_serial("processor: 0\n") is None


# ---- DeviceLink tick against a fake cloud

class FakeTTS:
    def __init__(self):
        self.said = []

    def speak_system(self, text):
        self.said.append(text)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.bodies = []

    def sync(self, token, status):
        self.bodies.append((token, status))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make_link(monkeypatch, responses):
    monkeypatch.setenv("DEVICE_TOKEN", "tok")
    written = {}
    monkeypatch.setattr(cloud.config, "write_env", lambda u: written.update(u))
    tts, offered, commands = FakeTTS(), [], []
    link = DeviceLink(
        tts, offer=offered.append, set_state=lambda s, e: None,
        status=lambda: {"gpio": True}, on_command=commands.append,
        adapt=lambda cats, phs: [("boards", len(cats))], client=FakeClient(responses),
        clock=lambda: 0.0,
    )
    link.claim.state = UNCLAIMED
    link.claim.greeted = True
    return link, tts, offered, commands, written


def test_link_speaks_claim_code_and_connects(monkeypatch):
    link, tts, offered, _, _ = make_link(monkeypatch, [
        {"claimed": False, "claim_pending": True, "claim_code": "4721"},
        {"claimed": True, "categories": [{"id": 1}], "phrases": []},
    ])
    link.tick()
    assert tts.said == [claim_prompt("4721")]
    link.tick()
    assert tts.said[-1] == CONNECTED
    assert offered == [[("boards", 1)]]   # phrases loaded straight away
    assert link.client.bodies[0] == ("tok", {"gpio": True})


def test_link_runs_commands_once(monkeypatch):
    import threading
    started = []
    monkeypatch.setattr(threading, "Thread", lambda target, args, **kw: started.append((target, args)) or type("T", (), {"start": lambda self: target(*args)})())
    link, _, _, commands, _ = make_link(monkeypatch, [
        {"claimed": True, "categories": [], "phrases": [], "command": "test_speak"},
        {"claimed": True, "categories": [], "phrases": [], "command": "rm -rf"},
    ])
    link.tick()
    link.tick()
    assert commands == ["test_speak"]     # unknown commands are ignored


def test_link_forgets_token_when_removed_in_app(monkeypatch):
    link, _, _, _, written = make_link(monkeypatch, [CloudError(401, "Unknown device token")])
    link.tick()
    assert written == {"DEVICE_TOKEN": ""}
    assert link.claim.state == cloud.UNREGISTERED


def test_link_offline_keeps_state(monkeypatch):
    link, tts, offered, _, written = make_link(monkeypatch, [ConnectionError("no route")])
    link.tick()
    assert tts.said == [] and offered == [] and written == {}


def test_speak_code_with_and_without_code(monkeypatch):
    link, tts, _, _, _ = make_link(monkeypatch, [])
    link.speak_code()
    assert "do not have a code" in tts.said[-1]
    link.claim.pairing_code = "AB12CD"
    link.speak_code()
    assert tts.said[-1] == "This box's code is A, B, 1, 2, C, D."


# ---- updates

def test_pick_latest_tag_numeric_order():
    assert pick_latest_tag(["v0.9.0", "v0.10.0", "v0.3.1", "latest", "v1.0", "x1.0.0"]) == "v0.10.0"
    assert pick_latest_tag(["main", "foo"]) is None


def test_needs_update_rules():
    assert needs_update("v0.4.0", "v0.3.0", contains_latest=False)
    assert not needs_update("v0.4.0", "v0.4.0", contains_latest=True)
    assert not needs_update(None, "v0.3.0", contains_latest=False)
    # Fresh install from main that already includes the newest tag: no downgrade.
    assert not needs_update("v0.3.0", None, contains_latest=True)
    assert needs_update("v0.3.0", None, contains_latest=False)


# ---- controllers

def test_is_gamepad_by_buttons_or_name():
    assert is_gamepad("Pro Controller", [304, 305])
    assert is_gamepad("Generic USB Joystick", [288])
    assert is_gamepad("8BitDo Zero 2", [1, 2, 3])        # name match with keys
    assert not is_gamepad("Logitech USB Keyboard", [1, 2, 30, 31])
    assert not is_gamepad("pwr_button", [116])
    assert not is_gamepad("Xbox Wireless Controller", [])  # no keys at all


def test_auto_pair_only_without_controller():
    assert bt_pair.should_auto_pair(True, [])
    assert not bt_pair.should_auto_pair(True, ["8BitDo"])
    assert not bt_pair.should_auto_pair(False, [])


def test_auto_pair_prompts_only_without_switches(monkeypatch):
    monkeypatch.setattr(bt_pair, "bt_available", lambda: True)
    monkeypatch.setattr(bt_pair, "pair_controller", lambda s, stop_when: (True, "Connected X"))
    tts = FakeTTS()
    assert bt_pair.auto_pair_window(tts, has_gpio=True, controllers=lambda: [])
    assert tts.said == ["Controller connected."]
    tts = FakeTTS()
    bt_pair.auto_pair_window(tts, has_gpio=False, controllers=lambda: [])
    assert tts.said == ["Turn on your controller in pairing mode.", "Controller connected."]


def test_auto_pair_skips_when_connected(monkeypatch):
    monkeypatch.setattr(bt_pair, "bt_available", lambda: True)
    called = []
    monkeypatch.setattr(bt_pair, "pair_controller", lambda *a, **k: called.append(1))
    assert not bt_pair.auto_pair_window(FakeTTS(), True, controllers=lambda: ["Pad"])
    assert called == []
