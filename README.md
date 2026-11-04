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
  bench.py      self-test speech while unclaimed, "switches seen" flag
  models.py     Board, Cell, Action
  config.py     env, paths, voice-engine selection, input map
  sync.py       board adapter, offline fallback, change-only swaps
  cloud.py      zero-typing setup: device-hello, claim code, status, commands
  updater.py    self-update to the newest v* release tag
  tts/          piper (default), elevenlabs (optional), espeak (fallback), cache
  input/        gpio.py, hid.py (USB+BT), learn.py (button-learning), factory
  bt_pair.py    Bluetooth controller pairing mode (bluetoothctl)
  setup_portal.py  first-boot Wi-Fi hotspot + phone setup page (nmcli)
  cli.py        entry point: python3 -m voicespeak [run|pair|setup|update]
config/
  default_boards.json     bundled layout for first boot with no internet
  default_input_map.json  default input bindings (override via INPUT_MAP_FILE)
systemd/voicespeak.service        start on boot, restart on crash
systemd/voicespeak-setup.service  Wi-Fi setup hotspot when offline at boot
systemd/voicespeak-update.*       daily self-update timer (+10 min after boot)
VERSION                     reported to the app as sw_version
tests/                      engine, sync, cloud, pairing + setup tests (no hardware needed)
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
| `SUPABASE_URL` | cloud base URL (defaults to the official VoiceSpeak cloud) |
| `DEVICE_TOKEN`, `DEVICE_SECRET`, `PAIRING_CODE` | written by the box itself on first boot; never type these |
| `HARDWARE_ID` | only on non-Pi dev machines (a Pi uses its CPU serial) |
| `SUPABASE_ANON_KEY` | legacy direct table access (own Supabase project) |
| `VOICE_ENGINE` | `piper` (default), `elevenlabs`, or `espeak` |
| `PIPER_BIN`, `PIPER_MODEL` | Piper binary + voice model path |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | optional premium voice |
| `INPUT_MAP_FILE` | override the default input map |
| `SYNC_INTERVAL_SECONDS` | how often to pull dashboard changes (default 60, 0 = boot only) |
| `SETUP_HOTSPOT_PASSWORD` | optional WPA password for the setup hotspot (8+ chars; empty = open) |
| `SETUP_PORT` | setup page port (default 80) |
| `BENCH_WIFI` | optional comma-separated Wi-Fi names/SSIDs to forget once a family connects the box |

## Zero-typing setup

A box with no `DEVICE_TOKEN` registers itself on first boot (`device-hello`
with its CPU serial and a secret generated on the box) and keeps working from
the bundled boards meanwhile. It says "Hello. To connect me, open the
VoiceSpeak app on a phone or computer on this Wi-Fi."

In the app, a parent on the same network sees the box and taps Connect. The
box then speaks a 4-digit number ("Type this number in the app: 4. 7. 2. 1."),
repeated every 20 seconds up to 6 times. Only someone in the room can hear it,
so a stranger sharing the same public IP (common with mobile and fibre
providers) cannot claim the box. Typing the number finishes the claim; the
box says "Connected." and loads the family's phrases straight away. While
unclaimed it checks every 10 seconds for 15 minutes after boot, then every
minute.

Fallback when the app cannot find the box (e.g. the phone is on mobile data):
hold the Repeat switch (GPIO 23, or controller button 308) for 5 seconds and
the box reads out its pairing code letter by letter, to type into the app.

If a box is removed in the app, its token stops working; the box forgets it
and registers again, ready for its next family.

If the network has registered too many new boxes in the last hour, the cloud
answers 429. The box says once "Too many new boxes on this network. I will
keep trying." and retries after the `retry_after_s` the cloud gives (default
10 minutes).

## Self-test (bench)

Until a family connects the box, every press says what the input is instead
of a phrase: "Red button", "More phrases", "Next board", "Repeat", or for a
controller "Controller bottom button. Red button.". Unmapped inputs say "Not
used". Long holds (pairing mode, speak the code) still work. Self-test stops
as soon as the cloud reports the box claimed; a claimed box that boots offline
never enters self-test.

