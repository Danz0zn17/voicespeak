"""Zero-typing setup: the box registers itself and waits to be claimed.

Flow:
  1. No DEVICE_TOKEN: POST device-hello with this board's hardware id and a
     secret generated once on the device. The cloud answers with a token and
     the box's pairing code. The box keeps working from its bundled boards.
  2. Unclaimed: poll device-sync (fast for 15 minutes after boot or after a
     claim). A parent on the same network sees the box in the app and taps
     Connect.
  3. Claim pending: the box speaks a 4-digit claim code. Only someone in the
     room hears it; they type it into the app to finish.
  4. Claimed: the usual sync every SYNC_INTERVAL_SECONDS, with a status
     heartbeat and one-shot commands from the app.

ClaimState is pure (tested): it turns cloud responses into spoken prompts.
DeviceLink owns the thread and the network.
"""

from __future__ import annotations

import os
import platform
import secrets
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import requests

from . import config

UNREGISTERED = "unregistered"
UNCLAIMED = "unclaimed"
PENDING = "pending"
CLAIMED = "claimed"

FAST_POLL = 10.0
SLOW_POLL = 60.0
FAST_WINDOW = 15 * 60.0
PROMPT_EVERY = 20.0
PROMPT_MAX = 6
HELLO_BACKOFF_MAX = 300.0
FOREIGN_RETRY = 1800.0

GREETING = "Hello. To connect me, open the VoiceSpeak app on a phone or computer on this Wi-Fi."
FOREIGN = "This box belongs to another account. Remove it in the app, then restart me."
CONNECTED = "Connected."
RATE_LIMITED = "Too many new boxes on this network. I will keep trying."
RATE_LIMIT_DEFAULT = 600.0
COMMANDS = {"pair_controller", "test_speak", "speak_code"}


# ---- pure helpers -----------------------------------------------------------

def spell(code: str, sep: str = ", ") -> str:
    """'K7Q2MX' -> 'K, 7, Q, 2, M, X' so the voice reads it one by one."""
    return sep.join(ch for ch in code.strip().upper() if ch.isalnum())


def code_prompt(pairing_code: str) -> str:
    return f"This box's code is {spell(pairing_code)}."


def claim_prompt(claim_code: str) -> str:
    digits = spell(claim_code, sep=". ")
    return f"Someone wants to connect to this VoiceSpeak. Type this number in the app: {digits}."


def poll_interval(state: str, now: float, fast_until: float, claimed_every: float) -> float:
    """Seconds until the next sync for this state."""
    if state in (UNCLAIMED, PENDING):
        return FAST_POLL if now < fast_until or state == PENDING else SLOW_POLL
    return claimed_every if claimed_every > 0 else SLOW_POLL


def status_payload(sw_version: str, model: str, gpio: bool,
                   controllers: list[str], bt_available: bool,
                   switches_seen: bool = False) -> dict:
    """`gpio` = GPIO input is available (kept for older apps); `switches_seen`
    = a switch has actually been pressed on this box."""
    return {
        "sw_version": sw_version, "model": model, "gpio": bool(gpio),
        "switches_seen": bool(switches_seen),
        "controllers": sorted(set(controllers)), "bt_available": bool(bt_available),
    }


def retry_after(data: dict, default: float = RATE_LIMIT_DEFAULT) -> float:
    """Seconds the cloud asked us to wait (retry_after_s), clamped to 10s..1h."""
    try:
        value = float(data.get("retry_after_s"))
    except (TypeError, ValueError):
        return default
    return min(max(value, 10.0), 3600.0)


def serial4(hw_id: str) -> str:
    """Last 4 letters/digits of the hardware id, uppercased ("...a1b2c3d4" -> "C3D4").
    Matches the box name ("VoiceSpeak C3D4") and the setup hotspot."""
    return "".join(ch for ch in hw_id if ch.isalnum())[-4:].upper()


def parse_cpuinfo_serial(text: str) -> str | None:
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "serial":
            value = value.strip().lower()
            if value and set(value) != {"0"}:
                return value
    return None


