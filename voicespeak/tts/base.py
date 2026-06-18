"""TTS base class, shared cache, and audio playback."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def play_file(path: Path) -> bool:
    """Play an audio file. Returns False on failure (never raises)."""
    ext = path.suffix.lower()
    if ext == ".mp3":
        player = "mpg123"
        cmd = [player, "-q", str(path)]
    else:  # wav and friends
        player = "aplay"
        cmd = [player, "-q", str(path)]
    if shutil.which(player) is None:
        print(f"Audio player '{player}' not found - cannot play {path.name}")
        return False
    try:
        subprocess.run(cmd, check=True)
        return True
    except Exception as e:  # noqa: BLE001 - playback must not crash the device
        print(f"Playback failed for {path.name}: {e}")
        return False


class TTSEngine:
    """Subclasses implement _synth(text, out_path) and set self.ext."""

    ext = ".wav"

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, text: str) -> Path:
        return self.cache_dir / f"{text_hash(text)}{self.ext}"

    def _synth(self, text: str, out_path: Path) -> bool:
        raise NotImplementedError

    def precache(self, phrases: list[str]) -> None:
        todo = [t for t in phrases if t and not self._cache_path(t).exists()]
        if not todo:
            return
        print(f"Caching {len(todo)} phrase(s)...")
        for i, text in enumerate(todo, 1):
            print(f"  {i}/{len(todo)}: {text!r}")
            self._synth(text, self._cache_path(text))

    def speak(self, text: str) -> None:
        if not text:
            return
        print(f"Speaking: {text}")
        path = self._cache_path(text)
        if not path.exists():
            if not self._synth(text, path):
                return
        play_file(path)

    def speak_system(self, text: str) -> None:
        # System prompts ("Board: Kitchen") use the same path by default.
        self.speak(text)
