"""First-boot Wi-Fi setup: a phone-friendly hotspot page, no keyboard or SSH.

Run by voicespeak-setup.service as root on boot (`python3 -m voicespeak setup`).
If the device is online within WAIT_SECONDS it exits and does nothing. If not,
it scans nearby networks, starts the "VoiceSpeak-Setup-C3D4" hotspot (the last
4 characters of the box's serial) via NetworkManager (Raspberry Pi OS
Bookworm), and serves a page at 10.42.0.1 where a parent picks their Wi-Fi and
types the password. Wrong password -> spoken message, hotspot comes back. A
pairing code is still accepted if an old page posts one.

Also: forget_bench_wifi() drops the workshop Wi-Fi once a family owns the box.

Stdlib only. Parsing, validation and page rendering are pure (tested).
"""

from __future__ import annotations

import html
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import requests

from . import config
from .config import write_env

HOTSPOT_NAME = "VoiceSpeak-Setup"  # NetworkManager connection name (fixed)
HOTSPOT_PREFIX = "VoiceSpeak-Setup-"
# Raspberry Pi Imager's customisation saves its Wi-Fi under this name.
IMAGER_CONNECTION = "preconfigured"
WAIT_SECONDS = 45
CONNECT_SECONDS = 30
# With no form submitted, drop the hotspot this often and let NetworkManager
# retry known networks (covers "router was just slow to boot").
RETRY_MINUTES = 15
DEFAULT_CLOUD_URL = config.DEFAULT_CLOUD_URL
# Make every DNS lookup on the hotspot resolve to us, so phones pop the page up.
DNSMASQ_CONF = Path("/etc/NetworkManager/dnsmasq-shared.d/voicespeak-setup.conf")


# ---- pure helpers -----------------------------------------------------------

def hotspot_ssid(hw_id: str | None = None) -> str:
    """"VoiceSpeak-Setup-" + serial4, so boxes on one bench can be told apart."""
    from .cloud import hardware_id, serial4
    try:
        suffix = serial4(hw_id if hw_id is not None else hardware_id())
    except Exception:  # noqa: BLE001 - never block setup on the id
        suffix = ""
    return HOTSPOT_PREFIX + suffix if suffix else HOTSPOT_NAME


def is_own_hotspot(ssid: str) -> bool:
    return ssid == HOTSPOT_NAME or ssid.startswith(HOTSPOT_PREFIX)


def spoken_ssid(ssid: str) -> str:
    """"VoiceSpeak-Setup-C3D4" -> "VoiceSpeak Setup C, 3, D, 4" for the voice."""
    if ssid.startswith(HOTSPOT_PREFIX):
        return "VoiceSpeak Setup " + ", ".join(ssid[len(HOTSPOT_PREFIX):])
    return ssid.replace("-", " ")

def split_terse(line: str) -> list[str]:
    """Split one `nmcli -t` line on ':' honouring '\\:' and '\\\\' escapes."""
    fields, cur, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if ch == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    fields.append("".join(cur))
    return fields


def parse_wifi_list(output: str) -> list[dict]:
    """`nmcli -t -f SSID,SIGNAL,SECURITY dev wifi list` -> strongest-first,
    one entry per SSID, hidden networks and our own hotspot dropped."""
    best: dict[str, dict] = {}
    for line in output.splitlines():
        parts = split_terse(line)
        if len(parts) < 3:
            continue
        ssid, signal, security = parts[0], parts[1], parts[2]
        if not ssid or is_own_hotspot(ssid):
            continue
        try:
            strength = int(signal)
        except ValueError:
            strength = 0
        entry = {"ssid": ssid, "signal": strength,
                 "secure": security not in ("", "--")}
        if ssid not in best or strength > best[ssid]["signal"]:
            best[ssid] = entry
    return sorted(best.values(), key=lambda n: -n["signal"])


