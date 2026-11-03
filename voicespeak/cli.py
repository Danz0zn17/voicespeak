"""Entry point: load config, sync boards, build TTS + inputs, run the loop.

Run with:  python3 -m voicespeak          the device (default)
           python3 -m voicespeak pair     Bluetooth controller pairing mode
           python3 -m voicespeak setup    first-boot Wi-Fi hotspot (as root)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from . import config
from .engine import Engine
from .input import build_sources, merge
from .sync import BackgroundSync, load_boards
from .tts import get_tts

# Exit code after pairing mode: systemd (Restart=always) restarts the service,
# which picks up the new controller and drops presses queued while pairing.
EXIT_RESTART = 75


def run() -> int:
    tts = get_tts(config.voice_engine(), config.CACHE_DIR)
    boards = load_boards()

    # Pre-cache every phrase so presses are instant and work offline.
    phrases = [c.phrase for b in boards for c in b.cells if c.phrase]
    tts.precache(phrases)

    restart = False

    def on_pair() -> None:
        nonlocal restart
        from .bt_pair import run_pairing_mode
        run_pairing_mode(tts)
        restart = True

    engine = Engine(boards, tts, on_sync=load_boards, on_pair=on_pair)

    # Parent edits in the dashboard reach the device within one interval.
    syncer = BackgroundSync(
        config.sync_interval(), boards,
        apply=engine.replace_boards, precache=tts.precache,
    )
    syncer.start()

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
            if restart:
                print("Restarting to load the new controller.")
                return EXIT_RESTART
    except KeyboardInterrupt:
        print("Exiting.")
    finally:
        syncer.stop()
        for src in sources:
            src.close()
    return 0


class _PrintOnly:
    """Stand-in voice for setup commands on a machine with no TTS engine."""

    def speak_system(self, text: str) -> None:
        print(f"(would say) {text}")


def _setup_tts(cache_dir: Path):
    try:
        return get_tts(config.voice_engine(), cache_dir)
    except Exception as e:  # noqa: BLE001 - setup must still run silently
        print(f"No voice available ({e}); prompts will only be logged.")
        return _PrintOnly()


def pair() -> int:
    from .bt_pair import run_pairing_mode
    tts = _setup_tts(config.CACHE_DIR)
    ok = run_pairing_mode(tts)
    if ok:
        print("Restart the device service to use it: sudo systemctl restart voicespeak")
    return 0 if ok else 1


def setup() -> int:
    from .setup_portal import run_setup
    # Runs as root: keep its audio cache out of the device user's directory.
    tts = _setup_tts(Path(tempfile.gettempdir()) / "voicespeak-setup")
    return run_setup(tts)


COMMANDS = {"run": run, "pair": pair, "setup": setup}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else "run"
    if command not in COMMANDS:
        print(f"Unknown command '{command}'. Use one of: {', '.join(COMMANDS)}")
        return 2
    config.load_env()
    return COMMANDS[command]()


if __name__ == "__main__":
    raise SystemExit(main())
