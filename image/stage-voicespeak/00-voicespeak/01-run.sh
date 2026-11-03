#!/bin/bash -e
# Host side of the VoiceSpeak stage: copy our files into the image and pass the
# build settings to the chroot step. Runs with pi-gen's ROOTFS_DIR exported.

: "${VOICESPEAK_REPO:?set VOICESPEAK_REPO in the build config}"
: "${VOICESPEAK_REF:?set VOICESPEAK_REF in the build config}"
: "${VOICESPEAK_VERSION:?set VOICESPEAK_VERSION in the build config}"
: "${VOICESPEAK_CLOUD_URL:?set VOICESPEAK_CLOUD_URL in the build config}"

# Every-boot helper: unique hostname once, then pick the right sound output.
install -m 755 files/voicespeak-firstboot.sh "${ROOTFS_DIR}/usr/local/sbin/voicespeak-firstboot"
install -m 644 files/voicespeak-firstboot.service "${ROOTFS_DIR}/etc/systemd/system/"

# Pi Zero 2 W builds drive the speaker through a MAX98357A I2S amp. The [pi02]
# filter applies only to the Zero 2 W, so a Pi 4 keeps its headphone jack.
CONFIG_TXT="${ROOTFS_DIR}/boot/firmware/config.txt"
if ! grep -q "VoiceSpeak" "${CONFIG_TXT}"; then
	cat >> "${CONFIG_TXT}" <<-'EOF'

		# VoiceSpeak: I2S speaker amplifier on the Pi Zero 2 W build only
		[pi02]
		dtoverlay=max98357a
		[all]
	EOF
fi

# Settings for the chroot step (read and deleted there)
cat > "${ROOTFS_DIR}/root/voicespeak-build.env" <<EOF
VOICESPEAK_REPO='${VOICESPEAK_REPO}'
VOICESPEAK_REF='${VOICESPEAK_REF}'
VOICESPEAK_VERSION='${VOICESPEAK_VERSION}'
VOICESPEAK_CLOUD_URL='${VOICESPEAK_CLOUD_URL}'
VOICESPEAK_ALLOW_ESPEAK='${VOICESPEAK_ALLOW_ESPEAK:-0}'
EOF
