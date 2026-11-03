#!/bin/bash
# Runs at every boot, before VoiceSpeak starts. Safe to run repeatedly.
#  1. Once: give the box a unique name (voicespeak-ab12) so several boxes on one
#     network can be told apart. Skipped if someone already chose a name in
#     Raspberry Pi Imager.
#  2. Every boot: point the default sound output at the speaker that is actually
#     fitted (I2S amp on the Zero build, headphone jack on the Pi 4), never HDMI.

STATE_DIR=/var/lib/voicespeak
HOSTNAME_MARK="${STATE_DIR}/hostname-set"
mkdir -p "${STATE_DIR}"

set_unique_hostname() {
	[ -e "${HOSTNAME_MARK}" ] && return
	if [ "$(hostname)" = "voicespeak" ]; then
		local serial suffix new
		serial="$(tr -d '\0' < /sys/firmware/devicetree/base/serial-number 2>/dev/null)"
		[ -n "${serial}" ] || serial="$(awk '/^Serial/ {print $3}' /proc/cpuinfo)"
		suffix="$(printf '%s' "${serial}" | tr 'A-F' 'a-f' | tail -c 4)"
		if [ -n "${suffix}" ]; then
			new="voicespeak-${suffix}"
			echo "${new}" > /etc/hostname
			if grep -q '^127\.0\.1\.1' /etc/hosts; then
				sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t${new}/" /etc/hosts
			else
				printf '127.0.1.1\t%s\n' "${new}" >> /etc/hosts
			fi
			hostname "${new}"
		fi
	fi
	touch "${HOSTNAME_MARK}"
}

# Card id (the word after "card N:") of the first card whose id or name
# matches $1. Only the card part is matched: HDMI cards have "i2s" in their
# device names, so matching the whole line would pick HDMI.
card_matching() {
	aplay -l 2>/dev/null \
		| sed -n 's/^card [0-9]*: \([^ ]*\) \[\([^]]*\)\].*/\1 \2/p' \
		| grep -i -E "$1" | head -n 1 | cut -d ' ' -f 1
}

choose_sound_output() {
	local card="" tries=0
	# Sound cards can appear a moment after boot
	while ! aplay -l 2>/dev/null | grep -q '^card ' && [ "${tries}" -lt 10 ]; do
		sleep 1
		tries=$((tries + 1))
	done
	card="$(card_matching 'max98357|hifiberry|i2s')"
	[ -n "${card}" ] || card="$(card_matching 'headphones|bcm2835')"
	# Unknown card name: take the first card that is not HDMI
	[ -n "${card}" ] || card="$(aplay -l 2>/dev/null \
		| sed -n 's/^card [0-9]*: \([^ ]*\) \[\([^]]*\)\].*/\1 \2/p' \
		| grep -v -i 'hdmi' | head -n 1 | cut -d ' ' -f 1)"
	[ -n "${card}" ] || return

	local wanted
	wanted="$(printf 'pcm.!default {\n  type plug\n  slave.pcm "hw:CARD=%s,DEV=0"\n}\nctl.!default {\n  type hw\n  card %s\n}\n' "${card}" "${card}")"
	if [ "$(cat /etc/asound.conf 2>/dev/null)" != "${wanted}" ]; then
		printf '%s\n' "${wanted}" > /etc/asound.conf
		echo "VoiceSpeak: default sound output set to ${card}"
	fi
}

set_unique_hostname
choose_sound_output
exit 0
