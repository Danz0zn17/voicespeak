"""Self-update to the newest release tag (v*). Run by voicespeak-update.timer.

Rules:
- Only tagged releases, never untagged main.
- Never a downgrade: if the current checkout already contains the newest
  tag (e.g. a fresh install from main), nothing changes.
- Only signed releases: the tag must be an annotated tag signed by a key in
  config/release_signers (SSH allowed_signers format) of the CURRENT
  checkout, and its signed name must match the tag name. Unsigned,
  unknown-key or renamed tags are refused, and an empty or missing signers
  file refuses every update (fail closed). A new key only takes effect after
  a release signed by an existing key ships it.
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
_SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

SIGNERS_FILE = "config/release_signers"
MAX_CANDIDATES = 5  # newest tags tried per run, so junk tags cannot cost unbounded work


def release_tags(tags: list[str]) -> list[str]:
    """vX.Y.Z tags newest first, by number (not text: v0.10.0 > v0.9.0). Others ignored."""
    found = {}
    for tag in tags:
        m = _TAG.match(tag.strip())
        if m:
            found[tag.strip()] = tuple(int(x) for x in m.groups())
    return sorted(found, key=found.get, reverse=True)


def pick_latest_tag(tags: list[str]) -> str | None:
    ordered = release_tags(tags)
    return ordered[0] if ordered else None


def needs_update(latest: str | None, current: str | None, contains_latest: bool) -> bool:
    if not latest:
        return False
    if current == latest:
        return False
    return not contains_latest


def has_signers(path: Path) -> bool:
    """True if the allowed_signers file has at least one key line."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return False
    return any(line.strip() and not line.lstrip().startswith("#") for line in lines)


def signed_tag_name(tag_object: str) -> str | None:
    """The name recorded inside an annotated tag object (`git cat-file tag`)."""
    for line in tag_object.splitlines():
        if not line:
            break  # end of headers
        if line.startswith("tag "):
            return line[4:].strip()
    return None


def verify_release(git: list[str], app_dir: Path, tag: str, signers: Path) -> tuple[str | None, str]:
    """Check `tag` is a signed release. Returns (commit sha, "") or (None, reason)."""
    if not has_signers(signers):
        return None, f"no release signing key in {SIGNERS_FILE}"
    if _run([*git, "cat-file", "-t", f"refs/tags/{tag}"], app_dir).stdout.strip() != "tag":
        return None, f"{tag} is not an annotated, signed tag"
    name = signed_tag_name(_run([*git, "cat-file", "tag", f"refs/tags/{tag}"], app_dir).stdout)
    if name != tag:
        return None, f"{tag} was signed as {name or 'nothing'}"
    verify = _run([
        *git, "-c", "gpg.format=ssh", "-c", f"gpg.ssh.allowedSignersFile={signers}",
        "verify-tag", f"refs/tags/{tag}",
    ], app_dir)
    if verify.returncode != 0:
        return None, f"{tag} signature not valid ({verify.stderr.strip()[-200:]})"
    sha = _run([*git, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"], app_dir).stdout.strip()
    if not _SHA.match(sha):
        return None, f"{tag} does not point at a commit"
    return sha, ""


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
        tags = release_tags(_run([*git, "tag", "--list", "v*"], app_dir).stdout.split())
        current = _run([*git, "describe", "--tags", "--exact-match"], app_dir).stdout.strip() or None
        # Newest first. Tags that fail verification are skipped, so a bad tag can
        # neither run nor freeze updates; the newest good one decides.
        latest, refused = None, []
        for tag in tags[:MAX_CANDIDATES]:
            sha, reason = verify_release(git, app_dir, tag, app_dir / SIGNERS_FILE)
            if not sha:
                refused.append(f"{tag}: {reason}")
                continue
            contains = _run([*git, "merge-base", "--is-ancestor", sha, "HEAD"], app_dir).returncode == 0
            if needs_update(tag, current, contains):
                latest = tag
            break
        note = f"; refused {'; '.join(refused)}" if refused else ""
        if refused and not latest:
            print(f"Update: staying on {current or 'untagged'}{note}.")
            return 1
        if not latest:
            print(f"Update: up to date ({current or 'untagged'}, newest release {tags[0] if tags else 'none'}).")
            return 0

        before = _req_hash(app_dir)
        # Check out the verified commit, not the tag name, so the ref cannot move in between.
        checkout = _run([*git, "checkout", "--quiet", "--detach", sha], app_dir)
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
        print(f"Update: {current or 'untagged'} -> {latest} (signature ok){pip_note}, {restart}{note}.")
        return 0
    except (OSError, subprocess.SubprocessError) as e:
        print(f"Update: error ({e})")
        return 1
