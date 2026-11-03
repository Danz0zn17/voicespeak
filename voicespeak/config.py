"""Environment, paths and the input-map default/override.

Reads a simple KEY=VALUE .env next to the install (no extra dependency).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Action

# VOICESPEAK_HOME lets root-run services (setup portal) use the device user's dir.
APP_DIR = Path(os.environ.get("VOICESPEAK_HOME") or Path.home() / "voicespeak")
CACHE_DIR = APP_DIR / "audio_cache"
DATA_DIR = APP_DIR / "data"
LOCAL_BOARDS = DATA_DIR / "boards.json"  # last good sync, offline fallback

# Bundled default layout used on a first boot with no internet.
PACKAGE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BOARDS = PACKAGE_DIR / "config" / "default_boards.json"
DEFAULT_INPUT_MAP = PACKAGE_DIR / "config" / "default_input_map.json"
VERSION_FILE = PACKAGE_DIR / "VERSION"

# The official VoiceSpeak cloud; SUPABASE_URL overrides it for self-hosting.
DEFAULT_CLOUD_URL = "https://drwgbsakfnrgyzdsitxt.supabase.co"


def load_env(env_path: Path | None = None) -> None:
    path = env_path or (APP_DIR / ".env")
    if not path.exists():
        # also try alongside the package for dev runs
        path = PACKAGE_DIR / ".env"
        if not path.exists():
            return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def cloud_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/") or DEFAULT_CLOUD_URL


def sync_interval() -> float:
    """Seconds between background cloud syncs (0 disables; boot sync only)."""
    try:
        return max(0.0, float(os.environ.get("SYNC_INTERVAL_SECONDS", "60")))
    except ValueError:
        return 60.0


def voice_engine() -> str:
    """Which TTS backend to use: piper (default), elevenlabs, or espeak."""
    explicit = os.environ.get("VOICE_ENGINE", "").strip().lower()
    if explicit:
        return explicit
    if os.environ.get("ELEVENLABS_API_KEY") and os.environ.get("ELEVENLABS_VOICE_ID"):
        return "elevenlabs"
    return "piper"


def load_input_map() -> dict[str, Action]:
    """Input id (e.g. 'gpio:17', 'hid:304') -> Action.

    Override path via INPUT_MAP_FILE; otherwise use the bundled default.
    """
    path = Path(os.environ.get("INPUT_MAP_FILE", DEFAULT_INPUT_MAP))
    with open(path) as f:
        raw = json.load(f)
    return {input_id: Action.from_dict(spec) for input_id, spec in raw.items()}


def env_path() -> Path:
    return APP_DIR / ".env"


def update_env_text(text: str, updates: dict[str, str]) -> str:
    """Set KEY=VALUE lines in .env content, keeping everything else."""
    lines, done = [], set()
    for line in text.splitlines():
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in updates:
            lines.append(f"{key}={updates[key]}")
            done.add(key)
        else:
            lines.append(line)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    return "\n".join(lines) + "\n"


def write_env(updates: dict[str, str]) -> None:
    """Persist KEY=VALUE pairs to the device .env (mode 600) and os.environ."""
    path = env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.exists() else ""
    path.write_text(update_env_text(text, updates))
    os.chmod(path, 0o600)
    # When run as root (setup portal), hand the file back to the dir's owner.
    try:
        st = path.parent.stat()
        if os.geteuid() == 0:
            os.chown(path, st.st_uid, st.st_gid)
    except (OSError, AttributeError):
        pass
    os.environ.update(updates)
