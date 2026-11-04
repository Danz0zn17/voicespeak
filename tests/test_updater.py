"""Signed-release self-update, against real local git repos. Run: python3 -m pytest -q"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from voicespeak import updater
from voicespeak.updater import has_signers, release_tags, signed_tag_name

pytestmark = pytest.mark.skipif(
    not (shutil.which("git") and shutil.which("ssh-keygen")), reason="needs git and ssh-keygen",
)

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


def sh(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, env=ENV, check=True, capture_output=True, text=True).stdout


def keygen(path: Path) -> str:
    sh("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", path.name, "-f", str(path))
    return path.with_suffix(".pub").read_text().strip()


def signers_line(pub: str) -> str:
    return f'release@voicespeak namespaces="git" {pub}\n'


def commit(repo: Path, msg: str, signers: str | None = None):
    if signers is not None:
        (repo / "config").mkdir(exist_ok=True)
        (repo / "config" / "release_signers").write_text(signers)
    (repo / "app.txt").write_text(msg)
    sh("git", "add", "-A", cwd=repo)
    sh("git", "commit", "-q", "-m", msg, cwd=repo)


def tag(repo: Path, name: str, key: Path | None = None, signed_as: str | None = None):
    if key is None:
        sh("git", "tag", "-a", name, "-m", name, cwd=repo)
        return
    sh("git", "-c", "gpg.format=ssh", "-c", f"user.signingkey={key}",
       "tag", "-s", signed_as or name, "-m", name, cwd=repo)
    if signed_as:  # publish the signed object under a different ref name
        sha = sh("git", "rev-parse", f"refs/tags/{signed_as}", cwd=repo).strip()
        sh("git", "update-ref", f"refs/tags/{name}", sha, cwd=repo)
        sh("git", "tag", "-d", signed_as, cwd=repo)


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    """An origin repo with signed v0.4.0 trusting `good`, and a box cloned at v0.4.0."""
    good, evil = tmp_path / "good", tmp_path / "evil"
    pub = keygen(good)
    keygen(evil)
    origin = tmp_path / "origin"
    origin.mkdir()
    sh("git", "init", "-q", "-b", "main", cwd=origin)
    commit(origin, "v0.4.0", signers=signers_line(pub))
    tag(origin, "v0.4.0", good)
    box = tmp_path / "box"
    sh("git", "clone", "-q", str(origin), str(box))
    sh("git", "checkout", "-q", "v0.4.0", cwd=box)
    restarts = []

    def fake_run(cmd, cwd, timeout=300):
        if cmd[0] == "systemctl":
            restarts.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=timeout)

    monkeypatch.setattr(updater, "_run", fake_run)
    return {"origin": origin, "box": box, "good": good, "evil": evil, "restarts": restarts}


def at(box: Path) -> str:
    return sh("git", "describe", "--tags", "--exact-match", cwd=box).strip()


def test_signed_release_is_applied(fleet, capsys):
    commit(fleet["origin"], "v0.5.0")
    tag(fleet["origin"], "v0.5.0", fleet["good"])
    assert updater.run_update(fleet["box"]) == 0
    assert at(fleet["box"]) == "v0.5.0"
    assert fleet["restarts"]
    assert "v0.4.0 -> v0.5.0 (signature ok)" in capsys.readouterr().out


def test_unsigned_tag_is_refused(fleet, capsys):
    commit(fleet["origin"], "evil")
    tag(fleet["origin"], "v0.5.0")
    assert updater.run_update(fleet["box"]) == 1
    assert at(fleet["box"]) == "v0.4.0" and not fleet["restarts"]
    assert "staying on v0.4.0; refused v0.5.0: v0.5.0 signature not valid" in capsys.readouterr().out


def test_lightweight_tag_is_refused(fleet, capsys):
    commit(fleet["origin"], "evil")
    sh("git", "tag", "v0.5.0", cwd=fleet["origin"])
    assert updater.run_update(fleet["box"]) == 1
    assert at(fleet["box"]) == "v0.4.0"
    assert "not an annotated, signed tag" in capsys.readouterr().out


def test_unknown_key_is_refused(fleet, capsys):
    commit(fleet["origin"], "evil")
    tag(fleet["origin"], "v0.5.0", fleet["evil"])
    assert updater.run_update(fleet["box"]) == 1
    assert at(fleet["box"]) == "v0.4.0" and not fleet["restarts"]
    assert "signature not valid" in capsys.readouterr().out


def test_attacker_cannot_trust_own_key_via_the_new_tag(fleet):
    # The new commit swaps in the attacker's key; only the box's current file counts.
    evil_pub = fleet["evil"].with_suffix(".pub").read_text().strip()
    commit(fleet["origin"], "evil", signers=signers_line(evil_pub))
    tag(fleet["origin"], "v0.5.0", fleet["evil"])
    assert updater.run_update(fleet["box"]) == 1
    assert at(fleet["box"]) == "v0.4.0"


def test_renamed_signed_tag_is_refused(fleet, capsys):
    # A genuinely signed v0.4.0 object republished as v9.9.9.
    sha = sh("git", "rev-parse", "refs/tags/v0.4.0", cwd=fleet["origin"]).strip()
    sh("git", "update-ref", "refs/tags/v9.9.9", sha, cwd=fleet["origin"])
    commit(fleet["origin"], "v0.5.0")
    tag(fleet["origin"], "v0.5.0", fleet["good"])
    # v9.9.9 is refused and cannot freeze updates; v0.5.0 still applies.
    assert updater.run_update(fleet["box"]) == 0
    assert at(fleet["box"]) == "v0.5.0"
    assert "v9.9.9: v9.9.9 was signed as v0.4.0" in capsys.readouterr().out


def test_renamed_tag_on_new_commit_is_refused(fleet, capsys):
    commit(fleet["origin"], "v0.5.0")
    tag(fleet["origin"], "v0.6.0", fleet["good"], signed_as="v0.5.0")
    assert updater.run_update(fleet["box"]) == 1
    assert at(fleet["box"]) == "v0.4.0"
    assert "signed as v0.5.0" in capsys.readouterr().out


def test_bad_newest_tag_does_not_block_a_good_one(fleet, capsys):
    commit(fleet["origin"], "v0.5.0")
    tag(fleet["origin"], "v0.5.0", fleet["good"])
    commit(fleet["origin"], "evil")
    tag(fleet["origin"], "v9.0.0")  # unsigned junk on top
    assert updater.run_update(fleet["box"]) == 0
    assert at(fleet["box"]) == "v0.5.0"
    assert "refused v9.0.0" in capsys.readouterr().out


def test_empty_signers_file_refuses_everything(fleet, capsys):
    (fleet["box"] / "config" / "release_signers").write_text("# no keys yet\n")
    commit(fleet["origin"], "v0.5.0")
    tag(fleet["origin"], "v0.5.0", fleet["good"])
    assert updater.run_update(fleet["box"]) == 1
    assert "no release signing key" in capsys.readouterr().out


def test_up_to_date_is_quiet_success(fleet, capsys):
    assert updater.run_update(fleet["box"]) == 0
    assert "up to date (v0.4.0" in capsys.readouterr().out


# ---- pure helpers

def test_release_tags_newest_first():
    assert release_tags(["v0.9.0", "v0.10.0", "x", "v1.0", "v0.3.1"]) == ["v0.10.0", "v0.9.0", "v0.3.1"]


def test_signed_tag_name_reads_header_only():
    obj = "object abc\ntype commit\ntag v1.2.3\ntagger t\n\ntag v9.9.9 in the message\n"
    assert signed_tag_name(obj) == "v1.2.3"
    assert signed_tag_name("object abc\n\ntag v1\n") is None


def test_has_signers(tmp_path):
    f = tmp_path / "s"
    assert not has_signers(f)
    f.write_text("# only comments\n\n")
    assert not has_signers(f)
    f.write_text('a namespaces="git" ssh-ed25519 AAAA\n')
    assert has_signers(f)


def test_repo_ships_signers_file():
    assert (updater.config.PACKAGE_DIR / updater.SIGNERS_FILE).exists()
