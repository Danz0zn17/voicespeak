"""Piper offline neural TTS (default voice). Free, on-device, multilingual.

Requires the `piper` binary and a voice model on the Pi. Install handled by the
device setup, not pip. See docs/spec.md.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .base import TTSEngine


class PiperTTS(TTSEngine):
    ext = ".wav"

    def __init__(self, cache_dir: Path, model_path: str | None = None):
        super().__init__(cache_dir)
        self.binary = os.environ.get("PIPER_BIN", "piper")
        self.model = model_path or os.environ.get("PIPER_MODEL", "")
        if shutil.which(self.binary) is None:
            raise RuntimeError(f"Piper binary '{self.binary}' not found")
        if not self.model or not Path(self.model).exists():
            raise RuntimeError(f"Piper model not found: {self.model!r}")

    def _synth(self, text: str, out_path: Path) -> bool:
        try:
            subprocess.run(
                [self.binary, "--model", self.model, "--output_file", str(out_path)],
                input=text.encode(),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as e:  # noqa: BLE001
            print(f"Piper synthesis failed for {text!r}: {e}")
            return False
