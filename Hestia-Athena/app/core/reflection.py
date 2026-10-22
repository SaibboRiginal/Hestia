"""Life reflection («Vita») — the coordinator layer above the modules (docs/work/2026-10-20-riflessione-a-livelli).

The modules judge their own data and publish short signals + weekly metrics (``hestia_common.signals_client``,
Archive ``signals-store``). This track reads ONLY those, never the raw data:

1. read active signals and the weekly series;
2. link series of different domains (Pearson at lag 0 and 1 week, closed weeks only) — numbers, not the model;
3. choose a few topics (strongest links, ``alta``/``attenzione`` signals), skipping what was said recently;
4. ask the owning module for details (``/api/module/context?topic=``);
5. one Oracle call (use case ``athena.riflessione``) → observations / one setting proposal;
6. the runtime gates them; accepted observations are stored (``kind=observation``, ``ref_id=athena``) and reach
   Marko only inside the evening recap («Da tenere d'occhio», ``recap_piece``). Nothing is sent to Hermes.

System health is the other track (``runtime._thinking_cycle``) and never sees this data.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

import requests

from . import athena_settings as S
from .athena_settings import get_float, get_int
from .schemas import ActionCandidate
from .shared_imports import import_shared_symbol
from .strategist import _map_to_action_candidates, _parse_candidates

SignalReader = import_shared_symbol("hestia_common.signals_client", "SignalReader")
iso_week = import_shared_symbol("hestia_common.signals_client", "iso_week")

logger = logging.getLogger("hestia_athena.reflection")

USE_CASE = "athena.riflessione"
SEVERITY_RANK = {"alta": 0, "attenzione": 1, "info": 2}
DOMAIN_WORDS = {"fitness": "Allenamento", "selfcare": "Cura di sé", "finance": "Spese", "wardrobe": "Guardaroba",
                "real_estate": "Case", "cognition": "Hestia"}


def local_day(ts: datetime | None = None) -> str:
    return (ts or datetime.now(timezone.utc)).astimezone().date().isoformat()


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy)


def _next_week(week: str) -> str:
    y, w = week.split("-W")
    return iso_week(date.fromisocalendar(int(y), int(w), 1) + timedelta(weeks=1))


def correlate(series: dict[str, dict], *, min_weeks: int, min_r: float, current_week: str | None = None) -> list[dict]:
    """Links between weekly series of DIFFERENT domains. Lag 0 = same week; lag 1 = ``a`` this week vs ``b`` the
    week after. The current (still open) week is left out. Strongest first, one link per pair (best lag)."""
    current = current_week or iso_week()
    clean = {name: {w: float(v) for w, v in (s.get("values") or {}).items()
                    if w and w != current and isinstance(v, (int, float))}
             for name, s in series.items()}
    names = sorted(clean)
    links: list[dict] = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if series[a].get("domain") == series[b].get("domain"):
                continue
            best = None
            for x, y in ((a, b), (b, a)):
                for lag in (0, 1):
                    if lag == 0 and x != a:
                        continue      # lag 0 is symmetric: count it once
                    pairs = [(clean[x][w], clean[y][w if lag == 0 else _next_week(w)]) for w in sorted(clean[x])
                             if (w if lag == 0 else _next_week(w)) in clean[y]]
                    if len(pairs) < min_weeks:
                        continue
                    r = pearson([p[0] for p in pairs], [p[1] for p in pairs])
                    if r is None or abs(r) < min_r:
                        continue
                    if best is None or abs(r) > abs(best["r"]):
                        best = {"a": x, "b": y, "lag": lag, "r": round(r, 3), "weeks": len(pairs)}
            if best:
                best["key"] = f"link:{best['a']}|{best['b']}|{best['lag']}"
                best["a_label"], best["b_label"] = series[best["a"]].get("label"), series[best["b"]].get("label")
                best["a_domain"], best["b_domain"] = series[best["a"]].get("domain"), series[best["b"]].get("domain")
                best["a_module"], best["b_module"] = series[best["a"]].get("module"), series[best["b"]].get("module")
                links.append(best)
    return sorted(links, key=lambda l: -abs(l["r"]))


def link_text(link: dict) -> str:
    """Caveman line for the prompt and the page: «Allenamenti ↔ Routine rispettate %: r=0.72 su 9 settimane»."""
    when = "stessa settimana" if not link["lag"] else "la settimana dopo"
    return (f"{link['a_label']} → {link['b_label']} ({when}): r={link['r']:+.2f} su {link['weeks']} settimane, "
            f"{'salgono insieme' if link['r'] > 0 else 'uno sale, l altro scende'}")


def choose_topics(signals: list[dict], links: list[dict], told: set[str], max_topics: int) -> list[dict]:
    """Alta signals first, then links (strongest), then attenzione signals; ``info`` only enrich the context."""
    topics: list[dict] = []
    ranked = sorted((s for s in signals if s.get("severity") in ("alta", "attenzione")),
                    key=lambda s: SEVERITY_RANK.get(s.get("severity"), 9))
    alta = [s for s in ranked if s.get("severity") == "alta"]
    rest = [s for s in ranked if s.get("severity") != "alta"]
    for s in alta:
        topics.append({"type": "signal", "key": f"signal:{s.get('module')}:{s.get('key')}", "signal": s})
    for link in links:
        topics.append({"type": "link", "key": link["key"], "link": link})
    for s in rest:
        topics.append({"type": "signal", "key": f"signal:{s.get('module')}:{s.get('key')}", "signal": s})
    out = [t for t in topics if t["key"] not in told]
    return out[:max(1, max_topics)]


def _prompt(topics: list[dict], info: list[dict], details: dict[str, str], settings_lines: list[str],
            max_items: int) -> str:
    lines = []
    for i, t in enumerate(topics, 1):
        if t["type"] == "link":
            lines.append(f"T{i} COLLEGAMENTO: {link_text(t['link'])}")
        else:
            s = t["signal"]
            lines.append(f"T{i} SEGNALE [{DOMAIN_WORDS.get(s.get('domain'), s.get('domain'))}, {s.get('severity')}]: "
                         f"{s.get('text')}")
        if details.get(t["key"]):
            lines.append(f"   dettagli: {details[t['key']]}")
    ctx = "; ".join(f"{DOMAIN_WORDS.get(s.get('domain'), s.get('domain'))}: {s.get('text')}" for s in info[:6])
    return (
        "Sei Athena, mente proattiva di Hestia. Rifletti sulla VITA dell'utente (non sul sistema).\n"
        "Hai solo segnali delle aree e collegamenti calcolati sui numeri. Non inventare numeri.\n"
        f"TEMI:\n" + "\n".join(lines) + "\n"
        + (f"ALTRO: {ctx}\n" if ctx else "")
        + (f"IMPOSTAZIONI (chiave=valore [scelte]): {'; '.join(settings_lines)}\n" if settings_lines else "")
        + f"\nScrivi max {max_items} osservazioni utili, solo se i dati le giustificano.\n"
        "Formato ESATTO per ognuna:\n"
        "AZIONE: <titolo breve>\n"
        "TIPO: observation|setting\n"
        "PRIORITA: low|normal|elevated|high\n"
        "DOMINIO: <area principale, es. fitness>\n"
        "TEMA: T<n>\n"
        "MOTIVO: <perché conta, 1 frase, coi numeri dati>\n"
        "RIASSUNTO: <l'osservazione per l'utente, 1-2 frasi, tono amichevole, dai del tu, mai ordini>\n"
        "Solo per setting (CHIAVE da IMPOSTAZIONI):\nCHIAVE: <chiave>\nVALORE: <nuovo valore>\n\n"
        "Regole:\n"
        "- observation = un fatto + perché conta. Un collegamento non è una causa: dillo con prudenza.\n"
        "- Mai nomi di moduli o servizi: parla di allenamento, spese, cura di sé, guardaroba.\n"
        "- Niente da dire -> scrivi solo: NESSUNA_AZIONE\n"
        "- No testo fuori formato. No markdown. No HTML."
    )


class LifeReflection:
    """One «Vita» cycle. The runtime owns the gate, the setting proposals and the records."""

    def __init__(self, hub_api_url: str, *, gate: Callable[[ActionCandidate], ActionCandidate],
                 propose_setting: Callable[[ActionCandidate, str], bool],
                 settings_lines: Callable[[], list[str]]) -> None:
        self.hub_api_url = hub_api_url.rstrip("/")
        self.reader = SignalReader(self.hub_api_url)
        self._gate = gate
        self._propose_setting = propose_setting
        self._settings_lines = settings_lines
        self._session = requests.Session()

    # ── Hub helpers ──────────────────────────────────────────────────────────
    def _route(self, service: str, method: str, path: str, *, query: dict | None = None, body: Any = None,
               timeout: float = 10) -> tuple[int, Any]:
        resp = self._session.post(
            f"{self.hub_api_url}/route/{service}/{path.lstrip('/')}",
            json={"method": method, "headers": {}, "query": query or {}, "body": body, "timeout_seconds": timeout},
            timeout=timeout + 4)
        resp.raise_for_status()
        routed = resp.json() or {}
        return int(routed.get("status_code", 500)), routed.get("payload")

    def detail(self, module: str, topic: str = "") -> str:
        budget = get_int(S.REFLECTION_DETAIL_BUDGET)
        try:
            status, payload = self._route(module, "GET", "api/module/context",
                                          query={"budget": budget, **({"topic": topic} if topic else {})}, timeout=8)
        except Exception as exc:
            logger.warning("[🔄] event=reflection_detail_failed module=%s topic=%s error=%s fallback=skip",
                           module, topic, exc)
            return ""
        if status >= 400 or not isinstance(payload, dict):
            return ""
        return str(payload.get("text") or "")[:budget]

    def _ask_oracle(self, prompt: str) -> str | None:
        timeout = get_float(S.STRATEGIST_TIMEOUT)
        try:
            status, payload = self._route("oracle", "POST", "api/llm/generate",
                                          body={"prompt": prompt, "use_case": USE_CASE}, timeout=timeout)
        except Exception as exc:
            logger.warning("event=reflection_oracle_failed error=%s", exc)
            return None
        if status >= 400 or not payload:
            logger.warning("event=reflection_oracle_error status_code=%s", status)
            return None
        if isinstance(payload, dict):
            return str(payload.get("response") or payload.get("text") or "")
        return str(payload)

    # ── stored observations (signals-store, ref_id=athena) ───────────────────
    def observations(self, since_days: int = 30) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        try:
            rows = self.reader.rows("observation", ref_id="athena", at_from=since, limit=500)
        except Exception as exc:
            logger.warning("[🔄] event=reflection_observations_read_failed error=%s fallback=empty", exc)
            return []
        return [{**(r.get("data") or {}), "id": r.get("id"), "at": r.get("at")} for r in rows if not r.get("deleted")]

    def _store(self, obs: list[dict]) -> bool:
        if not obs:
            return True
        now = datetime.now(timezone.utc).isoformat()
        rows = [{"kind": "observation", "id": f"athena:{o['id']}", "ref_id": "athena",
                 "parent_id": o.get("domain") or "cognition", "at": now, "data": o, "updated_at": now} for o in obs]
        try:
            status, _ = self._route("archive", "PUT", "api/signals-store/records", body={"rows": rows})
            return status < 400
        except Exception as exc:
            logger.warning("[🔄] event=reflection_store_failed rows=%d error=%s", len(rows), exc)
            return False

    def recap_piece(self, day: str) -> dict:
        """Athena's piece of the daily recap (contract of docs/work/2026-10-20-recap-giornaliero §3.2)."""
        items = [o for o in self.observations(since_days=3) if o.get("day") == day]
        base = {"module": "athena", "title": "Da tenere d'occhio", "icon": "eye", "emoji": "👀", "order": 900}
        if not items:
            return {**base, "empty": True}
        items.sort(key=lambda o: -float(o.get("score") or 0))
        return {**base, "done": [{"text": o.get("text") or o.get("title") or "", "tone": "info"} for o in items]}

    # ── the cycle ────────────────────────────────────────────────────────────
    def run(self, trace_id: str) -> dict[str, Any]:
        """Returns ``{candidates, life, error}``; candidates are already gated and acted on."""
        life: dict[str, Any] = {"signals": [], "links": [], "topics": [], "details": {}}
        try:
            signals = self.reader.signals()
            series = self.reader.series(weeks=26)
        except Exception as exc:
            logger.warning("event=reflection_read_failed error=%s", exc)
            return {"candidates": [], "life": life, "error": f"segnali non leggibili: {exc}"}
        links = correlate(series, min_weeks=get_int(S.REFLECTION_MIN_WEEKS),
                          min_r=get_float(S.REFLECTION_MIN_CORRELATION))
        life["signals"] = [{k: s.get(k) for k in ("module", "domain", "key", "kind", "severity", "text", "page")}
                           for s in signals[:40]]
        life["links"] = links[:10]
        life["series"] = len(series)

        recent = self.observations(since_days=get_int(S.REFLECTION_REPEAT_DAYS))
        told = {o.get("topic_key") for o in recent if o.get("topic_key")}
        today = local_day()
        left = get_int(S.REFLECTION_MAX_PER_DAY) - sum(1 for o in recent if o.get("day") == today)
        topics = choose_topics(signals, links, told, get_int(S.REFLECTION_MAX_TOPICS))
        life["topics"] = [{"key": t["key"], "type": t["type"],
                           "text": link_text(t["link"]) if t["type"] == "link" else t["signal"].get("text")}
                          for t in topics]
        if not topics or left <= 0:
            logger.info("event=reflection_nothing_to_say topics=%d left_today=%d", len(topics), left)
            return {"candidates": [], "life": life, "error": None}

        details: dict[str, str] = {}
        for t in topics:
            if t["type"] == "signal":
                s = t["signal"]
                details[t["key"]] = self.detail(s.get("module"), s.get("topic") or s.get("key"))
            else:
                link = t["link"]
                parts = [self.detail(m) for m in {link.get("a_module"), link.get("b_module")} if m]
                details[t["key"]] = " | ".join(p for p in parts if p)
        life["details"] = details

        modules = {t["signal"].get("module") if t["type"] == "signal" else None for t in topics}
        modules |= {t["link"].get(k) for t in topics if t["type"] == "link" for k in ("a_module", "b_module")}
        settings_lines = [ln for ln in self._settings_lines() if ln.split(".", 1)[0] in modules]
        info = [s for s in signals if s.get("severity") == "info"]
        raw = self._ask_oracle(_prompt(topics, info, details, settings_lines, left))
        if raw is None:
            return {"candidates": [], "life": life, "error": "modello non disponibile"}
        parsed = _parse_candidates(raw)
        candidates = _map_to_action_candidates(parsed)
        stored: list[dict] = []
        for item, cand in zip(parsed, candidates):
            cand.track = "vita"
            topic = None
            tema = str(item.get("tema") or "").strip().upper().lstrip("T")
            if tema.isdigit() and 1 <= int(tema) <= len(topics):
                topic = topics[int(tema) - 1]
            cand.topic_key = topic["key"] if topic else None
            if cand.kind not in ("observation", "setting"):
                cand.kind = "observation"
            self._gate(cand)
            if not cand.accepted:
                continue
            if cand.kind == "setting":
                cand.outcome = "setting_proposed" if self._propose_setting(cand, trace_id) else "setting_skipped"
                continue
            if len(stored) >= left or (cand.topic_key and cand.topic_key in told):
                cand.outcome = "discarded"
                cand.gate_reason += " · già detto o limite del giorno"
                continue
            sig = topic.get("signal") if topic and topic["type"] == "signal" else {}
            link = topic.get("link") if topic and topic["type"] == "link" else {}
            stored.append({
                "id": uuid4().hex[:16], "day": today, "title": cand.title, "text": cand.summary,
                "reasoning": cand.reasoning, "domain": cand.domain, "topic_key": cand.topic_key,
                "domains": sorted({d for d in (sig.get("domain"), link.get("a_domain"), link.get("b_domain")) if d}),
                "page": sig.get("page") or "", "module": sig.get("module") or "", "link": link or None,
                "score": cand.score, "trace_id": trace_id})
            if cand.topic_key:
                told.add(cand.topic_key)
            cand.outcome = "observed"
        if not self._store(stored):
            for cand in candidates:
                if cand.outcome == "observed":
                    cand.outcome = "failed"
        logger.info("event=reflection_done topics=%d candidates=%d observed=%d trace_id=%s", len(topics),
                    len(candidates), len(stored), trace_id)
        return {"candidates": candidates, "life": life, "error": None}
