"""Tests — guided setup «Benvenuto»: secrets into .env, container re-create, Telegram one-time code
(docs/work/2026-10-30-setup-un-click §4.2). No Docker, no network."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.setup import secrets
from app.setup.service import SetupService

pytestmark = pytest.mark.unit

TOKEN = "123456789:AAH" + "x" * 32


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "Hestia-Telegram/app").mkdir(parents=True)
    (tmp_path / "Hestia-Telegram/app/.env").write_text("# bot\nTELEGRAM_BOT_TOKEN=\nALLOWED_USER_ID=\nOTHER=keep me\n")
    (tmp_path / "Hestia-Oracle/app").mkdir(parents=True)
    (tmp_path / "Hestia-Oracle/app/.env").write_text("# ORACLE_KEY_GEMINI=\n")
    (tmp_path / ".env").write_text("HESTIA_DB_PASSWORD=abc\n")
    return tmp_path


def test_whitelist_refuses_other_keys():
    with pytest.raises(secrets.SecretRefused):
        secrets.target_for("HESTIA_DB_PASSWORD")
    with pytest.raises(secrets.SecretRefused):
        secrets.target_for("PATH")
    assert secrets.target_for("ORACLE_KEY_GEMINI").services == ("oracle",)


@pytest.mark.parametrize("key,value", [("ALLOWED_USER_ID", "abc"), ("TELEGRAM_BOT_TOKEN", "nope"),
                                       ("ORACLE_KEY_X", "two words"), ("ORACLE_KEY_X", "line\nbreak")])
def test_bad_values_refused(key, value):
    with pytest.raises(secrets.SecretRefused):
        secrets.validate(key, value)


def test_write_env_replaces_active_then_commented_then_appends(tmp_path):
    repo = _repo(tmp_path)
    secrets.set_secret(repo, "TELEGRAM_BOT_TOKEN", TOKEN)
    secrets.set_secret(repo, "ORACLE_KEY_GEMINI", "k1")
    secrets.set_secret(repo, "HESTIA_BACKUP_PASSPHRASE", "a-long-passphrase")
    tg = (repo / "Hestia-Telegram/app/.env").read_text()
    assert f"TELEGRAM_BOT_TOKEN={TOKEN}\n" in tg and "OTHER=keep me" in tg and tg.startswith("# bot\n")
    assert (repo / "Hestia-Oracle/app/.env").read_text() == "ORACLE_KEY_GEMINI=k1\n"
    assert (repo / ".env").read_text() == "HESTIA_DB_PASSWORD=abc\nHESTIA_BACKUP_PASSPHRASE=a-long-passphrase\n"
    assert secrets.is_set(repo, "TELEGRAM_BOT_TOKEN") and not secrets.is_set(repo, "ALLOWED_USER_ID")


def test_merged_env_updates_and_adds():
    assert secrets.merged_env(["A=1", "B=2"], {"A": "9", "C": "3"}) == ["A=9", "B=2", "C=3"]


def test_set_secrets_recreates_each_service_once_and_never_logs_values(tmp_path, caplog):
    calls = []
    service = SetupService(_repo(tmp_path), tmp_path / "data",
                           recreate=lambda svc, updates, **kw: calls.append((svc, dict(updates))) or (True, "ok"))
    with caplog.at_level(logging.INFO):
        out = service.set_secrets({"ORACLE_KEY_GEMINI": "secret-one", "ORACLE_KEY_DEEPSEEK": "secret-two"})
    assert calls == [("oracle", {"ORACLE_KEY_GEMINI": "secret-one", "ORACLE_KEY_DEEPSEEK": "secret-two"})]
    assert out["services"]["oracle"]["recreated"] is True
    assert "secret-one" not in caplog.text and "secret-two" not in caplog.text
    assert "secret" not in str(service.state())


def test_telegram_code_claim(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("app.setup.service.threading.Timer",
                        lambda delay, fn: type("T", (), {"start": lambda self: fn()})())
    service = SetupService(_repo(tmp_path), tmp_path / "data",
                           recreate=lambda svc, updates, **kw: calls.append((svc, updates)) or (True, "ok"))
    assert service.claim("123456", "42")["reason"] == "no_code"
    code = service.new_code()["code"]
    assert service.state()["telegram"]["code_active"]
    assert service.claim("000000" if code != "000000" else "111111", "42") == {"ok": False, "reason": "wrong_code"}
    assert service.claim(code, "42") == {"ok": True}
    assert calls == [("telegram", {"ALLOWED_USER_ID": "42"})]
    assert service.claim(code, "43")["reason"] == "no_code"   # one use only
    assert secrets.is_set(service.repo, "ALLOWED_USER_ID")


def test_code_burned_after_too_many_tries(tmp_path):
    service = SetupService(_repo(tmp_path), tmp_path / "data", recreate=lambda *a, **k: (True, "ok"))
    code = service.new_code()["code"]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        service.claim(wrong, "42")
    assert service.claim(code, "42")["reason"] == "no_code"


def test_state_later_and_complete(tmp_path):
    service = SetupService(_repo(tmp_path), tmp_path / "data")
    assert service.state()["completed"] is False
    assert service.mark("backup", later=True)["later"] == ["backup"]
    state = service.mark(completed=True)
    assert state["completed"] and state["later"] == ["backup"]


def test_hardware_from_installer_file(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".hestia-install").mkdir()
    (repo / ".hestia-install/hardware.json").write_text('{"os": "windows", "ram_gb": 64, "gpu": "RTX", "vram_gb": 16}')
    assert SetupService(repo, tmp_path / "data").hardware()["vram_gb"] == 16


def test_role_and_lan_ip_from_installer(tmp_path):
    (tmp_path / ".hestia-install").mkdir()
    (tmp_path / ".hestia-install" / "hardware.json").write_text(
        '{"role": "centrale", "lan_ip": "192.168.1.10", "ram_gb": 8}', encoding="utf-8")
    svc = SetupService(tmp_path, tmp_path / "data")
    assert svc.role() == "centrale"
    assert svc.hardware()["lan_ip"] == "192.168.1.10"
    assert SetupService(tmp_path / "none", tmp_path / "data").role() == "tutto"