Once claimed and online, the box forgets bench Wi-Fi: the Raspberry Pi Imager
connection (`preconfigured`) and any names in `BENCH_WIFI`. It never deletes
the connection it is using, and only does it while on another Wi-Fi.

## Buttons and phrases

Phrases map to fixed slots by their type in the app: `button_x` is the red
button (cell 0), `button_o` the blue button (cell 1), and `analog_left`
phrases follow as the "More phrases" scan list. An empty slot stays silent; a
missing red phrase never moves the blue phrase onto the red button. Scanning
skips empty slots.

## App commands

Each sync sends a status heartbeat (version, model, GPIO available,
`switches_seen`, connected controllers, Bluetooth available). `switches_seen`
turns true the first time any GPIO switch is pressed and stays true (flag file
`data/switches_seen` in the data dir); `gpio` is kept for older apps. The app can send one-shot
commands: `pair_controller`, `test_speak` ("Hello, I am working.") and
`speak_code`.

## Self-update

`voicespeak-update.timer` runs `python3 -m voicespeak update` 10 minutes after
boot and daily (randomised). It fetches tags and checks out the newest `vX.Y.Z`
release only if the current checkout does not already contain it, so it never
moves to untagged main and never downgrades. Dependencies are reinstalled only
when `requirements.txt` changed. The systemd units in `systemd/` are
re-templated for the box (the installer's `/home/pi/voicespeak-app` and
`/home/pi/voicespeak` substitution, plus the service user and runtime dir) and
installed when they changed, followed by `daemon-reload`; changed units are
restarted and the main service always is. One log line per run:
`journalctl -u voicespeak-update`. Releasing: set `VERSION` to the new number,
commit, then `git tag v0.3.1 && git push --tags`. The image build fails early
if `VERSION` does not match the tag.

## Live updates

The device syncs at boot, then re-checks the cloud every
`SYNC_INTERVAL_SECONDS` on a background thread. New phrases are voiced and
cached first, then swapped in silently, only when the content actually changed.
Offline ticks keep the current phrases; the log notes only online/offline
changes, not every tick.

## Controllers

Automatic: for 3 minutes after boot, if no controller is connected, the box
quietly looks for one in pairing mode and pairs it (it only asks out loud,
"Turn on your controller in pairing mode.", when there are no switches
either). Trusted controllers reconnect on their own, and the scan stops as
soon as one does.

Hotplug: controllers are picked up whenever they appear (USB plugged in,
Bluetooth paired, or switched back on) and dropped when they go, with no
service restart. Keyboards and power buttons are never grabbed.

Manual: hold the Next board switch (GPIO 22, or controller button 307) for 5
seconds, tap "Pair a controller" in the app, or run `python3 -m voicespeak pair`.
The box says "Pairing mode. Turn on your controller.", scans for about 60
seconds, then pairs, trusts and connects the first gamepad it finds. Only one
pairing runs at a time.

## Wi-Fi setup from a phone

Install once:

```
sudo cp systemd/voicespeak-setup.service /etc/systemd/system/
sudo systemctl enable voicespeak-setup.service
```

If the device has no network 45 seconds after boot, it starts a
`VoiceSpeak-Setup-C3D4` hotspot (the last 4 characters of the box's serial,
matching its name "VoiceSpeak C3D4") and says so. Join it on a phone; the
setup page opens (or browse to http://10.42.0.1). Pick the home Wi-Fi and type
the password; the app finds the box once it is online. A pairing code is still
accepted if an old page posts one.
The device connects, says "Connected." and restarts the main service. A wrong password brings
the hotspot back with a message. With nobody configuring it, the hotspot drops
every 15 minutes to let known networks reconnect. Needs NetworkManager
(Raspberry Pi OS Bookworm or later).

## Licence

MIT - see [LICENSE](LICENSE).

## Tests

```
python3 -m pytest -q
```
