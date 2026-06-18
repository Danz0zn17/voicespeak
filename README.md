# VoiceSpeak (Pi client)

Low-cost AAC device that gives people with cerebral palsy a voice. Physical
inputs (GPIO switches, USB or Bluetooth gamepads) trigger spoken phrases that a
caregiver edits from a web dashboard, synced from the cloud and cached for
offline use.

Full product spec: [docs/spec.md](docs/spec.md).

## Layout

```
voicespeak/
  engine.py     board/cell logic, navigation, repeat-last (pure, tested)
  models.py     Board, Cell, Action
  config.py     env, paths, voice-engine selection, input map
  sync.py       Supabase sync + offline fallback (local cache, then defaults)
  tts/          piper (default), elevenlabs (optional), espeak (fallback), cache
  input/        gpio.py, hid.py (USB+BT), learn.py (button-learning), factory
  cli.py        entry point: python3 -m voicespeak
config/
  default_boards.json     bundled layout for first boot with no internet
  default_input_map.json  default input bindings (override via INPUT_MAP_FILE)
systemd/voicespeak.service  start on boot, restart on crash
tests/test_engine.py        engine logic tests (no hardware needed)
```

## Run (dev)

```
pip install -r requirements.txt
cp .env.example .env   # fill in Supabase creds
python3 -m voicespeak
```

On a Pi, also install the system packages the voices/playback need:

```
sudo apt-get install -y mpg123 espeak-ng        # playback + fallback voice
# Piper (default voice): install the piper binary + a voice model, then set
# PIPER_BIN and PIPER_MODEL in .env
```

## Configuration (.env)

| Key | Purpose |
|-----|---------|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | cloud sync |
| `VOICE_ENGINE` | `piper` (default), `elevenlabs`, or `espeak` |
| `PIPER_BIN`, `PIPER_MODEL` | Piper binary + voice model path |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | optional premium voice |
| `INPUT_MAP_FILE` | override the default input map |

## Tests

```
python3 -m pytest -q
```
