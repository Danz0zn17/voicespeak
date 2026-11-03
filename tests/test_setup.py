"""Bluetooth parsing, setup-form parsing and page escaping - no hardware.
Run: python3 -m pytest -q
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from voicespeak.bt_pair import is_gamepad_name, parse_devices, pick_gamepad
from voicespeak.engine import Engine
from voicespeak.models import Action, BT_PAIR, Board, Cell
from voicespeak.config import update_env_text
from voicespeak.setup_portal import parse_setup_form, parse_wifi_list, render_page, split_terse

BTCTL = (
    "Device AA:BB:CC:DD:EE:01 JBL Flip 5\n"
    "\x1b[0;92m[NEW]\x1b[0m Device AA:BB:CC:DD:EE:02 AA-BB-CC-DD-EE-02\n"
    "[CHG] Device AA:BB:CC:DD:EE:02 Name: ignored\n"
    "Device AA:BB:CC:DD:EE:02 8BitDo Micro gamepad\n"
    "Device aa:bb:cc:dd:ee:03 Xbox Wireless Controller\n"
    "Discovery started\n"
)


def test_parse_devices_strips_colour_and_prefers_real_names():
    devices = dict(parse_devices(BTCTL))
    assert devices["AA:BB:CC:DD:EE:01"] == "JBL Flip 5"
    assert devices["AA:BB:CC:DD:EE:02"] == "8BitDo Micro gamepad"
    assert devices["AA:BB:CC:DD:EE:03"] == "Xbox Wireless Controller"
    assert len(devices) == 3


def test_gamepad_detection():
    assert is_gamepad_name("DualSense Wireless Controller")
    assert is_gamepad_name("Joy-Con (L)")
    assert not is_gamepad_name("JBL Flip 5")
    assert not is_gamepad_name("Danny's iPad")


def test_pick_gamepad_skips_already_paired():
    devices = parse_devices(BTCTL)
    assert pick_gamepad(devices)[0] == "AA:BB:CC:DD:EE:02"
    assert pick_gamepad(devices, skip={"AA:BB:CC:DD:EE:02"})[0] == "AA:BB:CC:DD:EE:03"
    assert pick_gamepad(devices[:1]) is None


def test_bt_pair_action_calls_hook():
    calls = []
    eng = Engine([Board("B", [Cell("a", "a")])], tts=None, on_pair=lambda: calls.append(1))
    eng.dispatch(Action(BT_PAIR))
    assert calls == [1]


def test_split_terse_escapes():
    assert split_terse(r"My\:Net:80:WPA2") == ["My:Net", "80", "WPA2"]
    assert split_terse(r"a\\b:1:") == ["a\\b", "1", ""]


def test_parse_wifi_list_dedupes_and_sorts():
    out = "Home:40:WPA2\nHome:75:WPA2\n:90:WPA2\nCafe:60:--\nVoiceSpeak-Setup:99:\n"
    nets = parse_wifi_list(out)
    assert [n["ssid"] for n in nets] == ["Home", "Cafe"]
    assert nets[0]["signal"] == 75 and nets[0]["secure"]
    assert not nets[1]["secure"]


def test_parse_setup_form_valid():
    form, err = parse_setup_form("ssid=Home&ssid_other=&password=secret123&pairing_code=tx+k4m2")
    assert err == ""
    assert form == {"ssid": "Home", "password": "secret123", "pairing_code": "TXK4M2"}


def test_parse_setup_form_other_ssid_wins_and_open_network():
    form, _ = parse_setup_form("ssid=Home&ssid_other=Hidden+Net&password=")
    assert form["ssid"] == "Hidden Net" and form["password"] == ""


def test_parse_setup_form_errors():
    assert parse_setup_form("ssid=&password=x")[0] is None
    assert parse_setup_form("ssid=Home&password=short")[0] is None
    assert parse_setup_form("ssid=Home&password=secret123&pairing_code=<x>")[0] is None
    assert parse_setup_form("ssid=" + "a" * 33)[0] is None


def test_render_page_escapes_ssids_and_errors():
    page = render_page([{"ssid": "<script>x</script>", "signal": 50, "secure": True}],
                       error='bad "pw" <b>')
    assert "<script>x</script>" not in page
    assert "&lt;script&gt;" in page
    assert "<b>" not in page.split("<form")[0].split("</style>")[1]


def test_update_env_text_replaces_and_appends():
    text = "SUPABASE_URL=old\n# DEVICE_TOKEN=commented\nVOICE_ENGINE=piper"
    out = update_env_text(text, {"SUPABASE_URL": "new", "DEVICE_TOKEN": "tok"})
    assert "SUPABASE_URL=new" in out
    assert "# DEVICE_TOKEN=commented" in out
    assert out.strip().endswith("DEVICE_TOKEN=tok")
    assert "VOICE_ENGINE=piper" in out
