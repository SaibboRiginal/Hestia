"""Quiet mood capture — «I'm tired today» is written down without asking (dossier docs/work/2026-10-30-mood-diary).

After the answer, in the background step that already runs the memory extraction, Oracle looks at the user's
message for how they feel *now*. A deterministic gate comes first (no model): the message is split into clauses and
a clause counts only with a first-person present cue and a word of the mood lexicon, not as a question, not
hypothetical, not negated, not about yesterday. Only then a short prompt reads it (the same chain as the memory
extractor); a model that is offline or answers garbage falls back to the lexicon guess, a model that says NONE wins.
The result goes to the module that declares the Hub capability ``mood_capture_endpoint`` (no module name here);
«don't log it» calls ``<endpoint>/undo``. The reply never claims it: a quiet notice follows the answer.
Moods never go to long-term memory (memory rule 2c): that is the mood module's job.

The words of every language live in ``locales/<lang>/words.json`` («mood.rules», «mood.label.<id>»,
«mood.cause.<id>»): each language's rules read the clause on their own, so a new language is only a new file.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

from core.services import prompt_config
from hestia_common import i18n
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger(f"hestia_oracle.{__name__}")

LABELS = ("tired", "energized", "calm", "happy", "motivated", "bored", "nervous", "anxious", "sad", "down",
          "angry", "ill")
CAUSES = ("work", "sleep", "people", "health", "sport", "money", "home", "free_time", "weather")
_QUOTED = re.compile(r"[«\"“][^»\"”]*[»\"”]")
_NEVER = re.compile(r"(?!x)x")


def _rx(value: Any) -> re.Pattern:
    return re.compile(str(value), re.I) if value else _NEVER


@dataclass(frozen=True)
class _Rules:
    """The mood words of one language (``words.json`` «mood.rules»)."""
    lexicon: tuple
    day: re.Pattern
    day_levels: dict
    day_tired: frozenset
    needs_verb: frozenset
    first_person: re.Pattern
    verb_before: re.Pattern
    own_verb: re.Pattern
    third_person: re.Pattern
    not_now: re.Pattern
    negation: re.Pattern
    negated_good: frozenset
    split: re.Pattern
    continue_with: str
    undo: re.Pattern


@lru_cache(maxsize=1)
def _languages() -> tuple[_Rules, ...]:
    out = []
    for raw in i18n.word_tables("mood.rules").values():
        if not isinstance(raw, dict):
            continue
        out.append(_Rules(
            lexicon=tuple((str(r[0]), (r[1], int(r[2]), r[3], r[4])) for r in raw.get("lexicon") or [] if len(r) == 5),
            day=_rx(raw.get("day")), day_levels=dict(raw.get("day_levels") or {}),
            day_tired=frozenset(raw.get("day_tired") or []), needs_verb=frozenset(raw.get("needs_verb") or []),
            first_person=_rx(raw.get("first_person")), verb_before=_rx(raw.get("verb_before")),
            own_verb=_rx(raw.get("own_verb")), third_person=_rx(raw.get("third_person")),
            not_now=_rx(raw.get("not_now")), negation=_rx(raw.get("negation")),
            negated_good=frozenset(raw.get("negated_good") or []),
            split=re.compile(r"(?<=[.!?;:\n])|" + str(raw.get("split") or r"(?!x)x"), re.I),
            continue_with=str(raw.get("continue_with") or ""), undo=_rx(raw.get("undo"))))
    return tuple(out)


def is_undo(text: str) -> bool:
    """«Don't log it», «remove the mood»… in any language (deterministic)."""
    return any(r.undo.search(str(text or "")) for r in _languages())


def _clauses(text: str, rules: _Rules) -> list[str]:
    clean = _QUOTED.sub(" ", str(text or ""))
    return [c.strip() for c in rules.split.split(clean) if c and c.strip()]