class ClaimState:
    """Cloud responses in, spoken prompts out. No I/O."""

    def __init__(self, now: float = 0.0):
        self.state = UNREGISTERED
        self.pairing_code = ""
        self.claim_code = ""
        self.prompts = 0
        self.last_prompt = 0.0
        self.greeted = False
        self.just_connected = False
        self.fast_until = now + FAST_WINDOW

    def on_hello(self, resp: dict, now: float) -> list[str]:
        self.pairing_code = str(resp.get("pairing_code") or self.pairing_code)
        if resp.get("claimed"):
            self.state = CLAIMED
            return []
        self.state = UNCLAIMED
        return self._greet()

    def on_sync(self, resp: dict, now: float) -> list[str]:
        """Returns what to say. Sets self.just_connected when a claim completed."""
        self.just_connected = False
        if resp.get("pairing_code"):
            self.pairing_code = str(resp["pairing_code"])
        before = self.state
        if resp.get("claimed"):
            self.state = CLAIMED
            self.claim_code = ""
            if before in (UNCLAIMED, PENDING):
                self.just_connected = True
                return [CONNECTED]
            return []
        if resp.get("claim_pending") and resp.get("claim_code"):
            code = str(resp["claim_code"])
            if code != self.claim_code:  # a new claim: start the prompts over
                self.claim_code = code
                self.prompts = 0
            self.state = PENDING
            self.fast_until = now + FAST_WINDOW
            return self.due_prompt(now)
        self.state = UNCLAIMED
        self.claim_code = ""
        self.prompts = 0
        return self._greet()

    def due_prompt(self, now: float) -> list[str]:
        if self.state != PENDING or self.prompts >= PROMPT_MAX:
            return []
        if self.prompts and now - self.last_prompt < PROMPT_EVERY:
            return []
        self.prompts += 1
        self.last_prompt = now
        return [claim_prompt(self.claim_code)]

    def _greet(self) -> list[str]:
        if self.greeted:
            return []
        self.greeted = True
        return [GREETING]


# ---- device identity --------------------------------------------------------

def hardware_id() -> str:
    """Pi serial, else machine-id, else a random id kept in .env (dev machines)."""
    try:
        serial = parse_cpuinfo_serial(Path("/proc/cpuinfo").read_text())
        if serial:
            return serial
    except OSError:
        pass
    try:
        mid = Path("/etc/machine-id").read_text().strip()
        if mid:
            return mid
    except OSError:
        pass
    hid = os.environ.get("HARDWARE_ID", "")
    if not hid:
        hid = uuid.uuid4().hex
        config.write_env({"HARDWARE_ID": hid})
    return hid


def device_model() -> str:
    try:
        return Path("/proc/device-tree/model").read_text().strip("\x00 \n")
    except OSError:
        return f"{platform.system()} {platform.machine()}".strip()


