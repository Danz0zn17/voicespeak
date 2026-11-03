#!/bin/bash
# Build the VoiceSpeak SD card image on your own machine with Docker.
# The normal route is a GitHub release (see README.md); use this to test a
# change to the image before tagging.
#
# Usage: image/build-local.sh [version]      e.g. image/build-local.sh v0.3.0-test
# Needs: Docker, git, ~20GB free disk. On an Apple Silicon Mac or ARM Linux box
# it builds natively; on Intel it needs qemu binfmt (slow).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${HERE}/.." && pwd)"
VERSION="${1:-dev-$(date +%Y%m%d)}"
PI_GEN_BRANCH="bookworm-arm64"
PI_GEN_COMMIT="d47bb153dda58f2a53de061ef18ecc22d6afadaf"
PI_GEN_DIR="${HERE}/.pi-gen"

# The image clones the client from GitHub at this commit, so it must be pushed
REF="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
if ! git -C "${REPO_ROOT}" branch -r --contains "${REF}" | grep -q 'origin/main'; then
	echo "Commit ${REF} is not on origin/main yet. Push first, or the image build cannot fetch it." >&2
	exit 1
fi

if [ ! -d "${PI_GEN_DIR}/.git" ]; then
	git clone --branch "${PI_GEN_BRANCH}" https://github.com/RPi-Distro/pi-gen.git "${PI_GEN_DIR}"
fi
git -C "${PI_GEN_DIR}" fetch --quiet origin "${PI_GEN_BRANCH}"
git -C "${PI_GEN_DIR}" checkout --quiet "${PI_GEN_COMMIT}"

"${HERE}/prepare-pi-gen.sh" "${PI_GEN_DIR}" "${VERSION}" "${REF}"

(cd "${PI_GEN_DIR}" && ./build-docker.sh)

mkdir -p "${HERE}/deploy"
cp "${PI_GEN_DIR}"/deploy/VoiceSpeak-"${VERSION}"-arm64.img.xz "${HERE}/deploy/"
echo "Image: ${HERE}/deploy/VoiceSpeak-${VERSION}-arm64.img.xz"
