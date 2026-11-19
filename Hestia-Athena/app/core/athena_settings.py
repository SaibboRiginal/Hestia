"""Athena settings declared to Themis (central settings).

Every tunable of Athena lives here (no env vars): the loop, the relevance gate, the
retrospective, Oracle hints, observer/strategist/auditor timeouts, memory consolidation and
skill curation thresholds. All ``live`` (read at use time) except the task store size.

*When* Athena works (consolidation, skill curation, thinking windows) is NOT a setting:
those are assistant-agenda windows (Chronos) the user moves/skips/pauses there.
"""
from __future__ import annotations

from .shared_imports import import_shared_symbol

SettingsClient = import_shared_symbol("hestia_common.settings_client", "SettingsClient")
setting = import_shared_symbol("hestia_common.settings_client", "setting")

PROPOSALS_PER_DAY = "athena.settings.proposals_per_day"

LOOP_ENABLED = "athena.loop.enabled"
LOOP_INTERVAL = "athena.loop.interval"
LOOP_IDLE_SECONDS = "athena.loop.idle_seconds"
GATE_THRESHOLD = "athena.gate.threshold"

RETRO_WINDOW = "athena.retro.window"
RETRO_FAILURE_URGENCY_BOOST = "athena.retro.failure_urgency_boost"
RETRO_UNRESOLVED_URGENCY_BOOST = "athena.retro.unresolved_urgency_boost"
RETRO_UNRESOLVED_USEFULNESS_BOOST = "athena.retro.unresolved_usefulness_boost"
COMMITMENT_TTL = "athena.commitments.ttl"

HINTS_ENABLED = "athena.hints.enabled"
HINTS_TIMEOUT = "athena.hints.timeout"

THINKING_ARCHIVE_ENABLED = "athena.thinking.archive_enabled"
THINKING_STORE_MAX = "athena.thinking.store_max"
TASK_STORE_MAX = "athena.tasks.store_max"

OBSERVE_TIMEOUT = "athena.observe.timeout"
OBSERVE_ENTITY_WINDOW_HOURS = "athena.observe.entity_window_hours"

STRATEGIST_ENABLED = "athena.strategist.enabled"
STRATEGIST_TIMEOUT = "athena.strategist.timeout"
STRATEGIST_MAX_CANDIDATES = "athena.strategist.max_candidates"

FORGE_ENABLED = "athena.forge.enabled"
FORGE_MAX_PER_DAY = "athena.forge.max_per_day"

MEMORY_ACTIVE_DAYS = "athena.memory.active_days"
MEMORY_LOOKBACK_HOURS = "athena.memory.lookback_hours"
MEMORY_ORACLE_TIMEOUT = "athena.memory.oracle_timeout"
MEMORY_PREFERENCE_DECAY_DAYS = "athena.memory.preference_decay_days"
MEMORY_REINFORCE_THRESHOLD = "athena.memory.reinforce_threshold"

SKILLS_MIN_SESSIONS = "athena.skills.min_sessions"
SKILLS_SIM_THRESHOLD = "athena.skills.sim_threshold"
SKILLS_DEDUP_THRESHOLD = "athena.skills.dedup_threshold"
SKILLS_STALE_DAYS = "athena.skills.stale_days"
SKILLS_HARD_DELETE_DAYS = "athena.skills.hard_delete_days"
SKILLS_CORE_USE_COUNT = "athena.skills.core_use_count"

TALK_MAX_PER_DAY = "athena.talk.max_per_day"
TALK_MIN_GAP_HOURS = "athena.talk.min_gap_hours"
TALK_EAGERNESS = "athena.talk.eagerness"

EVIDENCE_MIN_DAYS = "athena.evidence.min_days"
EVIDENCE_SEEN_DAYS = "athena.evidence.seen_days"
EVIDENCE_WINDOW_DAYS = "athena.evidence.window_days"

REFLECTION_MAX_PER_DAY = "athena.reflection.max_per_day"
REFLECTION_MAX_TOPICS = "athena.reflection.max_topics"
REFLECTION_MIN_WEEKS = "athena.reflection.min_weeks"
REFLECTION_MIN_CORRELATION = "athena.reflection.min_correlation"
REFLECTION_REPEAT_DAYS = "athena.reflection.repeat_days"
REFLECTION_DETAIL_BUDGET = "athena.reflection.detail_budget"

AUDIT_TIMEOUT = "athena.audit.timeout"
AUDIT_MAX_TURNS = "athena.audit.max_turns"

RECAP_STYLE = "athena.recap.style"
RECAP_MAX_CHARS = "athena.recap.max_chars"
RECAP_PIECE_TIMEOUT = "athena.recap.piece_timeout_seconds"

