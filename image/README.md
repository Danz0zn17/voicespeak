# VoiceSpeak SD card image

One file you flash onto a microSD card. The card boots straight into VoiceSpeak:
no keyboard, no screen, no typing. The same image works in a **Raspberry Pi
Zero 2 W** build and a **Raspberry Pi 4** build.

What is already on the card:
- Raspberry Pi OS Lite (Bookworm, 64-bit)
- The VoiceSpeak software at the released version, the natural offline voice
  (Piper, en_US-lessac-medium), the espeak backup voice and all packages
- VoiceSpeak, the phone Wi-Fi setup and the nightly self-update, all switched on
- Only public settings. No account details and no device token: each box
  registers itself the first time it is online.

What happens on first boot:
1. The box names itself `voicespeak-xxxx` (the last 4 characters of its
   serial number), so several boxes on one network can be told apart.
2. It picks the right speaker: the I2S amplifier on a Zero 2 W build, the
   headphone jack on a Pi 4. Never HDMI.
3. If there is no network, it opens the **VoiceSpeak-Setup** Wi-Fi for a phone.

## Making a release (Danny)

1. Make sure everything you want in the image is pushed to `main`.
2. Sign the tag with the release key and push it. Boxes ignore unsigned tags
   (see "Self-update" in the main README):
   ```
   git -c gpg.format=ssh -c user.signingkey=~/.ssh/voicespeak_release.pub \
     tag -s v1.0.0 -m v1.0.0
   git push origin v1.0.0
   ```
3. GitHub builds the image. It takes 1 to 2 hours. Watch it under
   **Actions > Build SD card image**.
4. When it finishes, the release page has three files:
   - `VoiceSpeak-v1.0.0-arm64.img.xz`: the image
   - `VoiceSpeak-v1.0.0-arm64.img.xz.sha256`: its checksum
   - `voicespeak-imager.json`: lets Raspberry Pi Imager list VoiceSpeak by name

For a trial build without publishing a release: **Actions > Build SD card image
> Run workflow**, give it a label such as `test`, and download the image from the
run's artifacts (kept 7 days).

The build runs on GitHub's ARM runners, which are free for public repositories.
If the repository is ever made private, the runner needs a paid plan or a switch
to `ubuntu-latest` (slower, emulated).

## Flashing a card (Levi, or anyone)

You need: a computer, a microSD card reader and a 32GB card.

1. Install **Raspberry Pi Imager** from raspberrypi.com/software (version 2.0 or newer).
2. Tell Imager where VoiceSpeak lives, once per computer:
   - Open **App Options** (bottom left), then **Content Repository**.
   - Choose **Use custom URL** and paste:
     `https://github.com/Danz0zn17/voicespeak/releases/latest/download/voicespeak-imager.json`
   - Press **Save**. Imager restarts its wizard.
3. **Device:** choose Raspberry Pi Zero 2 W or Raspberry Pi 4.
4. **Operating system:** choose **VoiceSpeak**.
5. **Storage:** choose the SD card. Double-check it is the card, not a USB drive.
6. **Customisation:**
   - For a box going to a family: skip it all. The family sets up Wi-Fi from their phone.
   - On the bench: you may add your workshop Wi-Fi so the box is online straight away.
   - To get into the box for support: set a username and password, and turn on
     SSH under Remote access. Leave SSH off for boxes that ship.
7. **Write**, wait for it to verify, take the card out, put it in the Pi.

Without the custom repository you can still choose **Use custom** and pick the
downloaded `.img.xz` file. Imager 2.x then hides the customisation screen,
because it cannot tell what kind of image a bare file is. The box still works:
the family sets up Wi-Fi from their phone.

## Bench test checklist (every box)

- [ ] Card flashed and verified by Imager
- [ ] Power on. Within about 2 minutes the box speaks.
- [ ] If not on Wi-Fi: a phone sees **VoiceSpeak-Setup**, the page opens and the box joins Wi-Fi
- [ ] Each big switch speaks its phrase; Next board and Repeat work
- [ ] Hold Next board for 5 seconds: "Pairing mode". Turn on a Bluetooth controller: "Controller connected"
- [ ] A USB controller works when plugged in
- [ ] Volume is loud enough across a room
- [ ] The box appears in the parent app's device finder on the same Wi-Fi
- [ ] Switch off, switch on again: it comes back by itself and the controller reconnects
- [ ] Label on the box, then into the shipping box

## Building on your own machine

Use this to try a change to the image before tagging a release. You need Docker
and about 20GB of free disk. An Apple Silicon Mac builds natively.

```
image/build-local.sh v1.0.0-test
```

The image clones the VoiceSpeak software from GitHub at your current commit, so
push that commit to `main` first. The script stops and tells you if you have not.
The result lands in `image/deploy/`.

If a build fails part-way and you rerun it, Docker may say the `pigen_work`
container already exists. Remove it with `docker rm -v pigen_work`.

## How it is built

- [pi-gen](https://github.com/RPi-Distro/pi-gen), branch `bookworm-arm64`,
  pinned to a known commit in `build-local.sh` and the workflow.
- `stage-voicespeak/` runs after pi-gen's Lite stages (`stage0 stage1 stage2`):
  - `00-packages`: apt packages (git, pip, mpg123, espeak-ng, alsa-utils, bluez...).
  - `01-run.sh`: copies in the boot helper and adds the Zero 2 W amplifier
    setting to `config.txt`, inside a `[pi02]` section so a Pi 4 ignores it.
  - `02-run-chroot.sh`: creates the `voicespeak` account, clones the software,
    installs Python packages and Piper, downloads the voice, writes `.env` and
    switches on the services.
  - `files/`: the every-boot helper (unique hostname once, speaker choice).
- `config.template`: South African locale, timezone and Wi-Fi country, hostname
  `voicespeak`, SSH off.
- `make-imager-repo.py`: writes `voicespeak-imager.json`. It uses
  `"init_format": "systemd"`, the format Bookworm images use, so Imager offers
  its customisation screen.

Why a separate `voicespeak` account: Imager's customisation renames the first
user (uid 1000) to whatever name you type and moves its home folder. VoiceSpeak
runs from its own account so that rename can never break it. The login account
is locked until you set a password in Imager.

If Piper fails to install, the build stops rather than shipping the robotic
espeak voice. To ship with espeak deliberately, set `VOICESPEAK_ALLOW_ESPEAK=1`
in `config.template`.
