"""Entry point: load config, sync boards, build TTS + inputs, run the loop.

Run with:  python3 -m voicespeak
"""

from __future__ import annotations

from . import config
from .engine import Engine
from .input import build_sources, merge
from .sync import load_boards
from .tts import get_tts


def main() -> int:
    config.load_env()

    tts = get_tts(config.voice_engine(), config.CACHE_DIR)
    boards = load_boards()

    # Pre-cache every phrase so presses are instant and work offline.
    phrases = [c.phrase for b in boards for c in b.cells if c.phrase]
    tts.precache(phrases)

    engine = Engine(boards, tts, on_sync=load_boards)

    input_map = config.load_input_map()
    sources = build_sources(input_map)
    if not sources:
        print("No input sources available. Check the controller / GPIO wiring.")
        return 1

    print(f"Ready. Starting board: {engine.board.name}")
    try:
        for input_id in merge(sources):
            action = input_map.get(input_id)
            if action:
                engine.dispatch(action)
    except KeyboardInterrupt:
        print("Exiting.")
    finally:
        for src in sources:
            src.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