_G_LOOP = "Proactive thinking"
_G_RETRO = "Retrospective"
_G_HINTS = "Suggestions to Oracle"
_G_RECORDS = "Thought log"
_G_STRATEGY = "Observation and strategy"
_G_FORGE = "Improvements (Forge)"
_G_MEMORY = "Memory consolidation"
_G_SKILLS = "Skill care"
_G_AUDIT = "Conversation audit"
_G_RECAP = "Daily recap"
_G_REFLECTION = "Reflection on your life"
_G_TALK = "Writes to you first"
_G_EVIDENCE = "First observe, then propose"

_ON_LOOP = {"key": LOOP_ENABLED, "equals": True}
_ON_HINTS = {"key": HINTS_ENABLED, "equals": True}
_ON_FORGE = {"key": FORGE_ENABLED, "equals": True}
_ON_STRATEGIST = {"key": STRATEGIST_ENABLED, "equals": True}

settings = SettingsClient("athena")
settings.declare([
    setting(PROPOSALS_PER_DAY, "Settings proposals per day", "int", 2, group="Proposals", min=0, max=10,
            help="How many settings changes Athena can propose to you per day (0 = none). Each proposal always waits for your confirmation."),

    # ── Loop ────────────────────────────────────────────────────────────────
    setting(LOOP_ENABLED, "Athena on", "bool", True, group=_G_LOOP, order=0,
            help="If off, Athena does not observe, think or propose anything on her own."),
    setting(LOOP_INTERVAL, "Interval between cycles", "int", 300, group=_G_LOOP, min=30, max=86400, unit="s",
            order=1, depends_on=_ON_LOOP,
            help="How often Athena does a round of observation and reflection. Shorter = more reactive but uses the model more."),
    setting(LOOP_IDLE_SECONDS, "Requested pause from chat", "int", 300, group=_G_LOOP, min=0, max=7200, unit="s",
            order=2, depends_on=_ON_LOOP,
            help="Fallback: used only if the assistant's state (Chronos) does not answer. Athena thinks only if you haven't chatted for at least this long (0 = thinks even while you chat). Normally the state decides: it thinks when you are not «Awake»."),
    setting(GATE_THRESHOLD, "Relevance threshold", "float", 0.55, group=_G_LOOP, min=0.0, max=1.0, order=3,
            depends_on=_ON_LOOP,
            help="How relevant an idea must be for Athena to send it to you. Higher = fewer messages, only the most useful."),

    # ── Retrospective (expert) ──────────────────────────────────────────────
    setting(RETRO_WINDOW, "Outcomes remembered", "int", 24, group=_G_RETRO, min=1, max=500, advanced=True,
            help="How many recent outcomes Athena considers to understand what is going wrong."),
    setting(RETRO_FAILURE_URGENCY_BOOST, "Urgency boost for failures", "float", 0.07, group=_G_RETRO,
            min=0.0, max=0.5, advanced=True,
            help="How much each consecutive failure raises the urgency of new ideas."),
    setting(RETRO_UNRESOLVED_URGENCY_BOOST, "Urgency boost for open commitments", "float", 0.04, group=_G_RETRO,
            min=0.0, max=0.5, advanced=True,
            help="How much each unresolved commitment raises the urgency of new ideas."),
    setting(RETRO_UNRESOLVED_USEFULNESS_BOOST, "Usefulness boost for open commitments", "float", 0.03,
            group=_G_RETRO, min=0.0, max=0.5, advanced=True,
            help="How much each unresolved commitment raises the estimated usefulness of new ideas."),
    setting(COMMITMENT_TTL, "Duration of a commitment", "int", 86400, group=_G_RETRO, min=60, max=2592000, unit="s",
            advanced=True,
            help="After how long an unresolved suggestion expires (also for suggestions given to Oracle)."),

    # ── Oracle hints ────────────────────────────────────────────────────────
    setting(HINTS_ENABLED, "Suggestions to the assistant", "bool", True, group=_G_HINTS,
            help="Athena passes her ideas to Oracle, so the assistant takes them into account when you talk to it."),
    setting(HINTS_TIMEOUT, "Wait to send a suggestion", "int", 8, group=_G_HINTS, min=1, max=120, unit="s",
            advanced=True, depends_on=_ON_HINTS,
            help="How long to wait for Oracle when Athena passes it a suggestion."),

    # ── Thinking records ────────────────────────────────────────────────────
    setting(THINKING_ARCHIVE_ENABLED, "Save thoughts in the archive", "bool", True, group=_G_RECORDS,
            help="Keeps in Archive every thought cycle (what it saw, considered and decided)."),
    setting(THINKING_STORE_MAX, "Thoughts kept in memory", "int", 100, group=_G_RECORDS, min=5, max=1000,
            advanced=True, help="How many recent thought cycles Athena keeps ready to show you."),
    setting(TASK_STORE_MAX, "Tasks kept in memory", "int", 500, group=_G_RECORDS, min=50, max=5000,
            apply="restart", advanced=True,
            help="How many recent tasks Athena remembers (from the next restart)."),

    # ── Observer + strategist ───────────────────────────────────────────────
    setting(OBSERVE_TIMEOUT, "Module observation wait", "float", 8.0, group=_G_STRATEGY, min=1, max=60,
            unit="s", advanced=True,
            help="How long to wait for each module when Athena collects the system state."),
    setting(OBSERVE_ENTITY_WINDOW_HOURS, "News considered", "int", 24, group=_G_STRATEGY, min=1, max=720,
            unit="h", help="How far back to look for new module data (e.g. listings, events)."),
    setting(STRATEGIST_ENABLED, "Ideas with the model", "bool", True, group=_G_STRATEGY,
            help="Athena uses the model to turn what she observes into ideas and proposals."),
    setting(STRATEGIST_TIMEOUT, "Wait for ideas from the model", "float", 20.0, group=_G_STRATEGY, min=5, max=300,
            unit="s", advanced=True, depends_on=_ON_STRATEGIST,
            help="How long to wait for the model for each round of ideas."),
    setting(STRATEGIST_MAX_CANDIDATES, "Ideas per cycle", "int", 3, group=_G_STRATEGY, min=1, max=10,
            depends_on=_ON_STRATEGIST,
            help="How many ideas at most Athena evaluates in each cycle."),

    # ── Forge hand-off (acts without the user: assistant may only read it) ─
    setting(FORGE_ENABLED, "Propose improvements to Forge", "bool", True, group=_G_FORGE, oracle="read",
            help="Athena sends code improvement ideas to Forge. Forge follows the permissions you chose; the merge always asks you."),
    setting(FORGE_MAX_PER_DAY, "Improvements per day", "int", 2, group=_G_FORGE, min=0, max=20,
            depends_on=_ON_FORGE, oracle="read",
            help="How many improvement requests Athena can send to Forge each day."),

    # ── Memory consolidation ────────────────────────────────────────────────
    setting(MEMORY_ACTIVE_DAYS, "Recent sessions considered", "int", 7, group=_G_MEMORY, min=1, max=90,
            unit="days", help="Consolidates the memory of the conversations active in the last N days."),
    setting(MEMORY_LOOKBACK_HOURS, "Shortest interval per session", "int", 24, group=_G_MEMORY, min=1, max=720,
            unit="h", advanced=True,
            help="The same conversation is not consolidated again before this time."),
    setting(MEMORY_ORACLE_TIMEOUT, "Memory analysis wait", "int", 30, group=_G_MEMORY, min=5, max=600,
            unit="s", advanced=True, help="How long to wait for the model that extracts the facts to remember."),
    setting(MEMORY_PREFERENCE_DECAY_DAYS, "Preference forgetting", "int", 90, group=_G_MEMORY, min=7, max=3650,
            unit="days",
            help="Preferences no longer confirmed for this long lose importance."),
    setting(MEMORY_REINFORCE_THRESHOLD, "Confirmations to reinforce", "int", 3, group=_G_MEMORY, min=1, max=50,
            advanced=True, help="How many times a pattern must repeat before becoming a strong preference."),

    # ── Skill curation ──────────────────────────────────────────────────────
    setting(SKILLS_MIN_SESSIONS, "Sessions to create a skill", "int", 3, group=_G_SKILLS, min=1, max=50,
            help="How many similar conversations are needed for Athena to draw a skill from them."),
    setting(SKILLS_SIM_THRESHOLD, "Similarity between conversations", "float", 0.90, group=_G_SKILLS,
            min=0.5, max=1.0, advanced=True,
            help="How similar two conversations must be to be grouped."),
    setting(SKILLS_DEDUP_THRESHOLD, "Similarity for duplicate skills", "float", 0.95, group=_G_SKILLS,
            min=0.5, max=1.0, advanced=True,
            help="Beyond this similarity two skills are considered the same and are merged."),
    setting(SKILLS_STALE_DAYS, "Unused skills to deprecate", "int", 30, group=_G_SKILLS, min=1, max=3650,
            unit="days", help="A skill not used for this long is deprecated."),
    setting(SKILLS_HARD_DELETE_DAYS, "Unused skills to delete", "int", 90, group=_G_SKILLS, min=1,
            max=3650, unit="days",
            help="A rarely used skill idle for this long is deleted."),
    setting(SKILLS_CORE_USE_COUNT, "Uses for a core skill", "int", 50, group=_G_SKILLS, min=1, max=10000,
            advanced=True,
            help="A skill used successfully more than this becomes core."),

    # ── Life reflection (signals of the modules → links between domains → the evening recap) ─
    setting(REFLECTION_MAX_PER_DAY, "Observations per day", "int", 2, group=_G_REFLECTION, min=1, max=5,
            help="How many observations about your life go into the evening recap at most."),
    setting(REFLECTION_MAX_TOPICS, "Topics per reflection", "int", 4, group=_G_REFLECTION, min=1, max=10,
            help="How many signals or links each reflection looks into."),
    setting(REFLECTION_MIN_WEEKS, "Weeks for a link", "int", 6, group=_G_REFLECTION, min=3, max=52,
            unit="weeks", help="How many weeks with data are needed before linking two habits."),
    setting(REFLECTION_MIN_CORRELATION, "Weakest link strength", "float", 0.6, group=_G_REFLECTION,
            min=0.3, max=0.95, advanced=True,
            help="How much two trends must move together (correlation) to count."),
    setting(REFLECTION_REPEAT_DAYS, "Don't repeat before", "int", 14, group=_G_REFLECTION, min=1, max=180,
            unit="days", advanced=True, help="The same observation does not come back before this."),
    setting(REFLECTION_DETAIL_BUDGET, "Details asked of each area", "int", 600, group=_G_REFLECTION, min=100,
            max=3000, unit="characters", advanced=True,
            help="How much text to ask an area when a signal deserves a closer look."),

    # ── She writes first (docs/work/2026-11-12-identity-and-proactivity). WHEN = agenda window athena.talk ──
    setting(TALK_MAX_PER_DAY, "How many times a day", "int", 2, group=_G_TALK, min=0, max=6,
            help="How many times a day it can write to you first, to ask you something or have a chat. It does so only with a real reason. 0 = never. You move the hours in the calendar."),
    setting(TALK_MIN_GAP_HOURS, "Pause between two messages", "int", 4, group=_G_TALK, min=1, max=24, unit="hours",
            advanced=True, help="How long it waits at least between one of its messages and the next."),
    setting(TALK_EAGERNESS, "How talkative", "int", 3, group=_G_TALK, min=1, max=5,
            help="How much it wants to write to you first. The wish grows if you haven't talked for a while and if it has something real to say, and drops if you don't answer. 1 = only when it has a lot to say, 5 = often. In the first days, knowing little about you, it writes little anyway."),

    # ── First observe, then propose (docs/work/2026-11-13-observe-then-propose) ──
    setting(EVIDENCE_MIN_DAYS, "Days of observation before proposing", "int", 5, group=_G_EVIDENCE, min=0,
            max=30, unit="days", order=0,
            help="After the first start it only observes for these days: no improvement or settings proposals. Real faults are reported at once, and «Pensa ora» does not wait."),
    setting(EVIDENCE_SEEN_DAYS, "On how many different days it must see it again", "int", 3, group=_G_EVIDENCE, min=1,
            max=14, unit="days", order=1,
            help="Proposes an improvement or a change only if the same thing came up on at least these different days. Once is not enough to judge."),
    setting(EVIDENCE_WINDOW_DAYS, "Within how many days", "int", 14, group=_G_EVIDENCE, min=1, max=90,
            unit="days", order=2, advanced=True,
            help="Evidence older than this no longer counts."),

    # ── Conversation audit ──────────────────────────────────────────────────
    setting(AUDIT_TIMEOUT, "Audit wait", "float", 40.0, group=_G_AUDIT, min=5, max=600, unit="s",
            advanced=True, help="How long to wait for the model that rates the answers."),
    setting(AUDIT_MAX_TURNS, "Answers per audit", "int", 20, group=_G_AUDIT, min=1, max=100,
            help="How many recent answers an audit evaluates if you don't say otherwise."),

    # ── Daily recap (docs/work/2026-10-20-daily-recap). WHEN = agenda job, not a setting ──
    setting(RECAP_STYLE, "Recap tone", "enum", "amichevole", group=_G_RECAP,
            options=["amichevole", "asciutto"],
            help="How the daily recap is written to you: friendly (a few more words) or dry (just the facts). You move the time in the calendar."),
    setting(RECAP_MAX_CHARS, "Longest recap", "int", 900, group=_G_RECAP, min=200, max=4000,
            unit="characters", help="The recap stays under this length."),
    setting(RECAP_PIECE_TIMEOUT, "Wait for each area", "float", 5.0, group=_G_RECAP, min=1, max=30, unit="s",
            advanced=True, help="How long to wait for each area (training, expenses…) before making the recap without it."),
]).declare_log_level()
settings.follow_personal()      # the owner's language: texts for people written by the model


def owner_language() -> str:
    """The owner's language in English («Italian»…) for hidden prompts (hestia_common.identity)."""
    from hestia_common import i18n, identity
    return identity.LANGUAGES[i18n.language(settings.get)]


def get_int(key: str) -> int:
    return int(settings.get(key))


def get_float(key: str) -> float:
    return float(settings.get(key))


def get_bool(key: str) -> bool:
    return bool(settings.get(key))
