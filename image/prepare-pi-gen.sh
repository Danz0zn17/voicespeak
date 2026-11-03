#!/bin/bash
# Put the VoiceSpeak stage and config into a pi-gen checkout.
# Usage: prepare-pi-gen.sh <pi-gen dir> <version> <git commit>
# Shared by build-local.sh and the GitHub workflow so both build the same image.
set -euo pipefail

PI_GEN_DIR="$1"
VERSION="$2"
REF="$3"
HERE="$(cd "$(dirname "$0")" && pwd)"

case "${VERSION}" in
	*[!A-Za-z0-9._-]*) echo "Version may only contain letters, digits, dot, dash and underscore" >&2; exit 1 ;;
esac

# build-docker.sh copies only the pi-gen folder into its container
rm -rf "${PI_GEN_DIR}/stage-voicespeak"
cp -R "${HERE}/stage-voicespeak" "${PI_GEN_DIR}/stage-voicespeak"
chmod +x "${PI_GEN_DIR}/stage-voicespeak/prerun.sh" "${PI_GEN_DIR}/stage-voicespeak/00-voicespeak/01-run.sh"

# Only export our image, not the plain Lite image from stage2
touch "${PI_GEN_DIR}/stage2/SKIP_IMAGES"

sed -e "s/@VERSION@/${VERSION}/g" -e "s/@REF@/${REF}/g" \
	"${HERE}/config.template" > "${PI_GEN_DIR}/config"
echo "pi-gen prepared for VoiceSpeak ${VERSION} at ${REF}"
