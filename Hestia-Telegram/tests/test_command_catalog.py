"""Tests — command catalog (Phase 2.2)

Validates the structure and contract of the local command catalog.
All tests are pure — no network, no bot, no Oracle.
"""
from __future__ import annotations

from typing import Any
import pytest

# conftest.py adds the Telegram app/ dir to sys.path
from command_catalog import telegram_local_commands

REQUIRED_FIELDS = {"command", "title", "description",
                   "method", "path", "clients", "response_mode"}
VALID_METHODS = {"GET", "POST", "DELETE", "PATCH", "PUT"}
VALID_RESPONSE_MODES = {"oracle_natural",
                        "direct", "raw_json", "text", "telegram_local"}


@pytest.mark.unit
class TestCommandCatalogStructure:
    @pytest.fixture(scope="class")
    def commands(self) -> list[dict[str, Any]]:
        return telegram_local_commands()

    def test_catalog_returns_non_empty_list(self, commands):
        assert isinstance(commands, list)
        assert len(commands) > 0

    def test_all_commands_have_required_fields(self, commands):
        for cmd in commands:
            missing = REQUIRED_FIELDS - set(cmd.keys())
            assert not missing, f"Command '{cmd.get('command')}' is missing fields: {missing}"

    def test_all_command_names_are_snake_case_lowercase(self, commands):
        for cmd in commands:
            name = cmd.get("command", "")
            assert name == name.lower(
            ), f"Command name not lowercase: {name!r}"
            assert " " not in name, f"Command name has spaces: {name!r}"

    def test_all_methods_are_valid_http_verbs(self, commands):
        for cmd in commands:
            method = cmd.get("method", "")
            assert method in VALID_METHODS, (
                f"Command '{cmd.get('command')}' has invalid method: {method!r}"
            )

    def test_all_response_modes_are_valid(self, commands):
        for cmd in commands:
            mode = cmd.get("response_mode", "")
            assert mode in VALID_RESPONSE_MODES, (
                f"Command '{cmd.get('command')}' has invalid response_mode: {mode!r}"
            )

    def test_all_paths_start_with_slash(self, commands):
        for cmd in commands:
            path = cmd.get("path", "")
            assert path.startswith("/"), (
                f"Command '{cmd.get('command')}' path does not start with /: {path!r}"
            )

    def test_all_clients_include_telegram(self, commands):
        for cmd in commands:
            clients = cmd.get("clients", [])
            assert "telegram" in clients, (
                f"Command '{cmd.get('command')}' missing 'telegram' in clients: {clients}"
            )

    def test_titles_are_non_empty_strings(self, commands):
        for cmd in commands:
            title = cmd.get("title", "")
            assert isinstance(title, str) and len(title.strip()) > 0, (
                f"Command '{cmd.get('command')}' has empty or invalid title"
            )

    def test_descriptions_are_non_empty_strings(self, commands):
        for cmd in commands:
            desc = cmd.get("description", "")
            assert isinstance(desc, str) and len(desc.strip()) > 0, (
                f"Command '{cmd.get('command')}' has empty description"
            )

    def test_no_duplicate_command_names(self, commands):
        names = [cmd.get("command") for cmd in commands]
        assert len(names) == len(set(
            names)), f"Duplicate command names found: {[n for n in names if names.count(n) > 1]}"

    def test_mandatory_commands_present(self, commands):
        """start, help, clear must always be in the local catalog."""
        names = {cmd.get("command") for cmd in commands}
        for required in ("start", "help", "clear"):
            assert required in names, f"Mandatory command '{required}' not in catalog"

    def test_telegram_local_response_mode_only_for_local_path(self, commands):
        """Commands with response_mode='telegram_local' must use /local/ paths."""
        for cmd in commands:
            if cmd.get("response_mode") == "telegram_local":
                path = cmd.get("path", "")
                assert "/local/" in path, (
                    f"Command '{cmd.get('command')}' has telegram_local mode but path is not /local/: {path!r}"
                )
