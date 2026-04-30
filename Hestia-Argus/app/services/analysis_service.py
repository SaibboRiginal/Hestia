"""Analysis service — builds :class:`SystemReport` and calls Oracle for LLM analysis."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta

from core.docker_client import get_events
from core.health_poller import poll_all
from core.hub_client import discover_services, fetch_service_log_events
from schemas.reports import LogEvent, SystemReport


LOG_SOURCE = os.getenv("ARGUS_LOG_SOURCE", "hub").strip().lower()
HUB_LOG_LIMIT = int(os.getenv("ARGUS_HUB_LOG_LIMIT", "200"))


def _since_to_timedelta(since: str) -> timedelta:
    """Parse e.g. '30m', '2h', '1h30m' into a timedelta."""
    total = timedelta()
    for value, unit in re.findall(r"(\d+)([smh])", since.lower()):
        n = int(value)
        if unit == "s":
            total += timedelta(seconds=n)
        elif unit == "m":
            total += timedelta(minutes=n)
        elif unit == "h":
            total += timedelta(hours=n)
    return total or timedelta(minutes=30)


def get_filtered_logs(
    service_name: str | None = None,
    since: str = "30m",
    level: str = "WARNING",
) -> list[LogEvent]:
    """Return log events filtered by service, time window, and log level."""
    cutoff = datetime.utcnow() - _since_to_timedelta(since)
    if LOG_SOURCE == "docker":
        container_filter = f"hestia_{service_name}" if service_name else None
        all_events = get_events(
            container_name=container_filter, level_min=level)
    else:
        targets = [service_name] if service_name else [
            str(s.get("name", "")).strip()
            for s in discover_services()
            if str(s.get("name", "")).strip()
        ]
        all_events = []
        for target in targets:
            all_events.extend(
                fetch_service_log_events(
                    target,
                    level=level,
                    limit=HUB_LOG_LIMIT,
                )
            )

    filtered: list[LogEvent] = []
    for event in all_events:
        try:
            event_time = datetime.fromisoformat(str(event.timestamp))
        except ValueError:
            continue
        if event_time >= cutoff:
            filtered.append(event)
    return filtered


def build_raw_report() -> SystemReport:
    """Assemble raw health + log data into a :class:`SystemReport` (no Oracle call)."""
    services = discover_services()
    health_snapshot = poll_all(services)

    healthy = sum(1 for r in health_snapshot.values() if r.status == "up")
    unhealthy = sum(1 for r in health_snapshot.values() if r.status != "up")

    if LOG_SOURCE == "docker":
        recent_events = get_events(level_min="WARNING")
    else:
        recent_events = get_filtered_logs(since="30m", level="WARNING")
    recent_events = sorted(
        recent_events, key=lambda e: e.timestamp, reverse=True)[:50]

    down_services = [n for n, r in health_snapshot.items()
                     if r.status == "down"]
    degraded_services = [
        n for n, r in health_snapshot.items() if r.status == "degraded"]

    parts: list[str] = []
    if not down_services and not degraded_services and not recent_events:
        parts.append("All services appear healthy with no recent warnings.")
    else:
        if down_services:
            parts.append(f"DOWN: {', '.join(down_services)}.")
        if degraded_services:
            parts.append(f"Degraded: {', '.join(degraded_services)}.")
        if recent_events:
            parts.append(
                f"{len(recent_events)} recent log event(s) at WARNING or higher."
            )

    return SystemReport(
        timestamp=datetime.utcnow(),
        health_snapshot=health_snapshot,
        healthy_count=healthy,
        unhealthy_count=unhealthy,
        recent_events=recent_events,
        summary=" ".join(parts),
    )


def build_system_report(project_context: str = "") -> SystemReport:
    """Build a SystemReport enriched with an Oracle LLM summary.

    Collects raw health and log data, formats it as a structured prompt, and
    sends it to Oracle together with the project context (all hestia-*.md docs).
    Oracle's reply is stored in ``SystemReport.summary``.

    Falls back gracefully to the plain summary if Oracle is unavailable.
    """
    # Import here to avoid circular imports; oracle_client is lightweight.
    from core import oracle_client  # noqa: PLC0415

    report = build_raw_report()

    # Build a compact data block for the prompt.
    health_lines = [
        f"  - {name}: {r.status}" + (f" ({r.error})" if r.error else "")
        for name, r in report.health_snapshot.items()
    ]
    log_lines = [
        f"  [{e.level}] {e.service}: {e.message[:120]}"
        for e in report.recent_events[:20]
    ]

    prompt = (
        f"Current Hestia system state as of {report.timestamp.isoformat()}:\n\n"
        f"Health ({report.healthy_count} healthy, {report.unhealthy_count} unhealthy):\n"
        + "\n".join(health_lines or ["  (no services registered)"])
        + "\n\nRecent log events (WARNING and above):\n"
        + "\n".join(log_lines or ["  (none)"])
        + "\n\nProvide a concise analysis of the system state. "
        "Be brief: one status line, then bullet points for any issues (service, symptom, likely cause), "
        "then bullet points for suggested actions if needed (max 3). "
        "Prefer bullet lists over paragraphs. No intro or closing phrases."
    )

    llm_summary = oracle_client.analyze(prompt, context=project_context)
    if llm_summary:
        report.summary = llm_summary

    return report
