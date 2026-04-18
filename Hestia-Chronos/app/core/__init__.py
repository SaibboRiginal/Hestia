"""Hestia-Chronos — unified calendar CRUD gateway.

Exposes a provider-agnostic HTTP API for creating, listing, updating, and
deleting calendar events.  Multiple calendar backends (Google Calendar,
Microsoft Outlook) are configured via environment variables and operated
simultaneously when requested.

Registered in Hub as service name ``chronos`` with tags [core, integration].
Oracle and other modules call it exclusively through Hub routing — this
service never receives calls from the outside world directly.
"""
from __future__ import annotations