def _hit(clause: str, rules: _Rules) -> dict | None:
    """The mood a clause states, or None. Deterministic: this is the gate and the offline fallback."""
    low = clause.lower()
    if low.endswith("?") or rules.not_now.search(low) or not rules.first_person.search(low):
        return None
    m = rules.day.search(low)
    if m and not rules.negation.search(low[:m.start()]) and m.group(1) in rules.day_levels:
        return {"mood": int(rules.day_levels[m.group(1)]), "energy": None, "stress": None,
                "labels": ["tired"] if m.group(1) in rules.day_tired else [], "quote": clause}
    for rx, (label, mood, energy, stress) in rules.lexicon:
        for m in re.finditer(rf"\b(?:{rx})\b", low):
            before = low[:m.start()]
            word = m.group(0)
            if word in rules.needs_verb and not rules.verb_before.search(before):
                continue
            if rules.third_person.search(before) and not rules.own_verb.search(before):
                continue
            if rules.negation.search(before):
                if word in rules.negated_good:     # «I'm not well» = down
                    return {"mood": 2, "energy": None, "stress": None, "labels": ["down"], "quote": clause}
                continue
            return {"mood": mood, "energy": energy, "stress": stress, "labels": [label] if label else [],
                    "quote": clause}
    return None


def mood_clauses(text: str) -> list[dict]:
    """Every clause of ``text`` that states how the user feels now, with the lexicon guess (the language whose rules
    find most wins). A clause with no subject of its own continues the previous first-person one («I'm happy but
    dead tired»)."""
    best: list[dict] = []
    for rules in _languages():
        hits: list[dict] = []
        previous_first = False
        for clause in _clauses(text, rules):
            low = clause.lower()
            own = bool(rules.first_person.search(low))
            hit = _hit(clause, rules)
            if hit is None and not own and previous_first and not rules.third_person.search(low):
                hit = _hit(f"{rules.continue_with}{clause}", rules)
                if hit:
                    hit["quote"] = clause
            if hit:
                hits.append(hit)
            previous_first = own if own or rules.third_person.search(low) else previous_first
        if len(hits) > len(best):
            best = hits
    return best


def guess(hits: list[dict]) -> dict | None:
    """One check-in from the gate's hits: the lowest mood wins (a bad day said in passing is still a bad day)."""
    if not hits:
        return None
    worst = min(hits, key=lambda h: h["mood"])
    pick = lambda f, fn: fn([h[f] for h in hits if h.get(f)]) if any(h.get(f) for h in hits) else None  # noqa: E731
    return {"mood": worst["mood"], "energy": pick("energy", min), "stress": pick("stress", max),
            "labels": list(dict.fromkeys(l for h in hits for l in h["labels"])),
            "quote": " · ".join(h["quote"] for h in hits)[:200]}


def _level(value: Any) -> int | None:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(1, min(5, n))


def parse_answer(raw: str) -> dict | None | str:
    """Model answer → check-in dict, ``"NONE"``, or None when it is garbage (→ lexicon fallback)."""
    text = str(raw or "").strip()
    if not text:
        return None
    if re.fullmatch(r"[\s`\"']*NONE[\s.`\"']*", text, re.I):
        return "NONE"
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    mood = _level(data.get("mood"))
    if mood is None:
        return None
    labels, causes = i18n.word_map("mood.label"), i18n.word_map("mood.cause")
    norm = lambda v, known: known.get(str(v or "").strip().lower().replace("_", " "),  # noqa: E731
                                      known.get(str(v or "").strip().lower(), ""))
    return {"mood": mood, "energy": _level(data.get("energy")), "stress": _level(data.get("stress")),
            "labels": [l for l in dict.fromkeys(norm(x, labels) for x in (data.get("labels") or [])) if l in LABELS],
            "causes": [c for c in dict.fromkeys(norm(x, causes) for x in (data.get("causes") or [])) if c in CAUSES]}


