"""Tests — «Aggiorna Hestia» (docs/work/2026-10-30-setup-un-click §4.4): versions from git tags, what's new from the
CHANGELOG, apply with health check and automatic way back. Real git in a temp dir, fake Docker, no network."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.setup import updater as up

pytestmark = pytest.mark.unit


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(repo: Path, files: dict[str, str], msg: str, tag: str = "") -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    sh(repo, "add", "-A")
    sh(repo, "commit", "-qm", msg)
    if tag:
        sh(repo, "tag", tag)


@pytest.fixture
def repos(tmp_path):
    """origin (with v1.0.0 and v1.1.0) and the install, a clone checked out at v1.0.0."""
    origin = tmp_path / "origin"
    origin.mkdir()
    sh(origin, "init", "-q", "-b", "main")
    commit(origin, {"CHANGELOG.md": "# CHANGELOG\n\n## 2026-11-01\n- First → `docs/work/a/` [ext-chat]\n",
                    "Hestia-Oracle/app/main.py": "v1\n", "Hestia-Hub/src/main.py": "v1\n"}, "one", "v1.0.0")
    commit(origin, {"CHANGELOG.md": "# CHANGELOG\n\n## 2026-11-05\n- Voice is faster → `docs/work/b/` [ext-chat]\n"
                                    "\n## 2026-11-01\n- First → `docs/work/a/` [ext-chat]\n",
                    "Hestia-Oracle/app/main.py": "v2\n"}, "two", "v1.1.0")
    install = tmp_path / "install"
    sh(tmp_path, "clone", "-q", str(origin), str(install))
    sh(install, "-c", "advice.detachedHead=false", "checkout", "-q", "v1.0.0")
    return origin, install


class FakeBox:
    def __init__(self, name):
        self.name = name
        self.restarts = 0

    def restart(self, timeout=30):
        self.restarts += 1


class FakeDocker:
    def __init__(self, names):
        self.boxes = {f"hestia_{n}": FakeBox(f"hestia_{n}") for n in names}
        self.containers = self

    def list(self, filters=None):
        return list(self.boxes.values())

    def get(self, name):
        return self.boxes[name]


def make(install, tmp_path, *, channel="stabile", unhealthy=None, docker=None, notes=None):
    sent = notes if notes is not None else []
    return up.Updater(install, tmp_path / "data", channel=lambda: channel, notify=sent.append,
                      unhealthy=unhealthy or (lambda s: []), docker_client=lambda: docker)


def test_check_finds_newer_tag_with_plain_notes_and_asks_once(repos, tmp_path):
    _, install = repos
    sent = []
    u = make(install, tmp_path, notes=sent)
    assert u.installed()["label"] == "1.0.0"
    data = u.check(notify=True)
    assert data["available"]["label"] == "1.1.0" and data["available"]["notes"] == ["Voice is faster"]
    assert sent and sent[0]["question"]["path"] == up.ANSWER_PATH and "1.1.0" in sent[0]["text"]
    u.check(notify=True)
    assert len(sent) == 1                                   # the same version is asked once


def test_apply_restarts_only_running_touched_services_then_records(repos, tmp_path):
    _, install = repos
    dock = FakeDocker(["oracle", "hub"])
    u = make(install, tmp_path, docker=dock)
    u.check()
    u.apply()
    u._thread.join(10)
    st = u.status()
    assert st["installed"]["label"] == "1.1.0" and st["job"]["state"] == "fatto"
    assert dock.boxes["hestia_oracle"].restarts == 1 and dock.boxes["hestia_hub"].restarts == 0
    assert st["history"][-1]["ok"] and st["previous"]
    assert st["available"] is None


def test_unhealthy_goes_back_to_previous_version(repos, tmp_path):
    _, install = repos
    dock = FakeDocker(["oracle"])
    sent = []
    u = make(install, tmp_path, docker=dock, unhealthy=lambda s: ["oracle"], notes=sent)
    u.check()
    u.apply()
    u._thread.join(10)
    st = u.status()
    assert st["installed"]["label"] == "1.0.0" and st["job"]["state"] == "errore"
    assert dock.boxes["hestia_oracle"].restarts == 2          # once for the update, once for the way back
    assert "1.0.0" in sent[-1]["text"]


def test_local_changes_block_the_update(repos, tmp_path):
    _, install = repos
    (install / "Hestia-Oracle/app/main.py").write_text("mine\n")
    u = make(install, tmp_path)
    u.check()
    assert "modifiche locali" in u.blocked()
    with pytest.raises(up.UpdateRefused):
        u.apply()


def test_novita_follows_main_and_refuses_local_commits(repos, tmp_path):
    origin, install = repos
    sh(install, "checkout", "-q", "main")
    commit(origin, {"Hestia-Hub/src/main.py": "v3\n"}, "three")
    u = make(install, tmp_path, channel="novita")
    assert u.check()["available"]["commits"] == 1
    commit(install, {"local.txt": "forge\n"}, "forge work")
    assert "non sono su GitHub" in u.blocked()


def test_compose_build_read_without_yaml(tmp_path):
    (tmp_path / "docker-compose.global.yml").write_text(
        "services:\n  oracle:\n    build:\n      context: .\n      dockerfile: Hestia-Oracle/Dockerfile\n"
        "    container_name: hestia_oracle\n  db:\n    image: postgres\n")
    assert up._compose_build(tmp_path, "oracle") == (".", "Hestia-Oracle/Dockerfile")
    assert up._compose_build(tmp_path, "db") is None


def test_notes_in_italian_once_and_english_when_the_brain_is_off(repos, tmp_path):
    _, install = repos
    calls = []
    u = make(install, tmp_path)
    u.translate = lambda notes: calls.append(notes) or ["La voce è più veloce"]
    assert u.check()["available"]["notes"] == ["La voce è più veloce"]
    assert u.check()["available"]["notes"] == ["La voce è più veloce"] and len(calls) == 1
    off = make(install, tmp_path / "other")
    off.translate = lambda notes: (_ for _ in ()).throw(OSError("brain off"))
    assert off.check()["available"]["notes"] == ["Voice is faster"]
