# VoiceSpeak (Pi client)

Low-cost AAC device that gives people with cerebral palsy a voice. Physical
inputs (GPIO switches, USB or Bluetooth gamepads) trigger spoken phrases that a
caregiver edits from a web dashboard, synced from the cloud and cached for
offline use.

The detailed product spec (BOM, pricing, roadmap) is maintained privately.

## Layout

```
voicespeak/
  engine.py     board/cell logic, navigation, repeat-last (pure, tested)
  models.py     Board, Cell, Action
  config.py     env, paths, voice-engine selection, input map
  sync.py       Supabase sync + offline fallback (local cache, then defaults)
  tts/          piper (default), elevenlabs (optional), espeak (fallback), cache
  input/        gpio.py, hid.py (USB+BT), learn.py (button-learning), factory
  bt_pair.py    Bluetooth controller pairing mode (bluetoothctl)
  setup_portal.py  first-boot Wi-Fi hotspot + phone setup page (nmcli)
  cli.py        entry point: python3 -m voicespeak [run|pair|setup]
config/
  default_boards.json     bundled layout for first boot with no internet
  default_input_map.json  default input bindings (override via INPUT_MAP_FILE)
systemd/voicespeak.service        start on boot, restart on crash
systemd/voicespeak-setup.service  Wi-Fi setup hotspot when offline at boot
tests/                      engine, sync, pairing + setup tests (no hardware needed)
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
| `SUPABASE_URL`, `DEVICE_TOKEN` | cloud sync for a paired device (normal setup) |
| `SUPABASE_ANON_KEY` | legacy direct table access (own Supabase project) |
| `VOICE_ENGINE` | `piper` (default), `elevenlabs`, or `espeak` |
| `PIPER_BIN`, `PIPER_MODEL` | Piper binary + voice model path |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | optional premium voice |
| `INPUT_MAP_FILE` | override the default input map |
| `SYNC_INTERVAL_SECONDS` | how often to pull dashboard changes (default 60, 0 = boot only) |
| `SETUP_HOTSPOT_PASSWORD` | optional WPA password for the setup hotspot (8+ chars; empty = open) |
| `SETUP_PORT` | setup page port (default 80) |

## Live updates

The device syncs at boot, then re-checks the cloud every
`SYNC_INTERVAL_SECONDS` on a background thread. New phrases are voiced and
cached first, then swapped in silently, only when the content actually changed.
Offline ticks keep the current phrases; the log notes only online/offline
changes, not every tick.

## Bluetooth controller pairing

Hold the mapped button for 5 seconds (default: the GPIO 22 switch, or the
controller's button 307), or run `python3 -m voicespeak pair`. The device says
"Pairing mode. Turn on your controller.", scans for about 60 seconds, then
pairs, trusts and connects the first gamepad it finds, and says "Controller
connected." or "No controller found." The service then restarts itself to load
the controller. Any input id with `:hold` can be mapped to `{"kind": "bt_pair"}`
in the input map.

## Wi-Fi setup from a phone

Install once:

```
sudo cp systemd/voicespeak-setup.service /etc/systemd/system/
sudo systemctl enable voicespeak-setup.service
```

If the device has no network 45 seconds after boot, it starts a
`VoiceSpeak-Setup` hotspot and says so. Join it on a phone; the setup page
opens (or browse to http://10.42.0.1). Pick the home Wi-Fi, type the password
and, optionally, the pairing code from the box label. The device connects,
pairs, says "Connected." and restarts the main service. A wrong password brings
the hotspot back with a message. With nobody configuring it, the hotspot drops
every 15 minutes to let known networks reconnect. Needs NetworkManager
(Raspberry Pi OS Bookworm or later).

## Licence

MIT - see [LICENSE](LICENSE).

## Tests

```
python3 -m pytest -q
```