def parse_setup_form(body: str) -> tuple[dict | None, str]:
    """POST body -> ({ssid, password, pairing_code}, "") or (None, error)."""
    form = parse_qs(body, keep_blank_values=True)

    def field(name: str) -> str:
        return form.get(name, [""])[0]

    ssid = field("ssid_other").strip() or field("ssid").strip()
    password = field("password")
    code = "".join(field("pairing_code").split()).upper()

    if not ssid:
        return None, "Choose your Wi-Fi network."
    if len(ssid.encode()) > 32:
        return None, "That network name is too long."
    if password and not 8 <= len(password) <= 63:
        return None, "Wi-Fi passwords are 8 to 63 characters."
    if code and (not code.isalnum() or len(code) > 12):
        return None, "The pairing code is letters and numbers only."
    return {"ssid": ssid, "password": password, "pairing_code": code}, ""


PAGE_CSS = """
body{margin:0;font-family:system-ui,sans-serif;background:#0b1020;color:#f1f5f9}
main{max-width:420px;margin:0 auto;padding:28px 20px 48px}
h1{font-size:26px;margin:0 0 6px}p{color:#94a3b8;line-height:1.5}
label{display:block;font-weight:600;margin:20px 0 8px}
select,input{width:100%;box-sizing:border-box;font-size:18px;padding:14px;
border-radius:12px;border:1px solid #334155;background:#111827;color:#f1f5f9}
button{width:100%;margin-top:28px;font-size:20px;font-weight:700;padding:16px;
border:0;border-radius:14px;background:#38bdf8;color:#0b1020}
.err{background:#7f1d1d;color:#fecaca;padding:12px 14px;border-radius:12px}
.hint{font-size:14px;margin-top:6px}
"""


def render_page(networks: list[dict], error: str = "") -> str:
    esc = html.escape
    options = "".join(
        f'<option value="{esc(n["ssid"])}">{esc(n["ssid"])}'
        f'{"" if n["secure"] else " (open)"}</option>'
        for n in networks
    )
    err = f'<p class="err">{esc(error)}</p>' if error else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VoiceSpeak setup</title><style>{PAGE_CSS}</style></head><body><main>
<h1>Set up VoiceSpeak</h1>
<p>Connect the device to your home Wi-Fi. It will say "Connected" when done.</p>
{err}
<form method="post" action="/connect">
<label for="ssid">Wi-Fi network</label>
<select id="ssid" name="ssid">{options}</select>
<label for="ssid_other">Not listed? Type its name</label>
<input id="ssid_other" name="ssid_other" autocomplete="off" autocapitalize="none">
<label for="password">Wi-Fi password</label>
<input id="password" name="password" type="password" autocomplete="off">
<p class="hint">Once it is online, open the VoiceSpeak app on this Wi-Fi to connect it.</p>
<button type="submit">Connect</button>
</form></main></body></html>"""


def render_done(ssid: str = HOTSPOT_NAME) -> str:
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VoiceSpeak setup</title><style>""" + PAGE_CSS + """</style></head>
<body><main><h1>Connecting...</h1>
<p>You can close this page and rejoin your home Wi-Fi. The device will say
"Connected" in about 30 seconds.</p>
<p>If it says the password was wrong, join <b>""" + html.escape(ssid) + """</b> again
and retry.</p></main></body></html>"""


DONE_PAGE = render_done()


# ---- NetworkManager ---------------------------------------------------------

def _nmcli(*args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["nmcli", *args], capture_output=True, text=True, timeout=timeout,
    )


def is_online() -> bool:
    try:
        state = _nmcli("networking", "connectivity", "check").stdout.strip()
    except Exception:  # noqa: BLE001
        return False
    return state in ("full", "limited")


def wait_online(seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if is_online():
            return True
        time.sleep(3)
    return is_online()


def scan_networks() -> list[dict]:
    out = _nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list",
                 "--rescan", "yes").stdout
    return parse_wifi_list(out)


