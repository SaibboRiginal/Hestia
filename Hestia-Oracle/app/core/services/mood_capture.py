"""Quiet mood capture — «oggi sono stanco» is written down without asking (dossier docs/work/2026-10-30-diario-umore).

After the answer, in the background step that already runs the memory extraction, Oracle looks at the user's
message for how they feel *now*. A deterministic gate comes first (no model): the message is split into clauses and
a clause counts only with a first-person present cue and a word of the mood lexicon, not as a question, not
hypothetical, not negated, not about yesterday. Only then a short prompt reads it (the same chain as the memory
extractor); a model that is offline or answers garbage falls back to the lexicon guess, a model that says NONE wins.
The result goes to the module that declares the Hub capability ``mood_capture_endpoint`` (no module name here);
«non segnarlo» calls ``<endpoint>/undo``. The reply never claims it: a quiet notice follows the answer.
Moods never go to long-term memory (memory rule 2c): that is the mood module's job.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable

from core.services import prompt_config

logger = logging.getLogger(f"hestia_oracle.{__name__}")

LABELS = ("stanco", "carico", "sereno", "contento", "motivato", "annoiato", "nervoso", "ansioso", "triste", "giù",
          "arrabbiato", "malato")
CAUSES = ("lavoro", "sonno", "persone", "salute", "sport", "soldi", "casa", "tempo libero", "meteo")

# word/phrase → (label, mood, energy, stress). Order matters: longer phrases first.
_LEXICON: list[tuple[str, tuple[str | None, int, int | None, int | None]]] = [
    (r"stanc[oa] mort[oa]|distrutt[oa]|esaust[oa]|sfinit[oa]|a pezzi|cott[oa]|spompat[oa]|stanchissim[oa]",
     ("stanco", 2, 1, None)),
    (r"stanc[oa]|assonnat[oa]|senza energi[ae]|scaric[oa]", ("stanco", 3, 2, None)),
    (r"carichissim[oa]|gasatissim[oa]|pien[oa] di energia", ("carico", 5, 5, None)),
    (r"caric[oa]|gasat[oa]|in forma|spacco", ("carico", 4, 5, None)),
    (r"seren[oa]|tranquill[oa]|rilassat[oa]|in pace", ("sereno", 4, None, 1)),
    (r"felicissim[oa]|alla grande|benissimo|al settimo cielo|da dio", ("contento", 5, None, None)),
    (r"felice|content[oa]|allegr[oa]|di buon umore|soddisfatt[oa]|bene", ("contento", 4, None, None)),
    (r"motivat[oa]|carico di voglia|ispirat[oa]", ("motivato", 4, 4, None)),
    (r"annoiat[oa]|apatic[oa]", ("annoiato", 3, 2, None)),
    (r"nervos[oa]|irritat[oa]|agitat[oa]|teso|tesa|sotto pressione", ("nervoso", 2, None, 4)),
    (r"ansios[oa]|in ansia|preoccupat[oa]|stressat[oa]|stressatissim[oa]|in panico", ("ansioso", 2, None, 5)),
    (r"triste|depress[oa]|abbattut[oa]|malinconic[oa]|giù di morale", ("triste", 2, None, None)),
    (r"malissimo|uno schifo|di merda|a terra|uno straccio", ("giù", 1, None, None)),
    (r"giù|giu|demoralizzat[oa]|di cattivo umore|scoraggiat[oa]|male", ("giù", 2, None, None)),
    (r"arrabbiat[oa]|incazzat[oa]|furios[oa]|furibond[oa]", ("arrabbiato", 2, None, 4)),
    (r"malat[oa]|influenzat[oa]|raffreddat[oa]|con la febbre|ho la febbre|ho mal di testa|ho l'influenza",
     ("malato", 2, 2, None)),
    (r"così così|cosi cosi|insomma|normale", (None, 3, None, None)),
]
_DAY = re.compile(r"\b(?:che |una )?giornata (pesante|dura|storta|no|di merda|schifosa|orribile|infinita|"
                  r"ottima|fantastica|splendida|bellissima|top|perfetta|tranquilla|leggera)\b", re.I)
_DAY_LEVELS = {"pesante": 2, "dura": 2, "storta": 2, "no": 2, "di merda": 1, "schifosa": 1, "orribile": 1,
               "infinita": 2, "ottima": 5, "fantastica": 5, "splendida": 5, "bellissima": 5, "top": 5, "perfetta": 5,
               "tranquilla": 4, "leggera": 4}
# Words that are a mood only right after «sto / mi sento / sono» («mi fa male il ginocchio» is not a mood).
_NEEDS_VERB = {"bene", "male", "benissimo", "malissimo", "normale", "insomma", "così così", "cosi cosi", "teso",
               "tesa", "a terra", "da dio", "cotto", "cotta", "giu"}
_FIRST_PERSON = re.compile(r"\b(sono|son|mi sento|sto|mi sono|mi trovo|oggi|stamattina|stasera|stanotte|"
                           r"ultimamente|in questi giorni|da qualche giorno|che giornata|giornata|spacco|"
                           r"ho (?:la febbre|mal di \w+|l'influenza))\b", re.I)
_VERB_BEFORE = re.compile(r"\b(sto|mi sento|sono|son|mi sono sentit[oa])\s+(?:proprio\s+|davvero\s+|molto\s+|"
                          r"un po'?\s+|abbastanza\s+|così\s+|troppo\s+)?$", re.I)
_THIRD_PERSON = re.compile(r"\b(è|e'|sei|siamo|siete|era|erano|sembra|sembri)\b", re.I)
_NOT_NOW = re.compile(r"^\s*(perch[eé]|come mai|se|quando|anche se|nel caso|qualora|chi|cosa|why|if)\b|"
                      r"\b(ieri|l'altro ieri|la settimana scorsa|ero|fossi|sarei|sarò|sarai)\b", re.I)
_NEGATION = re.compile(r"\b(non|mai|né|nemmeno|neanche|per niente)\s+(?:\w+\s+){0,2}$", re.I)
_QUOTED = re.compile(r"[«\"“][^»\"”]*[»\"”]")
_SPLIT = re.compile(r"(?<=[.!?;:\n])|,|\bma\b|\bperò\b|\be poi\b", re.I)
_UNDO = re.compile(r"\bnon (?:lo |l')?(?:segnare|segnarlo|registrare|registrarlo|salvare|salvarlo|scriverlo)\b|"
                   r"\btogli(?:lo)? (?:l'umore|dall'umore|quello che ho detto)\b|"
                   r"\bcancella (?:l'umore|l'ultimo umore)\b|\bnon (?:segnare|registrare) l'umore\b|"
                   r"\bnon è vero,? (?:sto bene|non sono)\b", re.I)


def is_undo(text: str) -> bool:
    """«Non segnarlo», «togli l'umore»… (deterministic)."""
    return bool(_UNDO.search(str(text or "")))


