"""Tests — command execution and router utilities (Phase 2.4)

Tests for router helpers (parse_command_arguments, extract_required_args,
resolve_template, route_service_command) and executor utilities.
All mocked — no network, no bot API.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# parse_command_arguments
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestParseCommandArguments:
    def test_single_key_value(self):
        from telegram_bot.services.router import parse_command_arguments
        result = parse_command_arguments("city=Milano")
        assert result == {"city": "Milano"}

    def test_multiple_key_values(self):
        from telegram_bot.services.router import parse_command_arguments
        result = parse_command_arguments("city=Milano price_max=300000")
        assert result["city"] == "Milano"
        assert result["price_max"] == 300000  # digit → int

    def test_numeric_value_parsed_as_int(self):
        from telegram_bot.services.router import parse_command_arguments
        result = parse_command_arguments("limit=10")
        assert result["limit"] == 10
        assert isinstance(result["limit"], int)

    def test_empty_string_returns_empty_dict(self):
        from telegram_bot.services.router import parse_command_arguments
        assert parse_command_arguments("") == {}

    def test_no_equals_sign_token_ignored(self):
        from telegram_bot.services.router import parse_command_arguments
        result = parse_command_arguments("random_token another")
        assert result == {}

    def test_key_lowercased(self):
        from telegram_bot.services.router import parse_command_arguments
        result = parse_command_arguments("City=Roma")
        assert "city" in result


# ─────────────────────────────────────────────────────────────────────────────
# extract_required_args
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestExtractRequiredArgs:
    def test_single_arg_extracted(self):
        from telegram_bot.services.router import extract_required_args
        result = extract_required_args("id=<id>")
        assert "id" in result

    def test_multiple_args_extracted(self):
        from telegram_bot.services.router import extract_required_args
        result = extract_required_args("city=<city> price_max=<price_max>")
        assert "city" in result
        assert "price_max" in result

    def test_empty_string_returns_empty_list(self):
        from telegram_bot.services.router import extract_required_args
        assert extract_required_args("") == []

    def test_args_all_lowercased(self):
        from telegram_bot.services.router import extract_required_args
        result = extract_required_args("City=<City>")
        assert "city" in result


# ─────────────────────────────────────────────────────────────────────────────
# resolve_template
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestResolveTemplate:
    def test_session_id_placeholder_replaced(self):
        from telegram_bot.services.router import resolve_template
        result = resolve_template("$session_id", "sess-abc", 123, {})
        assert result == "sess-abc"

    def test_chat_id_placeholder_replaced(self):
        from telegram_bot.services.router import resolve_template
        result = resolve_template("$chat_id", "sess", 456, {})
        assert result == "456"

    def test_arg_placeholder_replaced(self):
        from telegram_bot.services.router import resolve_template
        result = resolve_template("$arg.city", "sess", 1, {"city": "Roma"})
        assert result == "Roma"

    def test_nested_dict_resolved_recursively(self):
        from telegram_bot.services.router import resolve_template
        template = {"session": "$session_id", "data": {"chat": "$chat_id"}}
        result = resolve_template(template, "my-session", 789, {})
        assert result["session"] == "my-session"
        assert result["data"]["chat"] == "789"

    def test_inline_placeholder_in_string_substituted(self):
        from telegram_bot.services.router import resolve_template
        result = resolve_template(
            "User $session_id from $chat_id", "s1", 42, {})
        assert "s1" in result
        assert "42" in result

    def test_missing_arg_placeholder_omitted_from_dict(self):
        from telegram_bot.services.router import resolve_template
        template = {"city": "$arg.city"}  # city not provided in args
        result = resolve_template(template, "s", 1, {})
        # Missing $arg.* values should be omitted from the output dict
        assert "city" not in result

    def test_plain_string_unchanged(self):
        from telegram_bot.services.router import resolve_template
        result = resolve_template("hello world", "s", 1, {})
        assert result == "hello world"


# ─────────────────────────────────────────────────────────────────────────────
# route_service_command — GET command via Hub routing
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestRouteServiceCommand:
    def test_get_command_calls_hub_route(self, monkeypatch):
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "status_code": 200, "payload": {"result": "ok"}}
        monkeypatch.setattr("requests.get", lambda *a, **kw: fake_resp)
        monkeypatch.setattr("requests.post", lambda *a, **kw: fake_resp)

        from telegram_bot.services.router import route_service_command
        ok, result = route_service_command(
            service="dummy",
            path="/api/meteo",
            method="GET",
            query={},
            body={},
        )
        assert ok is True

    def test_non_200_response_signals_failure(self, monkeypatch):
        fake_resp = MagicMock()
        fake_resp.status_code = 500
        fake_resp.json.return_value = {"error": "server error"}
        fake_resp.text = "Internal Server Error"
        monkeypatch.setattr("requests.get", lambda *a, **kw: fake_resp)
        monkeypatch.setattr("requests.post", lambda *a, **kw: fake_resp)

        from telegram_bot.services.router import route_service_command
        ok, result = route_service_command(
            service="dummy",
            path="/api/bad",
            method="GET",
            query={},
            body={},
        )
        assert ok is False

    def test_network_error_handled_gracefully(self, monkeypatch):
        monkeypatch.setattr("requests.get", lambda *a, **
                            kw: (_ for _ in ()).throw(ConnectionError("timeout")))
        monkeypatch.setattr("requests.post", lambda *a, **
                            kw: (_ for _ in ()).throw(ConnectionError("timeout")))

        from telegram_bot.services.router import route_service_command
        ok, result = route_service_command(
            service="dummy",
            path="/api/unreachable",
            method="GET",
            query={},
            body={},
        )
        assert ok is False


# ─────────────────────────────────────────────────────────────────────────────
# execute_direct_command
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestExecuteDirectCommand:
    def test_direct_command_formats_with_oracle_for_oracle_natural(self, fake_message, monkeypatch):
        import telegram_bot.core as core_module
        core_module.ALLOWED_USER_ID = ""
        mock_bot = MagicMock()
        core_module.bot = mock_bot

        command_metadata = {
            "command": "meteo",
            "title": "🌤 Meteo",
            "method": "GET",
            "path": "/api/meteo",
            "response_mode": "oracle_natural",
            "service": "dummy",
        }
        # Pre-populate the registry so execute_direct_command can find the command
        with core_module.COMMAND_REGISTRY_LOCK:
            core_module.COMMAND_REGISTRY["meteo"] = command_metadata

        # Hub route returns envelope with 200 + payload; Oracle format also returns 200
        fake_hub_resp = MagicMock()
        fake_hub_resp.status_code = 200
        fake_hub_resp.json.return_value = {
            "status_code": 200, "payload": {"temp": "22°C"}}

        monkeypatch.setattr("requests.post", lambda *a, **kw: fake_hub_resp)
        monkeypatch.setattr("requests.get", lambda *a, **kw: fake_hub_resp)

        from telegram_bot.services.executor import execute_direct_command
        execute_direct_command("meteo", 12345, "")
        # Bot should have sent at least one message
        assert mock_bot.send_message.called or mock_bot.reply_to.called


@pytest.mark.unit
class TestSendUserMessageFallback:
    def test_html_parse_error_retries_as_plain_text(self):
        import telegram_bot.core as core_module

        mock_bot = MagicMock()
        mock_bot.send_message.side_effect = [
            Exception("Bad Request: can't parse entities: Unmatched end tag"),
            None,
        ]
        core_module.bot = mock_bot

        core_module.send_user_message(
            12345,
            "<i>Preferenze</em>",
            parse_mode="HTML",
        )

        assert mock_bot.send_message.call_count == 2
        _, first_kwargs = mock_bot.send_message.call_args_list[0]
        _, second_kwargs = mock_bot.send_message.call_args_list[1]
        assert first_kwargs.get("parse_mode") == "HTML"
        assert "parse_mode" not in second_kwargs

    def test_non_parse_error_is_not_silenced(self):
        import telegram_bot.core as core_module

        mock_bot = MagicMock()
        mock_bot.send_message.side_effect = Exception("network down")
        core_module.bot = mock_bot

        with pytest.raises(Exception, match="network down"):
            core_module.send_user_message(
                12345,
                "<b>ciao</b>",
                parse_mode="HTML",
            )


@pytest.mark.unit
class TestCommandDeliverySafetyCoverage:
    @pytest.mark.parametrize(
        "command_name,response_mode",
        [
            ("preferenze_attive", "oracle_natural"),
            ("notifiche_attive", "direct"),
            ("avvisi_recenti", "direct"),
            ("scout_listings", "direct"),
            ("meteo", "oracle_natural"),
        ],
    )
    def test_execute_direct_command_html_parse_error_falls_back(
        self,
        command_name,
        response_mode,
        monkeypatch,
    ):
        import telegram_bot.core as core_module
        from telegram_bot.services import executor

        core_module.ALLOWED_USER_ID = ""
        core_module.LOCAL_COMMANDS = {}

        with core_module.COMMAND_REGISTRY_LOCK:
            core_module.COMMAND_REGISTRY[command_name] = {
                "command": command_name,
                "title": "",
                "method": "GET",
                "path": f"/api/{command_name}",
                "response_mode": response_mode,
                "service": "dummy",
            }

        mock_bot = MagicMock()
        mock_bot.send_message.side_effect = [
            Exception("Bad Request: can't parse entities: Unmatched end tag"),
            None,
        ]
        core_module.bot = mock_bot

        monkeypatch.setattr(
            executor,
            "route_command_from_metadata",
            lambda command, chat_id, parsed_args: (True, {"ok": True}),
        )
        monkeypatch.setattr(
            executor,
            "render_direct_command_output",
            lambda *args, **kwargs: ("<i>output</em>", "HTML"),
        )

        executor.execute_direct_command(command_name, 12345, "")

        assert mock_bot.send_message.call_count == 2
        _, first_kwargs = mock_bot.send_message.call_args_list[0]
        _, second_kwargs = mock_bot.send_message.call_args_list[1]
        assert first_kwargs.get("parse_mode") == "HTML"
        assert "parse_mode" not in second_kwargs
