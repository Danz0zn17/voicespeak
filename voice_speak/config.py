"""Environment, paths and the input-map default/override.

Reads a simple KEY=VALUE .env next to the install (no extra dependency).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Action

APP_DIR = Path.home() / "voice-speak"
CACHE_DIR = APP_DIR / "audio_cache"
DATA_DIR = APP_DIR / "data"
LOCAL_BOARDS = DATA_DIR / "boards.json"  # last good sync, offline fallback

# Bundled default layout used on a first boot with no internet.
PACKAGE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BOARDS = PACKAGE_DIR / "config" / "default_boards.json"
DEFAULT_INPUT_MAP = PACKAGE_DIR / "config" / "default_input_map.json"


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
