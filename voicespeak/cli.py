"""Entry point: load config, sync boards, build TTS + inputs, run the loop.

Run with:  python3 -m voicespeak          the device (default)
           python3 -m voicespeak pair     Bluetooth controller pairing mode
           python3 -m voicespeak setup    first-boot Wi-Fi hotspot (as root)
           python3 -m voicespeak update   update to the newest release (timer)
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

from . import config
from .bench import SwitchesSeen, self_test_line
from .engine import Engine
from .input import build_sources, merge
from .models import SPEAK_CODE, SYNC
from .sync import BackgroundSync, _adapt, load_boards
from .tts import get_tts


def _legacy_mode() -> bool:
    """Old installs that read tables with the anon key and have no token."""
    return bool(os.environ.get("SUPABASE_ANON_KEY")) and not os.environ.get("DEVICE_TOKEN")


def run() -> int:
    from . import bt_pair, cloud

    tts = get_tts(config.voice_engine(), config.CACHE_DIR)
    legacy = _legacy_mode()
    # Paired and new boxes start from local data; the cloud link syncs at once.
    boards = load_boards(use_cloud=legacy)

    # Pre-cache every phrase so presses are instant and work offline.
    phrases = [c.phrase for b in boards for c in b.cells if c.phrase]
    tts.precache(phrases)

    def pair_in_background() -> None:
        threading.Thread(target=bt_pair.run_pairing_mode, args=(tts,),
                         name="pair", daemon=True).start()

    engine = Engine(boards, tts, on_pair=pair_in_background)

    syncer = BackgroundSync(
        config.sync_interval(), boards,
        apply=engine.replace_boards, precache=tts.precache,
    )

    input_map = config.load_input_map()
    sources = build_sources(input_map)
    hid = next((s for s in sources if s.name == "hid"), None)
    has_gpio = any(s.name == "gpio" for s in sources)
    switches = SwitchesSeen()

    def controllers() -> list[str]:
        return hid.connected_names() if hid else []

    link = None
    if legacy:
        engine.on_sync = load_boards
        syncer.start()
    else:
        def on_command(cmd: str) -> None:
            print(f"Command from app: {cmd}")
            if cmd == "pair_controller":
                bt_pair.run_pairing_mode(tts)
            elif cmd == "test_speak":
                tts.speak_system("Hello, I am working.")
            elif cmd == "speak_code":
                link.speak_code()

        def status() -> dict:
            return cloud.status_payload(
                cloud.sw_version(), cloud.device_model(), has_gpio,
                controllers(), bt_pair.bt_available(), switches.seen,
            )

        def on_claimed() -> None:
            from .setup_portal import forget_bench_wifi
            forget_bench_wifi()

        link = cloud.DeviceLink(
            tts, offer=syncer.offer, set_state=syncer.set_state, status=status,
            on_command=on_command, adapt=_adapt, on_claimed=on_claimed,
        )
        engine.on_sync = None
        link.start()

    if not sources:
        print("No input sources available. Check the controller / GPIO wiring.")
        return 1

    # A controller in pairing mode at boot is paired without anyone asking.
    if hid is not None:
        threading.Thread(target=bt_pair.auto_pair_window,
                         args=(tts, has_gpio, controllers), name="auto-pair",
                         daemon=True).start()

    print(f"Ready. Starting board: {engine.board.name}")
    try:
        for input_id in merge(sources):
            action = input_map.get(input_id)
            switches.note(input_id)  # reported in the next status heartbeat
            # Unclaimed: say what each input is, so wiring can be checked.
            if link and link.self_test:
                line = self_test_line(input_id, action)
                if line:
                    tts.speak_system(line)
                    continue
            if not action:
                continue
            if action.kind == SPEAK_CODE:
                if link:
                    link.speak_code()
                continue
            if action.kind == SYNC and link:
                link.sync_now()
                continue
            engine.dispatch(action)
    except KeyboardInterrupt:
        print("Exiting.")
    finally:
        syncer.stop()
        if link:
            link.stop()
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
        print("Paired. The running device service picks it up by itself.")
    return 0 if ok else 1


def setup() -> int:
    from .setup_portal import run_setup
    # Runs as root: keep its audio cache out of the device user's directory.
    tts = _setup_tts(Path(tempfile.gettempdir()) / "voicespeak-setup")
    return run_setup(tts)


def update() -> int:
    from .updater import run_update
    return run_update()


COMMANDS = {"run": run, "pair": pair, "setup": setup, "update": update}


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