def start_hotspot(ssid: str = HOTSPOT_NAME) -> None:
    try:
        DNSMASQ_CONF.parent.mkdir(parents=True, exist_ok=True)
        DNSMASQ_CONF.write_text("address=/#/10.42.0.1\n")
    except OSError as e:
        print(f"Captive DNS not set ({e}); open http://10.42.0.1 by hand.")
    _nmcli("connection", "delete", HOTSPOT_NAME)
    args = ["connection", "add", "type", "wifi", "ifname", "wlan0",
            "con-name", HOTSPOT_NAME, "autoconnect", "no", "ssid", ssid,
            "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
            "ipv4.method", "shared"]
    password = os.environ.get("SETUP_HOTSPOT_PASSWORD", "")
    if len(password) >= 8:
        args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
    _nmcli(*args)
    result = _nmcli("connection", "up", HOTSPOT_NAME)
    if result.returncode != 0:
        raise RuntimeError(f"Hotspot failed: {result.stderr.strip()}")
    print(f"Hotspot '{ssid}' up at http://10.42.0.1")


def stop_hotspot() -> None:
    _nmcli("connection", "down", HOTSPOT_NAME)
    _nmcli("connection", "delete", HOTSPOT_NAME)
    DNSMASQ_CONF.unlink(missing_ok=True)


def connect_wifi(ssid: str, password: str) -> bool:
    _nmcli("dev", "wifi", "rescan", timeout=15)
    time.sleep(3)
    args = ["dev", "wifi", "connect", ssid, "ifname", "wlan0"]
    if password:
        args += ["password", password]
    result = _nmcli(*args, timeout=60)
    if result.returncode == 0 and wait_online(CONNECT_SECONDS):
        return True
    # Drop the failed profile so a wrong password is not retried forever.
    _nmcli("connection", "delete", ssid)
    print(f"Wi-Fi connect failed: {result.stderr.strip() or 'no internet'}")
    return False


# ---- forget bench Wi-Fi -------------------------------------------------------

def bench_names(env: str | None = None) -> set[str]:
    """Connections to forget once a family owns the box: Imager's
    "preconfigured" plus any names/SSIDs in BENCH_WIFI (comma separated)."""
    raw = os.environ.get("BENCH_WIFI", "") if env is None else env
    return {IMAGER_CONNECTION} | {n.strip() for n in raw.split(",") if n.strip()}


def parse_connections(output: str) -> list[dict]:
    """`nmcli -t -f NAME,UUID,TYPE,ACTIVE connection show` -> dicts."""
    rows = []
    for line in output.splitlines():
        parts = split_terse(line)
        if len(parts) < 4:
            continue
        rows.append({"name": parts[0], "uuid": parts[1], "type": parts[2],
                     "active": parts[3].strip().lower() == "yes"})
    return rows


def pick_bench_connections(rows: list[dict], names: set[str],
                           ssids: dict[str, str]) -> list[dict]:
    """Which saved Wi-Fi connections to delete. Never the active one, and only
    when the box is on another Wi-Fi right now (so it cannot strand itself)."""
    wifi = [r for r in rows if r["type"] in ("802-11-wireless", "wifi")
            and r["name"] != HOTSPOT_NAME]
    matches = [r for r in wifi if not r["active"]
               and (r["name"] in names or ssids.get(r["uuid"], "") in names)]
    keep = {r["uuid"] for r in matches}
    if not any(r["active"] and r["uuid"] not in keep for r in wifi):
        return []
    return matches


def forget_bench_wifi() -> list[str]:
    """Delete bench Wi-Fi profiles once the box is claimed and online.
    Returns the names deleted. A no-op on machines without NetworkManager."""
    if not sys.platform.startswith("linux") or shutil.which("nmcli") is None:
        return []
    try:
        listing = _nmcli("-t", "-f", "NAME,UUID,TYPE,ACTIVE", "connection", "show")
        if listing.returncode != 0:
            return []
        rows = parse_connections(listing.stdout)
        names = bench_names()
        ssids: dict[str, str] = {}
        if names - {IMAGER_CONNECTION}:
            for r in rows:
                if r["type"] in ("802-11-wireless", "wifi") and not r["active"]:
                    out = _nmcli("-g", "802-11-wireless.ssid", "connection", "show", r["uuid"])
                    ssids[r["uuid"]] = out.stdout.strip()
        deleted = []
        for r in pick_bench_connections(rows, names, ssids):
            if _nmcli("connection", "delete", "uuid", r["uuid"]).returncode == 0:
                deleted.append(r["name"])
            else:
                print(f"Could not forget bench Wi-Fi '{r['name']}'.")
        if deleted:
            print(f"Forgot bench Wi-Fi: {', '.join(deleted)}")
        return deleted
    except (OSError, subprocess.SubprocessError) as e:
        print(f"Bench Wi-Fi check skipped ({e}).")
        return []


