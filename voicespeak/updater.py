"""Self-update to the newest release tag (v*). Run by voicespeak-update.timer.

Rules:
- Only tagged releases, never untagged main.
- Never a downgrade: if the current checkout already contains the newest
  tag (e.g. a fresh install from main), nothing changes.
- Dependencies are reinstalled only when requirements.txt changed.
- One log line per run.

Runs as root (it restarts the service), but git and pip run as the owner of
the app directory so file ownership never changes.
"""

from __future__ import annotations

import hashlib
import os
import pwd
import re
import subprocess
from pathlib import Path

from . import config

_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def pick_latest_tag(tags: list[str]) -> str | None:
    """Newest vX.Y.Z by number (not text: v0.10.0 > v0.9.0). Others ignored."""
    best, best_key = None, None
    for tag in tags:
        m = _TAG.match(tag.strip())
        if not m:
            continue
        key = tuple(int(x) for x in m.groups())
        if best_key is None or key > best_key:
            best, best_key = tag.strip(), key
    return best


def needs_update(latest: str | None, current: str | None, contains_latest: bool) -> bool:
    if not latest:
        return False
    if current == latest:
        return False
    return not contains_latest


def _as_owner(app_dir: Path) -> list[str]:
    """Prefix to run a command as the app dir's owner when we are root."""
    if os.geteuid() != 0:
        return []
    owner = pwd.getpwuid(app_dir.stat().st_uid).pw_name
    return [] if owner == "root" else ["runuser", "-u", owner, "--"]


def _run(cmd: list[str], cwd: Path, timeout: float = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _req_hash(app_dir: Path) -> str:
    try:
        return hashlib.sha256((app_dir / "requirements.txt").read_bytes()).hexdigest()
    except OSError:
        return ""


def run_update(app_dir: Path = config.PACKAGE_DIR) -> int:
    pre = _as_owner(app_dir)
    git = [*pre, "git", "-C", str(app_dir)]
    try:
        fetch = _run([*git, "fetch", "--tags", "--force", "--quiet", "origin"], app_dir)
        if fetch.returncode != 0:
            print(f"Update: fetch failed ({fetch.stderr.strip()[-200:]})")
            return 1
        tags = _run([*git, "tag", "--list", "v*"], app_dir).stdout.split()
        latest = pick_latest_tag(tags)
        current = _run([*git, "describe", "--tags", "--exact-match"], app_dir).stdout.strip() or None
        contains = bool(latest) and _run(
            [*git, "merge-base", "--is-ancestor", latest, "HEAD"], app_dir,
        ).returncode == 0
        if not needs_update(latest, current, contains):
            print(f"Update: up to date ({current or 'untagged'}, newest release {latest or 'none'}).")
            return 0

        before = _req_hash(app_dir)
        checkout = _run([*git, "checkout", "--quiet", latest], app_dir)
        if checkout.returncode != 0:
            print(f"Update: checkout {latest} failed ({checkout.stderr.strip()[-200:]})")
            return 1
        pip_note = ""
        if _req_hash(app_dir) != before:
            pip = _run([*pre, "pip3", "install", "--quiet", "--break-system-packages",
                        "-r", str(app_dir / "requirements.txt")], app_dir, timeout=900)
            pip_note = ", dependencies updated" if pip.returncode == 0 else ", dependency install FAILED"
        try:
            ok = _run(["systemctl", "restart", "voicespeak.service"], app_dir).returncode == 0
        except OSError:
            ok = False
        restart = "service restarted" if ok else "restart FAILED, reboot to apply"
        print(f"Update: {current or 'untagged'} -> {latest}{pip_note}, {restart}.")
        return 0
    except (OSError, subprocess.SubprocessError) as e:
        print(f"Update: error ({e})")
        return 1
