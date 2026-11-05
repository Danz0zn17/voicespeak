"""Self-test speech, switches flag, bench Wi-Fi and unit templating - no
hardware, nmcli and systemctl mocked. Run: python3 -m pytest -q"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from voicespeak import config, setup_portal, updater
from voicespeak.bench import SwitchesSeen, describe_input, self_test_line


def input_map():
    return config.load_input_map()


# ---- self-test mode

def test_self_test_names_every_default_switch():
    m = input_map()
    assert describe_input("gpio:27", m["gpio:27"]) == "Red button"
    assert describe_input("gpio:17", m["gpio:17"]) == "More phrases"
    assert describe_input("gpio:22", m["gpio:22"]) == "Next board"
    assert describe_input("gpio:23", m["gpio:23"]) == "Repeat"
    assert describe_input("gpio:5", None) == "Switch on pin 5. Not used."


def test_self_test_names_controller_buttons():
    m = input_map()
    assert describe_input("hid:304", m["hid:304"]) == "Controller bottom button. Red button."
    assert describe_input("hid:305", m["hid:305"]) == "Controller right button. Blue button."
    assert describe_input("hid:307", m["hid:307"]) == "Controller top button. Next board."
    assert describe_input("hid:308", m["hid:308"]) == "Controller left button. Repeat."
    assert describe_input("hid:abs:1:hi", m["hid:abs:1:hi"]) == "Controller stick down. More phrases."
    assert describe_input("hid:999", None) == "Controller button 999. Not used."


def test_holds_keep_their_setup_action_in_self_test():
    m = input_map()
    assert self_test_line("gpio:22:hold", m["gpio:22:hold"]) is None
    assert self_test_line("hid:308:hold", m["hid:308:hold"]) is None
    assert self_test_line("gpio:27", m["gpio:27"]) == "Red button"


# ---- switches seen

def test_switches_seen_persists(tmp_path):
    flag = tmp_path / "data" / "switches_seen"
    s = SwitchesSeen(flag)
    assert not s.seen
    assert not s.note("hid:304")             # a controller is not a switch
    assert s.note("gpio:27") is True
    assert s.note("gpio:22") is False        # only the first time
    assert flag.exists()
    assert SwitchesSeen(flag).seen           # survives a restart


# ---- forget bench Wi-Fi

NM_ROWS = (
    "preconfigured:u-pre:802-11-wireless:no\n"
    "Smith Home:u-home:802-11-wireless:yes\n"
    "Workshop:u-shop:802-11-wireless:no\n"
    "VoiceSpeak-Setup:u-ap:802-11-wireless:no\n"
    "Wired connection 1:u-eth:802-3-ethernet:no\n"
)


def fake_nmcli(monkeypatch, rows, ssids=None):
    calls = []

    def run(*args, timeout=30):
        calls.append(args)
        out = ""
        if args[:4] == ("-t", "-f", "NAME,UUID,TYPE,ACTIVE", "connection"):
            out = rows
        elif args[:2] == ("-g", "802-11-wireless.ssid"):
            out = (ssids or {}).get(args[-1], "") + "\n"
        return subprocess.CompletedProcess(["nmcli", *args], 0, out, "")

    monkeypatch.setattr(setup_portal, "_nmcli", run)
    monkeypatch.setattr(setup_portal.sys, "platform", "linux")
    monkeypatch.setattr(setup_portal.shutil, "which", lambda name: "/usr/bin/nmcli")
    return calls


def deletes(calls):
    return [c[-1] for c in calls if c[:2] == ("connection", "delete")]


def test_forgets_imager_wifi_but_not_active_or_hotspot(monkeypatch):
    monkeypatch.delenv("BENCH_WIFI", raising=False)
    calls = fake_nmcli(monkeypatch, NM_ROWS)
    assert setup_portal.forget_bench_wifi() == ["preconfigured"]
    assert deletes(calls) == ["u-pre"]


def test_forgets_bench_wifi_by_name_or_ssid(monkeypatch):
    monkeypatch.setenv("BENCH_WIFI", "Levi Bench, Workshop")
    rows = NM_ROWS + "Bench 2:u-b2:802-11-wireless:no\n"
    calls = fake_nmcli(monkeypatch, rows, ssids={"u-b2": "Levi Bench"})
    assert sorted(setup_portal.forget_bench_wifi()) == ["Bench 2", "Workshop", "preconfigured"]
    assert "u-home" not in deletes(calls)


def test_never_deletes_the_active_connection(monkeypatch):
    monkeypatch.setenv("BENCH_WIFI", "Smith Home")
    rows = "preconfigured:u-pre:802-11-wireless:yes\nSmith Home:u-home:802-11-wireless:yes\n"
    calls = fake_nmcli(monkeypatch, rows)
    assert setup_portal.forget_bench_wifi() == []
    assert deletes(calls) == []


def test_keeps_bench_wifi_when_not_on_other_wifi(monkeypatch):
    # Online over Ethernet only: deleting the Wi-Fi could strand the box later.
    monkeypatch.delenv("BENCH_WIFI", raising=False)
    rows = "preconfigured:u-pre:802-11-wireless:no\nWired:u-eth:802-3-ethernet:yes\n"
    calls = fake_nmcli(monkeypatch, rows)
    assert setup_portal.forget_bench_wifi() == []
    assert deletes(calls) == []


def test_forget_is_noop_without_networkmanager(monkeypatch):
    monkeypatch.setattr(setup_portal.shutil, "which", lambda name: None)
    called = []
    monkeypatch.setattr(setup_portal, "_nmcli", lambda *a, **k: called.append(a))
    assert setup_portal.forget_bench_wifi() == []
    assert called == []


# ---- updater installs systemd units

def test_render_unit_matches_installer_substitution():
    text = ("User=pi\nWorkingDirectory=/home/pi/voicespeak-app\n"
            "Environment=VOICESPEAK_HOME=/home/pi/voicespeak\n"
            "Environment=XDG_RUNTIME_DIR=/run/user/1000\n")
    out = updater.render_unit(text, Path("/home/levi/voicespeak-app"),
                              Path("/home/levi/voicespeak"), "levi", 1001)
    assert out == ("User=levi\nWorkingDirectory=/home/levi/voicespeak-app\n"
                   "Environment=VOICESPEAK_HOME=/home/levi/voicespeak\n"
                   "Environment=XDG_RUNTIME_DIR=/run/user/1001\n")


def make_repo(tmp_path):
    app = tmp_path / "app"
    (app / "systemd").mkdir(parents=True)
    (app / "systemd" / "voicespeak.service").write_text(
        "[Service]\nUser=pi\nWorkingDirectory=/home/pi/voicespeak-app\n[Install]\nWantedBy=multi-user.target\n")
    (app / "systemd" / "voicespeak-update.timer").write_text("[Timer]\nOnCalendar=daily\n[Install]\nWantedBy=timers.target\n")
    units = tmp_path / "etc"
    units.mkdir()
    return app, units


def mock_systemctl(monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "_run", lambda cmd, cwd, timeout=300: calls.append(cmd)
                        or subprocess.CompletedProcess(cmd, 0, "", ""))
    monkeypatch.setattr(updater.os, "geteuid", lambda: 0)
    monkeypatch.setattr(updater, "_owner", lambda app: ("voicespeak", 1001, app.parent))
    monkeypatch.setenv("VOICESPEAK_HOME", "/home/voicespeak/voicespeak")
    return calls


def test_install_units_writes_changed_reloads_and_restarts(monkeypatch, tmp_path):
    app, units = make_repo(tmp_path)
    (units / "voicespeak-update.timer").write_text("[Timer]\nOnCalendar=weekly\n")
    calls = mock_systemctl(monkeypatch)
    changed = updater.install_units(app, units)
    assert changed == ["voicespeak-update.timer", "voicespeak.service"]
    assert f"WorkingDirectory={app}" in (units / "voicespeak.service").read_text()
    assert "User=voicespeak" in (units / "voicespeak.service").read_text()
    assert calls[0] == ["systemctl", "daemon-reload"]
    assert ["systemctl", "enable", "voicespeak.service"] in calls      # new unit
    assert ["systemctl", "restart", "voicespeak-update.timer"] in calls
    assert ["systemctl", "restart", "voicespeak.service"] not in calls  # run_update does that last


def test_install_units_unchanged_does_nothing(monkeypatch, tmp_path):
    app, units = make_repo(tmp_path)
    calls = mock_systemctl(monkeypatch)
    updater.install_units(app, units)
    calls.clear()
    assert updater.install_units(app, units) == []
    assert calls == []


def test_install_units_skipped_when_not_root(monkeypatch, tmp_path):
    app, units = make_repo(tmp_path)
    calls = mock_systemctl(monkeypatch)
    monkeypatch.setattr(updater.os, "geteuid", lambda: 1000)
    assert updater.install_units(app, units) == []
    assert calls == [] and not (units / "voicespeak.service").exists()


def test_run_update_installs_units_after_checkout(monkeypatch, tmp_path):
    app, units = make_repo(tmp_path)
    (app / "requirements.txt").write_text("requests\n")
    calls = mock_systemctl(monkeypatch)
    monkeypatch.setattr(updater, "_as_owner", lambda d: [])
    monkeypatch.setattr(updater, "UNIT_DIR", units)
    # Signature checks are covered in test_updater.py; here every tag passes.
    monkeypatch.setattr(updater, "verify_release", lambda git, d, tag, s: ("a" * 40, ""))

    def run(cmd, cwd, timeout=300):
        calls.append(cmd)
        out, rc = "", 0
        if cmd[-3:] == ["tag", "--list", "v*"]:
            out = "v0.3.0\nv0.3.1\n"
        elif "describe" in cmd:
            out = "v0.3.0\n"
        elif "merge-base" in cmd:
            rc = 1
        return subprocess.CompletedProcess(cmd, rc, out, "")

    monkeypatch.setattr(updater, "_run", run)
    assert updater.run_update(app) == 0
    i_checkout = next(i for i, c in enumerate(calls) if "checkout" in c)
    i_reload = calls.index(["systemctl", "daemon-reload"])
    i_restart = calls.index(["systemctl", "restart", "voicespeak.service"])
    assert i_checkout < i_reload < i_restart
    assert (units / "voicespeak.service").exists()
