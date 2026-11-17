"""Quiet mood capture — «I'm tired today» (any language) is written down without asking (dossier docs/work/2026-10-30-diario-umore).

After the answer, in the background step that already runs the memory extraction, Oracle looks at the user's
message for how they feel *now*. A deterministic gate comes first (no model): the message is split into clauses and
a clause counts only with a first-person present cue and a word of the mood lexicon, not as a question, not
hypothetical, not negated, not about yesterday. Only then a short prompt reads it (the same chain as the memory
extractor); a model that is offline or answers garbage falls back to the lexicon guess, a model that says NONE wins.
The result goes to the module that declares the Hub capability ``mood_capture_endpoint`` (no module name here);
«don't log it» calls ``<endpoint>/undo``. The reply never claims it: a quiet notice follows the answer.
Moods never go to long-term memory (memory rule 2c): that is the mood module's job.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable

from core.services import prompt_config
from hestia_common.i18n import t as tr  # fixed texts in the owner's language
from hestia_common.i18n import word_regex, word_set, words

logger = logging.getLogger(f"hestia_oracle.{__name__}")

# Stored values (English): mood labels and causes. The words that say them live in locales/<lang>/words.json.
LABELS = ("tired", "charged", "calm", "happy", "motivated", "bored", "nervous", "anxious", "sad", "down",
          "angry", "sick")
CAUSES = ("work", "sleep", "people", "health", "sport", "money", "home", "free_time", "weather")

# words list → (label, mood, energy, stress). Order matters: stronger lists first.
_LEXICON: list[tuple[str, tuple[str | None, int, int | None, int | None]]] = [
    ("mood.tired_heavy", ("tired", 2, 1, None)),
    ("mood.tired", ("tired", 3, 2, None)),
    ("mood.charged_high", ("charged", 5, 5, None)),
    ("mood.charged", ("charged", 4, 5, None)),
    ("mood.calm", ("calm", 4, None, 1)),
    ("mood.happy_high", ("happy", 5, None, None)),
    ("mood.happy", ("happy", 4, None, None)),
    ("mood.motivated", ("motivated", 4, 4, None)),
    ("mood.bored", ("bored", 3, 2, None)),
    ("mood.nervous", ("nervous", 2, None, 4)),
    ("mood.anxious", ("anxious", 2, None, 5)),
    ("mood.sad", ("sad", 2, None, None)),
    ("mood.down_low", ("down", 1, None, None)),
    ("mood.down", ("down", 2, None, None)),
    ("mood.angry", ("angry", 2, None, 4)),
    ("mood.sick", ("sick", 2, 2, None)),
    ("mood.so_so", (None, 3, None, None)),
]
# «what a heavy day»: words list → (mood, labels)
_DAYS = (("mood.day_tired", 2, ["tired"]), ("mood.day_1", 1, []), ("mood.day_2", 2, []), ("mood.day_5", 5, []),
         ("mood.day_4", 4, []))


def _rx(template: str, *keys: str) -> "re.Pattern[str]":
    return word_regex(template, *keys)


def _first_person():
    return _rx(r"\b(?:{0})\b", "mood.first_person")


def _verb_before():
    return _rx(r"\b(?:{0})\s+(?:(?:{1})\s+)?$", "mood.subject_verb", "mood.adverb")


def _third_person():
    return _rx(r"\b(?:{0})(?=\s|$)", "mood.third_person")


def _not_now():
    return _rx(r"^\s*(?:{0})\b|\b(?:{1})\b", "mood.not_now_start", "mood.not_now")


def _negation():
    return _rx(r"\b(?:{0})\s+(?:\w+\s+){{0,2}}$", "mood.negation")


_QUOTED = re.compile(r"[«\"“][^»\"”]*[»\"”]")


def _split():
    return _rx(r"(?<=[.!?;:\n])|,|\b(?:{0})\b", "mood.but")


def is_undo(text: str) -> bool:
    """«Don't log it», «remove my mood»… in any language with a words file (deterministic)."""
    return bool(_rx(r"\b(?:{0})\b", "mood.undo").search(str(text or "")))


def _clauses(text: str) -> list[str]:
    clean = _QUOTED.sub(" ", str(text or ""))
    return [c.strip() for c in _split().split(clean) if c and c.strip()]


def _hit(clause: str) -> dict | None:
    """The mood a clause states, or None. Deterministic: this is the gate and the offline fallback."""
    low = clause.lower()
    if low.endswith("?") or _not_now().search(low) or not _first_person().search(low):
        return None
    for key, level, labels in _DAYS:
        m = _rx(r"\b(?:{0})\b", key).search(low)
        if m and not _negation().search(low[:m.start()]):
            return {"mood": level, "energy": None, "stress": None, "labels": list(labels), "quote": clause}
    needs_verb, good = word_set("mood.needs_verb"), word_set("mood.good_words")
    subject = _rx(r"\b(?:{0})\b", "mood.subject_verb")
    for key, (label, mood, energy, stress) in _LEXICON:
        for m in _rx(r"\b(?:{0})\b", key).finditer(low):
            before = low[:m.start()]
            word = m.group(0)
            if word in needs_verb and not _verb_before().search(before):
                continue
            if _third_person().search(before) and not subject.search(before):
                continue
            if _negation().search(before):
                if word in good:     # «I'm not well» = down
                    return {"mood": 2, "energy": None, "stress": None, "labels": ["down"], "quote": clause}
                continue
            return {"mood": mood, "energy": energy, "stress": stress, "labels": [label] if label else [],
                    "quote": clause}
    return None


def mood_clauses(text: str) -> list[dict]:
    """Every clause of ``text`` that states how the user feels now, with the lexicon guess. A clause with no subject
    of its own continues the previous first-person one («I'm happy but dead tired»)."""
    hits: list[dict] = []
    previous_first = False
    for clause in _clauses(text):
        low = clause.lower()
        own = bool(_first_person().search(low))
        hit = _hit(clause)
        if hit is None and not own and previous_first and not _third_person().search(low):
            for prefix in words("mood.continue_prefix"):
                hit = _hit(f"{prefix} {clause}")
                if hit:
                    hit["quote"] = clause
                    break
        if hit:
            hits.append(hit)
        previous_first = own if own or _third_person().search(low) else previous_first
    return hits


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
    norm = lambda v: str(v or "").strip().lower().replace(" ", "_")  # noqa: E731
    return {"mood": mood, "energy": _level(data.get("energy")), "stress": _level(data.get("stress")),
            "labels": [l for l in dict.fromkeys(norm(x) for x in (data.get("labels") or [])) if l in LABELS],
            "causes": [c for c in dict.fromkeys(norm(x) for x in (data.get("causes") or [])) if c in CAUSES]}


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
