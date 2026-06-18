"""ElevenLabs TTS (optional premium voice). Needs internet and an API key."""

from __future__ import annotations

import os
from pathlib import Path

from .base import TTSEngine

MODEL = "eleven_multilingual_v2"


class ElevenLabsTTS(TTSEngine):
    ext = ".mp3"

    def __init__(self, cache_dir: Path):
        super().__init__(cache_dir)
        self.api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        self.voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "")
        if not self.api_key or not self.voice_id:
            raise RuntimeError("ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID required")

    def _synth(self, text: str, out_path: Path) -> bool:
        try:
            from elevenlabs.client import ElevenLabs
            client = ElevenLabs(api_key=self.api_key)
            audio = client.text_to_speech.convert(
                voice_id=self.voice_id,
                text=text,
                model_id=MODEL,
                output_format="mp3_44100_128",
            )
            with open(out_path, "wb") as f:
                for chunk in audio:
                    f.write(chunk)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"ElevenLabs synthesis failed for {text!r}: {e}")
            return False
