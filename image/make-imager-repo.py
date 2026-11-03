#!/usr/bin/env python3
"""Write the Raspberry Pi Imager repository file for a built VoiceSpeak image.

Imager reads this to show "VoiceSpeak" in its OS list and, because of
init_format "systemd", to offer its customisation screen (Wi-Fi, username,
password, SSH) for our image. Format: rpi-imager doc/json-schema/os-list-schema.json.

Usage:
  make-imager-repo.py IMAGE.img.xz --version v1.0.0 --url URL_OF_IMAGE > voicespeak-imager.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import lzma
import os
import sys

CHUNK = 4 * 1024 * 1024


def measure(path: str) -> dict[str, object]:
    download = hashlib.sha256()
    extract = hashlib.sha256()
    extract_size = 0
    decompressor = lzma.LZMADecompressor()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            download.update(chunk)
            data = decompressor.decompress(chunk)
            extract.update(data)
            extract_size += len(data)
    return {
        "image_download_size": os.path.getsize(path),
        "image_download_sha256": download.hexdigest(),
        "extract_size": extract_size,
        "extract_sha256": extract.hexdigest(),
    }


def entry(image: str, version: str, url: str) -> dict[str, object]:
    return {
        "name": f"VoiceSpeak {version}",
        "description": "Talking communication device for people with cerebral palsy. Raspberry Pi Zero 2 W or Pi 4.",
        "url": url,
        "icon": "https://voice-pad-web.netlify.app/icon-192.png",
        "website": "https://voice-pad-web.netlify.app",
        "release_date": dt.date.today().isoformat(),
        **measure(image),
        # Imager device tags: Zero 2 W shares the "pi3-64bit" tag with the Pi 3
        "devices": ["pi4-64bit", "pi3-64bit"],
        # Bookworm-based images are customised with firstrun.sh (systemd format)
        "init_format": "systemd",
        "architecture": "armv8",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", help="path to VoiceSpeak-<version>-arm64.img.xz")
    parser.add_argument("--version", required=True)
    parser.add_argument("--url", required=True, help="public download URL of the image")
    args = parser.parse_args()
    json.dump({"os_list": [entry(args.image, args.version, args.url)]}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