def _clauses(text: str) -> list[str]:
    clean = _QUOTED.sub(" ", str(text or ""))
    return [c.strip() for c in _SPLIT.split(clean) if c and c.strip()]


def _hit(clause: str) -> dict | None:
    """The mood a clause states, or None. Deterministic: this is the gate and the offline fallback."""
    low = clause.lower()
    if low.endswith("?") or _NOT_NOW.search(low) or not _FIRST_PERSON.search(low):
        return None
    m = _DAY.search(low)
    if m and not _NEGATION.search(low[:m.start()]):
        level = _DAY_LEVELS[m.group(1)]
        return {"mood": level, "energy": None, "stress": None,
                "labels": ["stanco"] if m.group(1) in ("pesante", "dura", "infinita") else [], "quote": clause}
    for rx, (label, mood, energy, stress) in _LEXICON:
        for m in re.finditer(rf"\b(?:{rx})\b", low):
            before = low[:m.start()]
            word = m.group(0)
            if word in _NEEDS_VERB and not _VERB_BEFORE.search(before):
                continue
            if _THIRD_PERSON.search(before) and not re.search(r"\b(sono|mi sento|sto)\b", before):
                continue
            if _NEGATION.search(before):
                if word in ("bene", "benissimo", "in forma", "alla grande"):     # «non sto bene» = giù
                    return {"mood": 2, "energy": None, "stress": None, "labels": ["giù"], "quote": clause}
                continue
            return {"mood": mood, "energy": energy, "stress": stress, "labels": [label] if label else [],
                    "quote": clause}
    return None


def mood_clauses(text: str) -> list[dict]:
    """Every clause of ``text`` that states how the user feels now, with the lexicon guess. A clause with no subject
    of its own continues the previous first-person one («sono felice ma stanco morto»)."""
    hits: list[dict] = []
    previous_first = False
    for clause in _clauses(text):
        low = clause.lower()
        own = bool(_FIRST_PERSON.search(low))
        hit = _hit(clause)
        if hit is None and not own and previous_first and not _THIRD_PERSON.search(low):
            hit = _hit(f"sono {clause}")
            if hit:
                hit["quote"] = clause
        if hit:
            hits.append(hit)
        previous_first = own if own or _THIRD_PERSON.search(low) else previous_first
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
    norm = lambda v: str(v or "").strip().lower().replace("giu", "giù")  # noqa: E731
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
        return [{"event": "mood.logged", "message": f"Umore segnato: {detail}",
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
        return [{"event": "mood.removed", "message": "Umore tolto", "data": {"detail": "l'ultima voce di oggi"}}]