def sw_version() -> str:
    try:
        v = config.VERSION_FILE.read_text().strip()
        if v:
            return v
    except OSError:
        pass
    try:
        out = subprocess.run(
            ["git", "-C", str(config.PACKAGE_DIR), "describe", "--tags", "--always"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or "0.0.0"
    except (OSError, subprocess.SubprocessError):
        return "0.0.0"


def device_secret() -> str:
    """Generated once on the device and never shown anywhere."""
    secret = os.environ.get("DEVICE_SECRET", "")
    if not secret:
        secret = secrets.token_hex(32)
        config.write_env({"DEVICE_SECRET": secret})
    return secret


# ---- network ----------------------------------------------------------------

class CloudError(Exception):
    def __init__(self, status: int, message: str, data: dict | None = None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.data = data or {}


class CloudClient:
    def __init__(self, base_url: str | None = None, timeout: float = 15):
        self.base = (base_url or config.cloud_url()).rstrip("/") + "/functions/v1"
        self.timeout = timeout

    def _post(self, fn: str, body: dict) -> dict:
        r = requests.post(f"{self.base}/{fn}", json=body, timeout=self.timeout)
        try:
            data = r.json() if r.content else {}
        except ValueError:
            data = {}
        if r.status_code >= 400:
            raise CloudError(r.status_code, str(data.get("error") or r.reason),
                             data if isinstance(data, dict) else {})
        return data

    def hello(self, hw_id: str, secret: str, model: str, version: str) -> dict:
        return self._post("device-hello", {
            "hardware_id": hw_id, "device_secret": secret,
            "model": model, "sw_version": version,
        })

    def sync(self, token: str, status: dict) -> dict:
        return self._post("device-sync", {"device_token": token, "status": status})


# ---- the background link ----------------------------------------------------

class DeviceLink:
    """Registers, waits for a claim, then keeps phrases and status in sync.

    `offer(boards)` swaps boards only when they changed (BackgroundSync.offer).
    `on_command(name)` runs app commands; it is called on its own thread.
    `on_claimed()` runs once per session, on its own thread, after the first
    sync that finds the box claimed and online (e.g. forget bench Wi-Fi).
    """

    def __init__(self, tts, offer: Callable, set_state: Callable[[str, Exception | None], None],
                 status: Callable[[], dict], on_command: Callable[[str], None],
                 adapt: Callable[[list, list], list], client: CloudClient | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 on_claimed: Callable[[], None] | None = None):
        self.tts = tts
        self.offer = offer
        self.set_state = set_state
        self.status = status
        self.on_command = on_command
        self.adapt = adapt
        self.client = client or CloudClient()
        self.clock = clock
        self.claim = ClaimState(clock())
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._backoff = 5.0
        self.on_claimed = on_claimed
        self._claimed_ran = False
        self._rate_warned = False

    # -- public
    @property
    def self_test(self) -> bool:
        """True while the box is known not to belong to a family: no token yet
        (or removed in the app), or the cloud says it is waiting to be claimed.
        A claimed box that is offline at boot is never in self-test."""
        return not self._token() or self.claim.state in (UNCLAIMED, PENDING)

    def start(self) -> None:
        threading.Thread(target=self._run, name="cloud", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def sync_now(self) -> None:
        self._wake.set()

    def speak_code(self) -> None:
        if self.claim.pairing_code:
            self.tts.speak_system(code_prompt(self.claim.pairing_code))
        else:
            self.tts.speak_system("I do not have a code yet. Connect me to the internet first.")

    # -- loop
    def _say(self, lines: list[str]) -> None:
        for line in lines:
            self.tts.speak_system(line)

    def _token(self) -> str:
        return os.environ.get("DEVICE_TOKEN", "").strip()

    def _hello(self) -> float:
        """Returns seconds to wait before the next attempt (0 = go sync now)."""
        try:
            resp = self.client.hello(hardware_id(), device_secret(), device_model(), sw_version())
        except CloudError as e:
            if e.status == 409:
                print(f"Hello refused: {e}")
                self.set_state("foreign", e)
                if self.claim.state != "foreign":
                    self.claim.state = "foreign"
                    self._say([FOREIGN])
                return FOREIGN_RETRY
            if e.status == 429:
                print(f"Hello rate limited: {e}")
                self.set_state("rate_limited", e)
                if not self._rate_warned:
                    self._rate_warned = True
                    self._say([RATE_LIMITED])
                return retry_after(e.data)
            self.set_state("offline", e)
            return self._next_backoff()
        except Exception as e:  # noqa: BLE001 - offline is expected
            self.set_state("offline", e)
            return self._next_backoff()
        token = str(resp.get("device_token") or "")
        if not token:
            self.set_state("offline", RuntimeError("hello returned no token"))
            return self._next_backoff()
        updates = {"DEVICE_TOKEN": token}
        if resp.get("pairing_code"):
            updates["PAIRING_CODE"] = str(resp["pairing_code"])
        config.write_env(updates)
        self._backoff = 5.0
        self._rate_warned = False
        print(f"Registered with the cloud (code {resp.get('pairing_code', '?')}).")
        self._say(self.claim.on_hello(resp, self.clock()))
        return 0.0

    def _next_backoff(self) -> float:
        wait = self._backoff
        self._backoff = min(self._backoff * 2, HELLO_BACKOFF_MAX)
        return wait

    def tick(self) -> None:
        """One sync round trip. Safe to call directly in tests."""
        token = self._token()
        try:
            resp = self.client.sync(token, self.status())
        except CloudError as e:
            if e.status == 401:
                # The box was removed in the app: forget the token, register again.
                print("Device token no longer valid; registering again.")
                config.write_env({"DEVICE_TOKEN": ""})
                self.claim.state = UNREGISTERED
            self.set_state("offline", e)
            return
        except Exception as e:  # noqa: BLE001 - offline is expected
            self.set_state("offline", e)
            return
        self.set_state("online" if resp.get("claimed") else "unclaimed", None)
        self._say(self.claim.on_sync(resp, self.clock()))
        if resp.get("claimed"):
            try:
                self.offer(self.adapt(resp.get("categories") or [], resp.get("phrases") or []))
            except Exception as e:  # noqa: BLE001 - keep current boards
                print(f"Cloud boards not usable ({e}); keeping current phrases.")
            if self.on_claimed and not self._claimed_ran:
                self._claimed_ran = True
                threading.Thread(target=self.on_claimed, name="claimed", daemon=True).start()
        cmd = resp.get("command")
        if cmd in COMMANDS:
            threading.Thread(target=self.on_command, args=(cmd,), name="command", daemon=True).start()

    def _run(self) -> None:
        if os.environ.get("PAIRING_CODE"):
            self.claim.pairing_code = os.environ["PAIRING_CODE"]
        while not self._stop.is_set():
            try:
                if not self._token():
                    wait = self._hello()
                else:
                    self.tick()
                    now = self.clock()
                    # A pending claim re-prompts between polls.
                    self._say(self.claim.due_prompt(now))
                    wait = poll_interval(self.claim.state, now, self.claim.fast_until,
                                         config.sync_interval())
            except Exception as e:  # noqa: BLE001 - the thread must never die
                print(f"Cloud link error: {e}")
                wait = SLOW_POLL
            if wait:
                self._wake.wait(wait)
                self._wake.clear()