# ---- pairing + .env ---------------------------------------------------------

def pair_device(code: str) -> str:
    """Exchange a pairing code for a device token (same call as the installer)."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/") or DEFAULT_CLOUD_URL
    r = requests.post(f"{url}/functions/v1/pair-device",
                      json={"pairing_code": code}, timeout=15)
    data = r.json() if r.content else {}
    token = data.get("device_token", "")
    if not token:
        raise RuntimeError(data.get("error") or f"HTTP {r.status_code}")
    write_env({"SUPABASE_URL": url, "DEVICE_TOKEN": token})
    return token


# ---- portal -----------------------------------------------------------------

class Portal:
    def __init__(self, tts):
        self.tts = tts
        self.networks: list[dict] = []
        self.error = ""
        self.done = threading.Event()
        self.submitted = threading.Event()
        self.server: HTTPServer | None = None
        self.ssid = HOTSPOT_NAME

    def say(self, text: str) -> None:
        try:
            self.tts.speak_system(text)
        except Exception as e:  # noqa: BLE001 - no speaker must not stop setup
            print(f"(could not speak '{text}': {e})")

    def handler(self):
        portal = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, body: str, status: int = 200) -> None:
                data = body.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802 - any path shows the setup page
                self._send(render_page(portal.networks, portal.error))

            def do_POST(self):  # noqa: N802
                length = min(int(self.headers.get("Content-Length") or 0), 4096)
                body = self.rfile.read(length).decode("utf-8", "replace")
                form, error = parse_setup_form(body)
                if form is None or portal.submitted.is_set():
                    self._send(render_page(portal.networks, error or "Already connecting."))
                    return
                portal.submitted.set()
                self._send(render_done(portal.ssid))
                threading.Thread(target=portal.apply, args=(form,), daemon=True).start()

            def log_message(self, *args):  # keep the journal quiet
                pass

        return Handler

    def apply(self, form: dict) -> None:
        time.sleep(1)  # let the "Connecting" page reach the phone first
        stop_hotspot()
        if not connect_wifi(form["ssid"], form["password"]):
            self.error = f"Could not join {form['ssid']}. Check the password and try again."
            self.say("Could not connect. Check the Wi-Fi password.")
            start_hotspot(self.ssid)
            self.submitted.clear()
            return
        message = "Connected."
        if form["pairing_code"]:
            try:
                pair_device(form["pairing_code"])
                print("Device paired.")
            except Exception as e:  # noqa: BLE001 - Wi-Fi still worked
                print(f"Pairing failed: {e}")
                message = "Connected, but the pairing code did not work."
        self.say(message)
        subprocess.run(["systemctl", "restart", "voicespeak.service"], check=False)
        self.done.set()

    def serve(self) -> None:
        port = int(os.environ.get("SETUP_PORT", "80"))
        self.server = HTTPServer(("0.0.0.0", port), self.handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def run_setup(tts) -> int:
    print(f"Waiting up to {WAIT_SECONDS}s for a network...")
    if wait_online(WAIT_SECONDS):
        print("Online - Wi-Fi setup not needed.")
        return 0
    portal = Portal(tts)
    portal.ssid = hotspot_ssid()
    portal.serve()
    while not portal.done.is_set():
        portal.networks = scan_networks()
        start_hotspot(portal.ssid)
        portal.say(f"Wi-Fi setup. On your phone, join {spoken_ssid(portal.ssid)}.")
        deadline = time.time() + RETRY_MINUTES * 60
        while time.time() < deadline and not portal.done.is_set():
            if portal.done.wait(5):
                break
            if portal.submitted.is_set():
                deadline = time.time() + RETRY_MINUTES * 60
        if portal.done.is_set():
            break
        # Nobody configured it: drop the hotspot and see if a known network is back.
        stop_hotspot()
        if wait_online(WAIT_SECONDS):
            print("Known network came back - leaving setup.")
            break
    if portal.server:
        portal.server.shutdown()
    return 0
