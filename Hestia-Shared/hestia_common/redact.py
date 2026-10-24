"""Clean text before it leaves for a model (Cindy idea 19, dossier docs/work/2026-10-24-tutto-brainstorm-cindy).

Logs, health reports and Forge requests may carry secrets and personal data: tokens, keys, passwords in URLs,
e-mail addresses, phone numbers, chat ids, home paths with the user name, IBANs, private IPs. Every module that
sends such text to a model (Argus analysis, Argus → Forge proposals, Forge prompts) passes it through
``redact`` first. Deny-by-default for known shapes: what looks like a secret is replaced by a typed placeholder
(``[email]``, ``[token]``…), the rest is untouched so the model can still reason about the log.

``redact(text)`` → cleaned text · ``redact_obj(obj)`` → same on every string of a JSON-like value ·
``found(text)`` → which kinds would be removed (for logs/tests).
"""
from __future__ import annotations

import re
from typing import Any

# Order matters: the most specific shapes first (a JWT also looks like a long token).
_RULES: list[tuple[str, re.Pattern, str]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "[chiave privata]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[token]"),
    ("bearer", re.compile(r"(?i)\b(bearer|token|basic)\s+[A-Za-z0-9._~+/=-]{12,}"), r"\1 [token]"),
    ("url_password", re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s@/]+@"), r"\1[credenziali]@"),
    ("assignment", re.compile(
        r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|PASSPHRASE|SECRET|TOKEN|API_?KEY|ACCESS_KEY|PRIVATE_KEY|CLIENT_SECRET|"
        r"COOKIE|SESSION_?ID|AUTH)[A-Z0-9_]*)(\s*[=:]\s*|\"\s*:\s*\")([^\s\"',;&]{3,})"), r"\1\2[segreto]"),
    ("query_secret", re.compile(r"(?i)([?&](?:access_token|refresh_token|id_token|token|key|api_key|apikey|code|"
                                r"secret|password|sig|signature)=)[^&\s\"']+"), r"\1[segreto]"),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), "[chiave]"),
    ("provider_key", re.compile(r"\b(?:sk|pk|rk)-(?:ant-|proj-|live-|test-)?[A-Za-z0-9_-]{16,}\b"), "[chiave]"),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), "[token]"),
    ("telegram_bot", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"), "[token]"),
    ("google_oauth", re.compile(r"\b(?:ya29\.[A-Za-z0-9_-]{20,}|1//[A-Za-z0-9_-]{20,})"), "[token]"),
    ("chat_id", re.compile(r"(?i)\b(chat[_ ]?id|user[_ ]?id|owner|from_id)(\s*[=:]\s*)-?\d{5,}"), r"\1\2[id]"),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[email]"),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b"), "[iban]"),
    ("card", re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"), "[carta]"),
    ("phone", re.compile(r"(?<![\w.])(?:\+\d{2,3}[ .-]?\d{2,4}[ .-]?\d{3,4}(?:[ .-]?\d{1,4})?|3\d{2}[ .-]?\d{3}[ .-]?\d{3,4})(?![\w.])"),
     "[telefono]"),
    ("windows_home", re.compile(r"(?i)\b([A-Z]:\\Users\\)[^\\\s\"']+"), r"\1[utente]"),
    ("unix_home", re.compile(r"(/home/|/Users/)(?!user\b)[^/\s\"']+"), r"\1[utente]"),
    ("private_ip", re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))(?:\.\d{1,3}){2,3}\b"), "[ip]"),
    ("long_hex", re.compile(r"\b[a-fA-F0-9]{40,}\b"), "[token]"),
]


def redact(text: Any) -> str:
    """Text with secrets and personal data replaced by placeholders. Non-strings are converted first."""
    if text is None:
        return ""
    out = text if isinstance(text, str) else str(text)
    for _, pattern, repl in _RULES:
        out = pattern.sub(repl, out)
    return out


def redact_obj(obj: Any) -> Any:
    """``redact`` applied to every string inside dicts/lists (keys kept; a secret-looking key hides its value)."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and re.search(r"(?i)password|passphrase|secret|token|api_?key|cookie|credential",
                                                k) and isinstance(v, (str, int, float)) and str(v):
                out[k] = "[segreto]"
            else:
                out[k] = redact_obj(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj


def found(text: Any) -> list[str]:
    """Kinds of data ``redact`` would remove from *text* (deduplicated, in rule order)."""
    out = text if isinstance(text, str) else str(text or "")
    kinds = []
    for kind, pattern, repl in _RULES:
        if pattern.search(out):
            kinds.append(kind)
            out = pattern.sub(repl, out)
    return kinds
