"""Oracle central settings: declared keys/defaults (former env vars) and live reads."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.services import oracle_settings as o

# Former env var → (setting key, default). Defaults = the old env defaults.
EXPECTED = {
    "ORACLE_MAX_AGENT_TURNS": ("oracle.agent.max_turns", 25),
    "ORACLE_MAX_AGENT_TOKENS": ("oracle.agent.max_tokens", 0),
    "ORACLE_TOOL_RESULT_MAX_CHARS": ("oracle.agent.tool_result_max_chars", 2000),
    "ORACLE_AGENT_EARLY_EXIT_NO_TOOL_TURNS": ("oracle.agent.early_exit_no_tool_turns", 2),
    "ORACLE_MAX_PARALLEL_TOOLS": ("oracle.agent.max_parallel_tools", 8),
    "ORACLE_HISTORY_LIMIT": ("oracle.context.history_messages", 6),
    "ORACLE_HISTORY_CHAR_LIMIT": ("oracle.context.history_message_chars", 500),
    "ORACLE_CONTEXT_ENTITIES_LIMIT": ("oracle.context.entities", 12),
    "ORACLE_CONTEXT_FIELD_CHAR_LIMIT": ("oracle.context.entity_field_chars", 280),
    "ORACLE_COMPACT_TRIGGER_MSGS": ("oracle.context.compact_trigger_messages", 20),
    "ORACLE_COMPACT_KEEP_RECENT": ("oracle.context.compact_keep_recent", 6),
    "ORACLE_TEMPORAL_CALENDAR_ENABLED": ("oracle.context.today_agenda", True),
    "ORACLE_POLICY_FOREGROUND_CHAT_TIMEOUT_SEC": ("oracle.timeouts.foreground_chat", 8),
    "ORACLE_POLICY_ACTION_SELECTION_TIMEOUT_SEC": ("oracle.timeouts.action_selection", 12),
    "ORACLE_POLICY_ACTION_SERVICE_ROUTE_TIMEOUT_SEC": ("oracle.timeouts.action_service_route", 25),
    "ORACLE_POLICY_MEMORY_EXTRACTION_TIMEOUT_SEC": ("oracle.timeouts.memory_extraction", 10),
    "ORACLE_POLICY_BACKGROUND_COMPACTION_TIMEOUT_SEC": ("oracle.timeouts.background_compaction", 8),
    "ORACLE_POLICY_NOTIFICATION_FORMATTING_TIMEOUT_SEC": ("oracle.timeouts.notification_formatting", 12),
    "ORACLE_LLM_CHAT_TIMEOUT_SEC": ("oracle.timeouts.gateway_chat", 600),
    "LLM_MAX_RETRIES": ("oracle.provider.retries", 3),
    "LLM_RETRY_BASE_DELAY_SEC": ("oracle.provider.retry_delay", 1.0),
    "OLLAMA_TIMEOUT_SEC": ("oracle.provider.ollama.timeout", 120),
    "OLLAMA_EMBED_TIMEOUT_SEC": ("oracle.provider.ollama.embed_timeout", 60),
    "OLLAMA_TOOL_CALL_MODE": ("oracle.provider.ollama.tool_call_mode", "auto"),
    "ORACLE_MEMORY_NOTICE_WAIT_SECONDS": ("oracle.memory.notice_wait", 8.0),
    "ORACLE_PREF_DOMAIN_SIM_THRESHOLD": ("oracle.memory.domain_threshold", 0.55),
    "ORACLE_FORCE_TELEGRAM_TARGET": ("oracle.memory.force_owner_target", True),
    "ORACLE_HIGH_IMPACT_APPROVAL_ENABLED": ("oracle.approval.enabled", True),
    "ORACLE_HIGH_IMPACT_APPROVAL_TTL_SECONDS": ("oracle.approval.ttl", 600),
    "ORACLE_HIGH_IMPACT_APPROVAL_BULK_MIN_COUNT": ("oracle.approval.bulk_min_count", 2),
    "ORACLE_HIGH_IMPACT_APPROVAL_METHODS": ("oracle.approval.methods", ["DELETE", "PUT", "PATCH"]),
    "ORACLE_HIGH_IMPACT_APPROVAL_COMMANDS": ("oracle.approval.commands", []),
    "ORACLE_ATHENA_HINTS_ENABLED": ("oracle.hints.enabled", True),
    "ORACLE_ATHENA_HINTS_TTL_SECONDS": ("oracle.hints.ttl", 7200),
    "ORACLE_ATHENA_HINTS_MAX": ("oracle.hints.max", 300),
    "ORACLE_SCHEMAS_CACHE_TTL_SECONDS": ("oracle.cache.schemas_ttl", 30),
    "MODULE_TOOL_REGISTRY_TTL_SECONDS": ("oracle.cache.tool_registry_ttl", 120),
    "ORACLE_TASK_STORE_MAX": ("oracle.tasks.max_kept", 500),
    "DOC_MAX_ARCHIVE_BYTES": ("oracle.documents.max_archive_mb", 10),
    "DOC_SEARCH_THRESHOLD": ("oracle.documents.search_threshold", 1.2),
    "WHISPER_MODEL": ("oracle.documents.whisper_model", "base"),
    "ORACLE_AUDIO_MODEL_PREFIXES": ("oracle.documents.audio_models", ["gemini-1.5", "gemini-2"]),
    "ORACLE_PROMPT_AB_ALERT_ENABLED": ("oracle.prompt_ab.alert.enabled", False),
    "ORACLE_PROMPT_AB_ALERT_VARIANTS": ("oracle.prompt_ab.alert.variants", ["control", "experimental"]),
    "ORACLE_PROMPT_AB_ALERT_DEFAULT": ("oracle.prompt_ab.alert.default", "control"),
    "ORACLE_PROMPT_AB_ALERT_FORCE": ("oracle.prompt_ab.alert.force", ""),
    "ORACLE_PROMPT_AB_PLANNER_ENABLED": ("oracle.prompt_ab.planner.enabled", False),
    "ORACLE_PROMPT_AB_PLANNER_VARIANTS": ("oracle.prompt_ab.planner.variants", ["control", "experimental"]),
    "ORACLE_PROMPT_AB_PLANNER_DEFAULT": ("oracle.prompt_ab.planner.default", "control"),
    "ORACLE_PROMPT_AB_PLANNER_FORCE": ("oracle.prompt_ab.planner.force", ""),
}


@pytest.mark.unit
class TestDeclaredSettings:
    @pytest.mark.parametrize("env_name", sorted(EXPECTED))
    def test_key_declared_with_old_default(self, env_name):
        key, default = EXPECTED[env_name]
        assert key in o.settings._defs, key
        assert o.settings._defs[key]["default"] == default
        assert o.settings._defs[key]["apply"] == "live"

    def test_list_and_object_defaults(self):
        assert "gemma4" in o.settings._defs[o.THINKING_FAMILIES]["default"]
        assert "llava" in o.settings._defs[o.VISION_MODELS]["default"]
        assert {"general", "food", "finance"} <= set(o.settings._defs[o.PREFERENCE_DOMAINS]["default"])

    def test_approval_gate_is_read_only_for_the_assistant(self):
        for k in (o.APPROVAL_ENABLED, o.APPROVAL_TTL, o.APPROVAL_BULK_MIN, o.APPROVAL_METHODS, o.APPROVAL_COMMANDS):
            assert o.settings._defs[k]["oracle"] == "read"

    def test_removed_env_vars_are_no_longer_read(self):
        app = Path(__file__).resolve().parents[1] / "app"
        source = "\n".join(p.read_text(encoding="utf-8") for p in app.rglob("*.py"))
        for env_name in list(EXPECTED) + ["ORACLE_TIMEZONE", "HESTIA_PERSONA", "ORACLE_AGENT_ACTION_TOOL_POLICY",
                                          "ORACLE_THINKING_FAMILIES", "ORACLE_VISION_MODEL_PREFIXES",
                                          "ORACLE_PREFERENCE_DOMAINS", "ORACLE_GEMINI_", "ORACLE_PROMPT_AB_SALT",
                                          "ORACLE_PROMPT_DYNAMIC_BOUNDARY", "ORACLE_DOMAINS_CACHE_TTL_SECONDS"]:
            assert f'"{env_name}' not in source, env_name


@pytest.mark.unit
class TestLiveReads:
    def test_typed_readers_fall_back_on_bad_values(self, monkeypatch):
        monkeypatch.setitem(o.settings._effective, o.MAX_TURNS, "nope")
        assert o.get_int(o.MAX_TURNS) == 25
        monkeypatch.setitem(o.settings._effective, o.APPROVAL_METHODS, "delete, put")
        assert o.get_list(o.APPROVAL_METHODS, upper=True) == ["DELETE", "PUT"]

    def test_timeout_by_source(self, monkeypatch):
        monkeypatch.setitem(o.settings._effective, "oracle.timeouts.action_selection", 40)
        assert o.timeout("action_selection", 5) == 40
        assert o.timeout("unknown_source", 5) == 5

    def test_prompt_ab_reads_settings(self, monkeypatch):
        from core.services import prompt_config
        monkeypatch.setitem(o.settings._effective, "oracle.prompt_ab.alert.force", "experimental")
        assert prompt_config.select_variant("alert_formatter", seed="x") == "experimental"

    def test_models_are_three_objects_and_the_rest_is_advanced(self):
        visible = [k for k, d in o.settings._defs.items() if not d["advanced"] and d["scope"] == "system"]
        assert sorted(visible) == sorted([o.PROVIDERS_KEY, o.CHAINS_KEY, o.USECASES_KEY])
        assert not any(k.startswith("oracle.models.") for k in o.settings._defs)

    def test_vision_prefixes_live(self, monkeypatch):
        from core.document import capabilities
        assert not capabilities.model_supports_vision("newvision-7b")
        monkeypatch.setitem(o.settings._effective, o.VISION_MODELS, ["newvision"])
        assert capabilities.model_supports_vision("newvision-7b")

    def test_context_builder_limits_live(self, monkeypatch):
        from core.services.context_builder import ContextBuilder
        cb = ContextBuilder()
        assert cb.max_history_messages == 6
        monkeypatch.setitem(o.settings._effective, o.HISTORY_LIMIT, 10)
        assert cb.max_history_messages == 10
        assert ContextBuilder(3, 500, 5, 100).max_history_messages == 3

    def test_old_provider_env_vars_are_gone(self):
        app = Path(__file__).resolve().parents[1] / "app"
        source = "\n".join(p.read_text(encoding="utf-8") for p in app.rglob("*.py"))
        for env_name in ("GEMINI_API_KEY", "ORACLE_OPENAI_BASE_URL", "ORACLE_OPENAI_API_KEY",
                         "ORACLE_ANTHROPIC_API_KEY", "ORACLE_LLM_PROFILE_"):
            assert env_name not in source, env_name
