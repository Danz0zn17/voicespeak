"""TTS factory with a graceful fallback chain.

Default chain: requested engine -> piper -> espeak. ElevenLabs is only used when
explicitly selected (it costs money and needs internet).
"""

from __future__ import annotations

from pathlib import Path

from .base import TTSEngine


def _build(name: str, cache_dir: Path) -> TTSEngine:
    if name == "piper":
        from .piper import PiperTTS
        return PiperTTS(cache_dir)
    if name == "elevenlabs":
        from .elevenlabs import ElevenLabsTTS
        return ElevenLabsTTS(cache_dir)
    if name == "espeak":
        from .espeak import EspeakTTS
        return EspeakTTS(cache_dir)
    raise ValueError(f"Unknown voice engine: {name}")


def get_tts(name: str, cache_dir: Path) -> TTSEngine:
    chain = [name]
    for fallback in ("piper", "espeak"):
        if fallback not in chain:
            chain.append(fallback)
    last_error: Exception | None = None
    for candidate in chain:
        try:
            engine = _build(candidate, cache_dir)
            if candidate != name:
                print(f"Voice engine '{name}' unavailable; using '{candidate}'.")
            return engine
        except Exception as e:  # noqa: BLE001 - try the next backend
            last_error = e
            print(f"Voice engine '{candidate}' unavailable: {e}")
    raise RuntimeError(f"No usable TTS engine. Last error: {last_error}")
