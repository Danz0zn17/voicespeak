"""espeak-ng fallback voice. Robotic but always-available and fully offline.

Speaks directly (no useful caching benefit), so it overrides speak().
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .base import TTSEngine


class EspeakTTS(TTSEngine):
    ext = ".wav"

    def __init__(self, cache_dir: Path):
        super().__init__(cache_dir)
        self.binary = "espeak-ng" if shutil.which("espeak-ng") else "espeak"
        if shutil.which(self.binary) is None:
            raise RuntimeError("espeak / espeak-ng not found")

    def _synth(self, text: str, out_path: Path) -> bool:
        try:
            subprocess.run([self.binary, "-w", str(out_path), text], check=True)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"espeak synthesis failed for {text!r}: {e}")
            return False