class MoodCapture:
    """``run(user_message)`` → notice signals (``mood.logged`` / ``mood.removed``), never raises."""

    _TTL = 60.0

    def __init__(self, hub, ask: Callable[[str], str]):
        self.hub = hub
        self.ask = ask
        self._endpoint: tuple[float, tuple[str, str] | None] = (0.0, None)

    def endpoint(self) -> tuple[str, str] | None:
        """(service, path) of the module that declares ``mood_capture_endpoint`` (cached 60 s)."""
        at, found = self._endpoint
        if time.time() - at < self._TTL:
            return found
        found = None
        services = self.hub.hub_get("registry/services", default=[], timeout=4)
        if isinstance(services, dict):
            services = services.get("services") or []
        for svc in services or []:
            if not isinstance(svc, dict):
                continue
            path = str((svc.get("capabilities") or {}).get("mood_capture_endpoint") or "").strip()
            if path:
                found = (str(svc.get("name") or svc.get("service_name") or "").strip().lower(), path)
                break
        self._endpoint = (time.time(), found)
        return found

    def run(self, user_message: str) -> list[dict]:
        try:
            return self._run(user_message)
        except Exception as exc:
            logger.warning("[🔄] event=mood_capture_failed error=%s fallback=skip", exc)
            return []

    def _run(self, user_message: str) -> list[dict]:
        text = str(user_message or "").strip()
        if not text or len(text) > 1500:
            return []
        if is_undo(text):
            return self._undo()
        hits = mood_clauses(text)
        if not hits:
            return []
        base = guess(hits)
        target = self.endpoint()
        if not target:
            logger.info("event=mood_capture_skipped reason=no_mood_module")
            return []
        raw = ""
        try:
            raw = self.ask(prompt_config.prompt("mood_capture_template", labels=", ".join(LABELS),
                                                causes=", ".join(CAUSES), user_message=text[:600],
                                                clauses=" | ".join(h["quote"] for h in hits)[:400]))
        except Exception as exc:
            logger.warning("[🔄] event=mood_capture_model_failed error=%s fallback=lexicon", exc)
        parsed = parse_answer(raw)
        if parsed == "NONE":
            logger.info("event=mood_capture_dropped reason=model_none quote=%s", base["quote"][:80])
            return []
        if parsed is None:
            logger.info("[🔄] event=mood_capture_fallback reason=unparsable fallback=lexicon raw=%s", str(raw)[:80])
            body = {**base, "causes": []}
        else:
            body = {**parsed, "labels": parsed["labels"] or base["labels"],
                    "energy": parsed["energy"] or base["energy"], "stress": parsed["stress"] or base["stress"],
                    "quote": base["quote"]}
        service, path = target
        ok, out = self.hub.route_to_service(service, path, "POST", body=body, timeout=8)
        if not ok:
            logger.warning("[🔄] event=mood_capture_write_failed service=%s detail=%s", service, str(out)[:120])
            return []
        out = out if isinstance(out, dict) else {}
        detail = f"{out.get('mood', body['mood'])}/5" + (f" · {', '.join(out.get('labels') or body['labels'])}"
                                                         if (out.get("labels") or body["labels"]) else "")
        logger.info("event=mood_capture_saved mood=%s labels=%s merged=%s", body["mood"], body["labels"],
                    out.get("merged"))
        return [{"event": "mood.logged", "message": tr("Mood noted: {0}", detail),
                 "data": {"detail": detail, "id": out.get("id"), "merged": bool(out.get("merged"))}}]

    def _undo(self) -> list[dict]:
        target = self.endpoint()
        if not target:
            return []
        service, path = target
        ok, out = self.hub.route_to_service(service, f"{path.rstrip('/')}/undo", "POST", body={}, timeout=8)
        if not ok or not (isinstance(out, dict) and out.get("deleted")):
            return []
        logger.info("event=mood_capture_undone id=%s", out.get("id"))
        return [{"event": "mood.removed", "message": tr("Mood removed"), "data": {"detail": tr("today's last entry")}}]
