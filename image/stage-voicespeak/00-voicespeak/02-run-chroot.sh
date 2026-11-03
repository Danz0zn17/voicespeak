#!/bin/bash -e
# Runs inside the image (pi-gen on_chroot). Installs everything install.sh
# installs, but for a dedicated "voicespeak" account and with no device token:
# the box registers itself on first boot.

# shellcheck disable=SC1091
. /root/voicespeak-build.env
rm -f /root/voicespeak-build.env

DEVICE_USER=voicespeak
HOME_DIR="/home/${DEVICE_USER}"
APP_DIR="${HOME_DIR}/voicespeak-app"
DATA_DIR="${HOME_DIR}/voicespeak"
PIPER_DIR="${DATA_DIR}/piper"
VOICE="en_US-lessac-medium"
VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium"

# A separate account from the login user (uid 1000). Raspberry Pi Imager's
# customisation renames uid 1000 to whatever username Levi picks; keeping the
# app out of that account means a rename can never break the device.
if ! id -u "${DEVICE_USER}" >/dev/null 2>&1; then
	adduser --disabled-password --gecos "VoiceSpeak device" "${DEVICE_USER}"
fi
passwd -l "${DEVICE_USER}"
for group in audio gpio input bluetooth video netdev; do
	if getent group "${group}" >/dev/null; then
		adduser "${DEVICE_USER}" "${group}"
	fi
done
DEVICE_UID="$(id -u "${DEVICE_USER}")"

# The client, on main at the commit being released, so the nightly updater can
# fast-forward from here.
rm -rf "${APP_DIR}"
git clone --branch main "${VOICESPEAK_REPO}" "${APP_DIR}"
git -C "${APP_DIR}" reset --hard "${VOICESPEAK_REF}"
echo "${VOICESPEAK_VERSION}" > "${APP_DIR}/.image-version"
# Root-run units (setup portal, updater) use git in a directory owned by the device user
git config --system --add safe.directory "${APP_DIR}"

pip3 install --break-system-packages -r "${APP_DIR}/requirements.txt"
if ! pip3 install --break-system-packages piper-tts; then
	if [ "${VOICESPEAK_ALLOW_ESPEAK}" = "1" ]; then
		echo "WARNING: piper-tts did not install; the image will use the espeak voice"
	else
		echo "ERROR: piper-tts did not install. Set VOICESPEAK_ALLOW_ESPEAK=1 to ship with espeak." >&2
		exit 1
	fi
fi

mkdir -p "${PIPER_DIR}"
curl -fsSL -o "${PIPER_DIR}/${VOICE}.onnx" "${VOICE_BASE}/${VOICE}.onnx"
curl -fsSL -o "${PIPER_DIR}/${VOICE}.onnx.json" "${VOICE_BASE}/${VOICE}.onnx.json"

# Public settings only. No DEVICE_TOKEN: the box gets one when a parent claims it.
cat > "${DATA_DIR}/.env" <<EOF
SUPABASE_URL=${VOICESPEAK_CLOUD_URL}

# Voice: piper (default, offline), elevenlabs, or espeak
VOICE_ENGINE=piper
PIPER_BIN=piper
PIPER_MODEL=${PIPER_DIR}/${VOICE}.onnx
EOF
chmod 600 "${DATA_DIR}/.env"
chown -R "${DEVICE_USER}:${DEVICE_USER}" "${HOME_DIR}"

# systemd units from the client repo, templated for this account the same way
# install.sh templates voicespeak.service
REQUIRED_UNITS="voicespeak.service voicespeak-setup.service voicespeak-update.service voicespeak-update.timer"
for unit in ${REQUIRED_UNITS}; do
	if [ ! -f "${APP_DIR}/systemd/${unit}" ]; then
		echo "ERROR: ${unit} is missing from the client repo's systemd/ folder" >&2
		exit 1
	fi
done
for src in "${APP_DIR}"/systemd/*.service "${APP_DIR}"/systemd/*.timer; do
	[ -f "${src}" ] || continue
	sed -e "s#^User=pi\$#User=${DEVICE_USER}#" \
		-e "s#/home/pi/#${HOME_DIR}/#g" \
		-e "s#/home/pi\$#${HOME_DIR}#g" \
		-e "s#/run/user/1000#/run/user/${DEVICE_UID}#g" \
		"${src}" > "/etc/systemd/system/$(basename "${src}")"
done

# Keep a user runtime dir (/run/user/<uid>) for the service account at boot
mkdir -p /var/lib/systemd/linger
touch "/var/lib/systemd/linger/${DEVICE_USER}"

systemctl enable voicespeak-firstboot.service
systemctl enable voicespeak.service voicespeak-setup.service voicespeak-update.timer
systemctl enable bluetooth.service
