#!/usr/bin/env python3
"""Real-run flows on the cloud test bench: what Marko would do by hand, driven through the real doors.

  python tools/cloud_test.py flows            # after `all` (stack up): every flow, report + screenshots
  python tools/cloud_test.py flows hygieia    # only the named areas (hercules hygieia wardrobe hermes …)

Doors used, like the clients do:
- module APIs through the WebUI plugin proxy  (/api/webui/plugins/<module>/call/<path> → Hub → module → Archive)
- chat through Oracle /api/chat with the fake LLM's scripted tools (`#tool name {args}`) → Hestia-MCP → module
- notifications through the WebUI inbox (/api/webui/notifications → Hermes) and its answer buttons
- pages through Chromium (Playwright) on the real WebUI, desk and phone
Every run creates its own data with a «Banco» prefix; nothing is deleted from the volumes.
Output: .cloud-test/flows.md + .cloud-test/flows/*.png. SPEC: docs/work/2026-10-19-prove-reali-banco/SPEC.md
"""
from __future__ import annotations

import base64
import json
import re
import struct
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".cloud-test"
SHOTS = OUT / "flows"
WEBUI = "http://localhost:19015"
ORACLE = "http://localhost:19004"
HUB = "http://localhost:19001"
THEMIS = "http://localhost:19016"
MCP = "http://localhost:19013"
RUN = datetime.now().strftime("%H%M%S")
TODAY = date.today()


# ── plumbing ─────────────────────────────────────────────────────────────────

def http(method: str, url: str, body=None, timeout: float = 30.0, headers: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw, status = resp.read().decode("utf-8", "replace"), resp.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read().decode("utf-8", "replace"), exc.code
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(exc)
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


class Fail(Exception):
    pass


def need(cond, msg: str):
    if not cond:
        raise Fail(msg)
    return cond


def api(module: str, method: str, path: str, body=None, query: dict | None = None, ok: tuple = (200, 201)):
    """Call a module like its WebUI plugin does (host.api)."""
    url = f"{WEBUI}/api/webui/plugins/{module}/call/{path.lstrip('/')}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    code, out = http(method, url, body)
    if ok and code not in ok:
        raise Fail(f"{method} {path} → {code} {str(out)[:300]}")
    return out


def hub(service: str, method: str, path: str, body=None, query: dict | None = None) -> tuple[int, object]:
    """Service → service door (what a module does): POST {HUB}/api/route/<svc>/<path> with the envelope."""
    env = {"method": method, **({"body": body} if body is not None else {}), **({"query": query} if query else {})}
    code, out = http("POST", f"{HUB}/api/route/{service}/{path.lstrip('/')}", env)
    if code != 200 or not isinstance(out, dict):
        return code, out
    return out.get("status_code", 0), out.get("payload")


def chat(message: str, session: str = "", mode: str = "") -> dict:
    """Oracle chat (NDJSON). Returns {reply, tools:[{tool, ok, preview}], events}."""
    body = {"message": message, "session_id": session or f"banco-{RUN}", "client": "webui"}
    if mode:
        body["mode"] = mode
    req = urllib.request.Request(f"{ORACLE}/api/chat", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    events = []
    with opener.open(req, timeout=180) as resp:
        for line in resp:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    final = next((e for e in reversed(events) if e.get("type") == "final"), {})
    tools = [{"tool": e.get("tool"), "ok": (e.get("metadata") or {}).get("ok"), "preview": e.get("content", "")}
             for e in events if e.get("type") == "thinking" and e.get("action") == "tool_result"]
    return {"reply": final.get("reply", ""), "tools": tools, "events": events}


def inbox(source: str = "", filter_: str = "all", limit: int = 50) -> list[dict]:
    q = {"filter": filter_, "limit": limit, **({"source": source} if source else {})}
    code, out = http("GET", f"{WEBUI}/api/webui/notifications?" + urllib.parse.urlencode(q))
    need(code == 200, f"inbox → {code} {str(out)[:200]}")
    return out.get("items", out) if isinstance(out, dict) else out


def answer(nid: str, action_id: str) -> tuple[int, object]:
    return http("POST", f"{WEBUI}/api/webui/notifications/{nid}/answer", {"actionId": action_id})


def png(color=(200, 60, 60), size=64) -> str:
    """A small solid PNG as data URL (a 'photo' for pieces and products)."""
    raw = b"".join(b"\x00" + bytes(color) * size for _ in range(size))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(data).decode()


# ── report ───────────────────────────────────────────────────────────────────

RESULTS: list[dict] = []


def step(area: str, name: str):
    """Decorator-ish runner: step(area, name)(fn) → records ok/fail/detail; returns fn's value or None."""
    def run(fn):
        t0 = time.time()
        try:
            out = fn()
            detail = out if isinstance(out, str) else ""
            RESULTS.append({"area": area, "name": name, "ok": True, "detail": detail, "ms": int((time.time() - t0) * 1000)})
            print(f"✅ [{area}] {name} {detail[:160]}", flush=True)
            return out
        except Exception as exc:  # noqa: BLE001 — a failing step is a finding, never a crash
            msg = str(exc) if isinstance(exc, Fail) else f"{exc.__class__.__name__}: {exc}"
            if not isinstance(exc, Fail):
                traceback.print_exc()
            RESULTS.append({"area": area, "name": name, "ok": False, "detail": msg[:600], "ms": int((time.time() - t0) * 1000)})
            print(f"❌ [{area}] {name}: {msg[:400]}", flush=True)
            return None
    return run


def write_report(notes: list[str]) -> Path:
    lines = [f"# Prove reali sul banco — {datetime.now():%Y-%m-%d %H:%M}", "",
             f"Passi: {sum(r['ok'] for r in RESULTS)} ✅ · {sum(not r['ok'] for r in RESULTS)} ❌", ""]
    area = None
    for r in RESULTS:
        if r["area"] != area:
            area = r["area"]
            lines += ["", f"## {area}", ""]
        lines.append(f"- {'✅' if r['ok'] else '❌'} {r['name']}" + (f" — {r['detail']}" if r["detail"] else ""))
    if notes:
        lines += ["", "## Note", ""] + [f"- {n}" for n in notes]
    OUT.mkdir(exist_ok=True)
    path = OUT / "flows.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ── Hercules (Allenamento) ───────────────────────────────────────────────────

def flow_hercules(ctx: dict) -> None:
    A = "Allenamento (Hercules)"
    M = "hercules"

    def pick(q: str) -> str:
        items = api(M, "GET", "api/hercules/exercises", query={"q": q, "limit": 5})["items"]
        return need(items, f"esercizio «{q}» non trovato")[0]["id"]

    def template():
        bench, row = pick("panca piana"), pick("rematore")
        t = api(M, "POST", "api/hercules/templates", {"name": f"Banco Push {RUN}", "favorite": True, "items": [
            {"exercise_id": bench, "rest_seconds": 120, "sets": [{"reps_min": 6, "reps_max": 8, "weight_kg": 60}] * 3},
            {"exercise_id": row, "sets": [{"reps_min": 8, "reps_max": 12}] * 3}]})
        ctx["tpl"], ctx["bench"], ctx["row"] = t["id"], bench, row
        need(len(t.get("items") or []) == 2, f"scheda con {len(t.get('items') or [])} voci")
        return f"scheda {t['name']} con 2 esercizi"
    act = api(M, "GET", "api/hercules/sessions/active")["session"]
    if act:   # a previous run left one open: the real UI would offer «Riprendi» or «Scarta»
        api(M, "POST", f"api/hercules/sessions/{act['id']}/discard")
    step(A, "Crea una scheda (2 esercizi, 3 serie)")(template)
    if "tpl" not in ctx:
        return

    def session():
        s = api(M, "POST", "api/hercules/sessions", {"template_id": ctx["tpl"]})
        sid = s.get("id") or s.get("session", {}).get("id")
        need(sid, f"nessun id sessione: {str(s)[:200]}")
        ctx["sid"] = sid
        for w, r in ((60, 8), (60, 8), (62.5, 6)):
            api(M, "POST", f"api/hercules/sessions/{sid}/sets", {"exercise_id": ctx["bench"], "weight_kg": w, "reps": r})
        for r in (10, 10, 9):
            api(M, "POST", f"api/hercules/sessions/{sid}/sets", {"exercise_id": ctx["row"], "weight_kg": 40, "reps": r})
        act = api(M, "GET", "api/hercules/sessions/active")["session"]
        need(act and act["id"] == sid, "la sessione attiva non è quella appena iniziata")
        fin = api(M, "POST", f"api/hercules/sessions/{sid}/finish", {"perceived_effort": 7})
        det = api(M, "GET", f"api/hercules/sessions/{sid}")
        sets = sum(len(b.get("sets") or []) for b in det.get("blocks") or [])
        need(sets == 6, f"serie salvate {sets} invece di 6")
        need(det.get("status") == "done", f"stato {det.get('status')}")
        return f"6 serie salvate, sessione chiusa: {str(det.get('summary'))[:120]} · PR {len(det.get('prs') or [])}"
    step(A, "Allenamento live: inizia, 6 serie, chiudi")(session)

    def last_time():
        det = api(M, "GET", f"api/hercules/exercises/{ctx['bench']}")
        hist = json.dumps(det)[:20000]
        need("62.5" in hist or "62,5" in hist, "il dettaglio esercizio non mostra la serie da 62.5 kg")
        t = api(M, "GET", f"api/hercules/templates/{ctx['tpl']}")
        text = json.dumps(t)
        need("last" in text or "suggest" in text, "la scheda non porta «l'ultima volta» o suggerimenti")
        return "dettaglio esercizio e scheda con ultima volta/suggerimento"
    step(A, "«L'ultima volta» e suggerimento per la prossima")(last_time)

    def records():
        r = api(M, "GET", "api/hercules/records", query={"exercise_id": ctx["bench"]})
        st = api(M, "GET", "api/hercules/stats", query={"per": "week", "count": 4})
        need(r, "nessun record")
        return f"record panca: {str(r)[:120]} · stats chiavi {sorted(st)[:6]}"
    step(A, "Record e statistiche")(records)

    def offline_sync():
        boot = api(M, "GET", "api/hercules/bootstrap", query={"days": 30})
        cursor = boot.get("cursor") or 0
        sid = f"bancooffline{RUN}"
        started = datetime.now().astimezone().replace(microsecond=0).isoformat()
        ops = [{"op_id": "o0", "kind": "session", "id": sid,
                "fields": {"name": "Banco offline", "status": "active", "started_at": started, "template_id": ctx["tpl"],
                         "exercises": [{"id": "se1", "exercise_id": ctx["bench"], "position": 0}]}}]
        for i in range(3):
            ops.append({"op_id": f"o{i + 1}", "kind": "set", "id": f"{sid}s{i}", "fields": {
                "session_id": sid, "session_exercise_id": "se1", "exercise_id": ctx["bench"], "weight_kg": 50,
                "reps": 10, "position": i, "completed": True}})
        out1 = api(M, "POST", "api/hercules/sync", {"device_id": "banco-phone", "cursor": cursor, "ops": ops})
        out2 = api(M, "POST", "api/hercules/sync", {"device_id": "banco-phone", "cursor": cursor, "ops": ops})  # retry
        api(M, "POST", f"api/hercules/sessions/{sid}/finish", {})
        det = api(M, "GET", f"api/hercules/sessions/{sid}")
        sets = sum(len(b.get("sets") or []) for b in det.get("blocks") or [])
        need(sets == 3, f"dopo due sync uguali le serie sono {sets} (attese 3: niente duplicati)")
        return f"sync applicate {str(out1.get('applied', out1))[:60]} / ripetuta {str(out2.get('applied', out2))[:60]}, 3 serie, nessun duplicato"
    step(A, "Offline → online: sync ripetuta senza duplicati")(offline_sync)

    def quick():
        chips = api(M, "GET", "api/hercules/quick/templates")
        items = chips.get("items", chips) if isinstance(chips, dict) else chips
        need(any(c.get("id") == ctx["tpl"] for c in items), "la scheda preferita non è tra i chip della Home")
        out = api(M, "POST", f"api/hercules/quick/{ctx['tpl']}", {})
        api(M, "DELETE", f"api/hercules/quick/{ctx['tpl']}")
        return f"«{out.get('label')}» e Annulla"
    step(A, "Home: «Segna fatto» con un tocco + Annulla")(quick)

    def adapt_chat():
        r = chat("Oggi sono a pezzi e ho 30 minuti #tool fitness_adapt_today "
                 + json.dumps({"energy": 1, "time_minutes": 30, "template_id": ctx["tpl"]}))
        need(r["tools"] and r["tools"][0]["tool"] == "fitness_adapt_today", f"strumenti chiamati: {r['tools']}")
        need(r["tools"][0]["ok"], f"fitness_adapt_today fallito: {r['tools'][0]['preview'][:300]}")
        prev = r["tools"][0]["preview"]
        ctx["adapt_preview"] = prev
        return f"piano adattato: {prev[:200]}"
    step(A, "Chat «sono a pezzi, 30 minuti» → fitness_adapt_today")(adapt_chat)

    def apply_restore():
        ad = api(M, "POST", "api/hercules/adapt", {"energy": 1, "time_minutes": 30, "template_id": ctx["tpl"]})
        aid = need(ad.get("id") or ad.get("adaptation_id"), f"nessun id adattamento: {str(ad)[:200]}")
        ap = api(M, "POST", f"api/hercules/adapt/{aid}/apply")
        sid = ap.get("session_id") or ap.get("id")
        planned = sum(len(e.get("planned") or []) for e in ap.get("exercises") or [] if not e.get("skipped"))
        rs = api(M, "POST", "api/hercules/restore", {"session_id": sid})
        restored = sum(len(e.get("planned") or []) for e in rs.get("exercises") or [] if not e.get("skipped"))
        need(restored > planned, f"«ripristina» non rimette le serie tolte: {planned} → {restored}")
        api(M, "POST", f"api/hercules/sessions/{sid}/discard")
        need(not rs.get("adaptation_id"), "dopo «ripristina» la sessione è ancora adattata")
        return f"serie pianificate: adattata {planned} → ripristinata {restored}"
    step(A, "Adattamento: applica e «ripristina»")(apply_restore)

    def body_goal():
        api(M, "POST", "api/hercules/measurements", {"kind": "bodyweight", "value": 78.4})
        g = api(M, "POST", "api/hercules/goals", {"scope": "any", "times": 3, "per": "week", "label": "Banco 3/settimana"})
        s = api(M, "GET", "api/hercules/summary")
        return f"peso + obiettivo {g.get('label')} · riepilogo: {s.get('text', '')[:100]}"
    step(A, "Peso, obiettivo «3 volte a settimana», riepilogo")(body_goal)


# ── Hygieia (Self care) ──────────────────────────────────────────────────────

def flow_hygieia(ctx: dict) -> None:
    A = "Self care (Hygieia)"
    M = "hygieia"
    P = "api/selfcare"

    def products():
        t0 = time.time()
        cleanser = api(M, "POST", f"{P}/products", {"name": f"Banco Detergente schiumoso {RUN}", "brand": "CeraVe",
                                                    "areas": ["viso"], "category": "detergente", "size": 236,
                                                    "pao_months": 12, "status": "in_use"})
        secs = time.time() - t0
        need(cleanser.get("opened_at") == TODAY.isoformat(), f"opened_at {cleanser.get('opened_at')} (atteso oggi)")
        need(cleanser.get("expires_at") or cleanser.get("pao_expires_at") or "pao" in json.dumps(cleanser),
             "nessun conto alla rovescia PAO")
        ret = api(M, "POST", f"{P}/products", {"name": f"Banco Siero retinolo {RUN}", "brand": "Banco", "areas": ["viso"],
                                               "category": "siero", "actives": ["retinolo"], "status": "in_use"})
        aha = api(M, "POST", f"{P}/products", {"name": f"Banco Tonico glicolico {RUN}", "brand": "Banco", "areas": ["viso"],
                                               "category": "tonico", "actives": ["aha_glicolico"], "status": "in_use"})
        ctx.update(cleanser=cleanser["id"], retinol=ret["id"], aha=aha["id"])
        return f"3 prodotti; il primo salvato in {secs:.1f} s con apertura oggi e PAO 12 mesi"
    step(A, "Aggiungi prodotti (detergente con PAO, retinolo, AHA)")(products)
    if "retinol" not in ctx:
        return

    def routine():
        r = api(M, "POST", f"{P}/routines", {"name": f"Banco Viso sera {RUN}", "areas": ["viso"], "slot": "evening",
                                             "cadence": {"mode": "daily"}, "reminder": True, "steps": [
            {"product_id": ctx["cleanser"]},
            {"product_id": ctx["retinol"], "cadence": {"mode": "target", "times": 3, "per": "week"}},
            {"product_id": ctx["aha"], "cadence": {"mode": "target", "times": 1, "per": "week"}}]})
        ctx["routine"] = r["id"]
        warn = json.dumps(r.get("warnings") or r.get("conflicts") or r.get("check") or "")
        ck = api(M, "GET", f"{P}/check", query={"routine_id": r["id"]})
        text = json.dumps(ck, ensure_ascii=False)
        need("AHA" in text or "aha" in text, f"selfcare_check non avvisa retinolo+AHA: {text[:300]}")
        return f"routine con 3 passi; avviso: {(warn if warn not in ('""', '[]') else text)[:160]}"
    step(A, "Routine «Viso sera»: retinolo 3/sett, AHA 1/sett, avviso conflitto")(routine)
    if "routine" not in ctx:
        return

    def retinol_evening():
        api(M, "POST", f"{P}/routines/{ctx['routine']}/done", {"steps": None})
        plan = api(M, "GET", f"{P}/routines/{ctx['routine']}/plan", query={"date": TODAY.isoformat()})
        text = json.dumps(plan, ensure_ascii=False)
        steps = plan.get("steps") or []
        aha = next((s for s in steps if (s.get("product") or {}).get("id") == ctx["aha"]), {})
        need(aha, f"passo AHA assente nel piano: {text[:300]}")
        need(not aha.get("include") and "retinolo" in (aha.get("reason") or ""),
             f"AHA: include={aha.get('include')} stato={aha.get('state')} motivo «{aha.get('reason')}»")
        return f"AHA dopo la sera col retinolo: {aha.get('state')} · {aha.get('reason') or aha.get('hint')}"
    step(A, "Dopo la sera col retinolo l'AHA dice «non oggi»")(retinol_evening)

    def versions():
        old = api(M, "GET", f"{P}/routines/{ctx['routine']}")
        api(M, "PUT", f"{P}/routines/{ctx['routine']}", {"steps": (old.get("steps") or [])[:2], "reason": "banco: tolgo AHA"})
        new = api(M, "GET", f"{P}/routines/{ctx['routine']}")
        vers = new.get("versions") or new.get("history") or []
        per = api(M, "GET", f"{P}/period", query={"date": TODAY.isoformat()})
        need(len(vers) >= 2 or new.get("version", 1) >= 2, f"nessuna nuova versione: {json.dumps(new)[:300]}")
        api(M, "POST", f"{P}/routines/{ctx['routine']}/undo")
        return f"versioni {len(vers) or new.get('version')}, periodo di oggi: {str(per)[:100]}; annullata"
    step(A, "Modificare la routine crea una versione (+ «come era» nel periodo, annulla)")(versions)

    def quick_and_streak():
        chips = api(M, "GET", f"{P}/quick/routines")
        items = chips.get("items", chips) if isinstance(chips, dict) else chips
        need(any(c.get("id") == ctx["routine"] for c in items), f"routine non tra i chip della Home: {str(items)[:200]}")
        out = api(M, "POST", f"{P}/quick/product/{ctx['cleanser']}", {})
        api(M, "DELETE", f"{P}/quick/product/{ctx['cleanser']}")
        st = api(M, "GET", f"{P}/stats", query={"days": 30})
        return f"«{out.get('label')}» + Annulla; stats chiavi {sorted(st)[:6]}"
    step(A, "Home: un tocco su prodotto e routine, Annulla, statistiche")(quick_and_streak)

    def tools_chat():
        r = chat("cosa uso stasera? #tool selfcare_today {}")
        need(r["tools"] and r["tools"][0]["ok"], f"selfcare_today: {r['tools']}")
        r2 = chat("ho finito il detergente #tool selfcare_product_update "
                  + json.dumps({"product": ctx["cleanser"], "status": "finished"}))
        need(r2["tools"] and r2["tools"][0]["ok"], f"selfcare_product_update: {r2['tools'][:1]}")
        p = api(M, "GET", f"{P}/products/{ctx['cleanser']}")
        need(p.get("status") == "finished", f"dopo la chat il detergente è «{p.get('status')}»")
        shop = api(M, "GET", f"{P}/shopping")
        in_shop = ctx["cleanser"] in json.dumps(shop)
        return f"stasera: {r['tools'][0]['preview'][:90]} · detergente finito (UI: {p.get('status')}), lista spesa: {in_shop}"
    step(A, "Chat «cosa uso stasera?» / «ho finito il detergente» → strumenti → UI")(tools_chat)

    def reminder_chain():
        code, _ = http("PUT", f"{THEMIS}/api/settings/key/hygieia.reminder.enabled", {"value": True, "actor": "banco"})
        need(code == 200, f"Themis non accetta hygieia.reminder.enabled → {code}")
        r = api(M, "POST", f"{P}/routines", {"name": f"Banco Crema mani {RUN}", "areas": ["mani"], "slot": "anytime",
                                             "cadence": {"mode": "daily"}, "reminder": True,
                                             "steps": [{"label": "crema mani"}]})
        ctx["hands"] = r["id"]
        key = f"selfcare.reminder.{r['id']}"
        out = api(M, "POST", f"{P}/reminders/run")
        mine = [i for i in out.get("items", []) if i.get("routine_id") == r["id"]]
        need(mine and mine[0].get("send"), f"il job non manda il promemoria per una routine giornaliera da fare: {out}")
        again = api(M, "POST", f"{P}/reminders/run")
        twice = [i for i in again.get("items", []) if i.get("routine_id") == r["id"]]
        need(twice and not twice[0].get("send"), f"secondo giro nello stesso giorno: {twice}")
        time.sleep(2)
        live = [n for n in inbox() if r["id"] in json.dumps(n.get("link") or {})]
        need(len(live) == 1, f"notifiche per la routine nell'inbox WebUI: {len(live)}")
        ctx["hands_key"], ctx["hands_note"] = key, live[0]
        return f"1 promemoria inviato, il secondo giro dice «{twice[0].get('why')}», 1 notifica nell'inbox WebUI"
    step(A, "Promemoria (interruttore acceso in Themis): un invio al giorno, notifica nella WebUI")(reminder_chain)
    if "hands_key" in ctx:
        hermes_chain(A, M, ctx["hands"], ctx["hands_key"], ctx["hands_note"])


def hermes_chain(A: str, module: str, rid: str, key: str, first: dict) -> None:
    """Hermes `replaces` (SPEC 2026-10-17-hermes-repeat-notifications §4) on a real module reminder: the next two
    days are emulated by sending the same thread again through the Hub, as the module job would."""
    from_module = {"event_type": "service.action_required", "domain": "system", "entity_id": key, "payload": {
        "kind": "selfcare.reminder", "service": module, "source": module, "domain": "selfcare", "_source": module,
        "_title": "Self care", "target": "owner", "replaces": key, "level": "info", "_message": first.get("message"),
        "_actions": [
            {"id": "done", "label": "Fatto", "style": "primary", "service": module, "method": "POST",
             "path": f"/api/selfcare/quick/routine/{rid}", "body": {"source": "reminder_button"}, "resolves": True},
            {"id": "skip", "label": "Salta", "service": module, "method": "POST",
             "path": f"/api/selfcare/routines/{rid}/skip", "body": {"source": "reminder_button"}}],
        "_link": {"module": module, "page": f"routine/{rid}"}}}

    def three_days():
        for _ in range(2):
            code, out = hub("hermes", "POST", "api/events/ingest", from_module)
            need(code == 200, f"ingest → {code} {str(out)[:200]}")
            time.sleep(1)
        live = [n for n in inbox() if rid in json.dumps(n.get("link") or {}) and n.get("pending")]
        need(len(live) == 1, f"notifiche vive {len(live)} (attesa 1)")
        rep = json.dumps(live[0].get("repeat"), ensure_ascii=False)
        need("2" in rep, f"contatore «saltato» assente: repeat={rep}")
        code, out = answer(first["id"], "done")
        need(code == 409, f"il bottone sulla notifica sostituita risponde {code} (atteso 409): {str(out)[:200]}")
        hermes_chain.live = live[0]
        return f"1 notifica viva, repeat={rep}; bottone sulla vecchia → 409"
    step(A, "Hermes: stesso promemoria per 3 giorni → una notifica «Saltato 2 volte», la vecchia dice «già sostituita»")(three_days)
    live = getattr(hermes_chain, "live", None)
    if not live:
        return

    def done_button():
        code, out = answer(live["id"], "done")
        need(code == 200, f"Fatto → {code} {str(out)[:300]}")
        logs = api(module, "GET", "api/selfcare/logs", query={"routine_id": rid, "days": 2})["items"]
        need(any(l.get("status") == "done" for l in logs), "dopo «Fatto» la routine non risulta fatta oggi")
        code, _ = hub("hermes", "POST", "api/events/ingest", from_module)
        time.sleep(1)
        fresh = [n for n in inbox() if rid in json.dumps(n.get("link") or {}) and n.get("pending")]
        need(len(fresh) == 1 and not fresh[0].get("repeat"), f"dopo Fatto la catena non riparte da zero: {fresh[:1]}")
        return f"«Fatto» eseguito dal modulo ({str(out)[:80]}), routine fatta, il promemoria dopo riparte da zero"
    step(A, "Hermes: «Fatto» chiude la catena e registra la routine")(done_button)


# ── Guardaroba (Wardrobe) ────────────────────────────────────────────────────

def flow_wardrobe(ctx: dict) -> None:
    A = "Guardaroba (Wardrobe)"
    M = "wardrobe"
    P = "api/wardrobe"

    def pieces():
        made = {}
        spec = [("shirt", "Camicia azzurra", ["azzurro"], 2, 3, ["ufficio"], (120, 170, 230)),
                ("polo", "Polo bianca", ["bianco"], 2, 2, ["casual"], (240, 240, 240)),
                ("longsleeve", "Maglia righe", ["blu"], 2, 2, ["ufficio"], (60, 80, 160)),
                ("trousers", "Pantaloni grigi lana", ["grigio"], 3, 4, ["ufficio"], (120, 120, 120)),
                ("sweater", "Maglione blu scuro", ["blu"], 4, 3, ["ufficio", "casual"], (20, 30, 80)),
                ("raincoat", "Impermeabile nero", ["nero"], 3, 3, ["ufficio", "casual"], (10, 10, 10)),
                ("coat", "Cappotto pesante antracite", ["grigio"], 5, 4, ["ufficio"], (50, 50, 55)),
                ("boots", "Stivaletti marroni", ["marrone"], 3, 3, ["ufficio", "casual"], (110, 70, 30)),
                ("sandals", "Sandali estivi", ["beige"], 1, 1, ["casual"], (230, 210, 170))]
        for cat, name, colors, warmth, formality, occ, rgb in spec:
            seasons = ["summer"] if cat == "sandals" else ["autumn", "winter", "spring"]
            body = {"name": f"Banco {name} {RUN}", "category": cat, "colors": colors, "warmth": warmth,
                    "formality": formality, "occasions": occ, "seasons": seasons,
                    **({"weather": {"rain_ok": cat != "sandals"}} if cat in ("raincoat", "boots", "sandals") else {})}
            if cat == "shirt":
                body["photo"] = {"name": "camicia.png", "mime": "image/png", "data_b64": png(rgb).split(",", 1)[1]}
            made[cat] = api(M, "POST", f"{P}/pieces", body)
        ctx["w"] = {k: v["id"] for k, v in made.items()}
        shirt = made["shirt"]
        need(shirt.get("photos"), f"la camicia non ha la foto: {str(shirt)[:200]}")
        ph = shirt["photos"][0]
        pid = ph.get("id") if isinstance(ph, dict) else ph
        code = http("GET", f"{WEBUI}/api/webui/plugins/wardrobe/image?" + urllib.parse.urlencode(
            {"path": f"{P}/files/{pid}?size=thumb"}))[0]
        need(code == 200, f"la miniatura via WebUI risponde {code}")
        return f"{len(made)} capi in pochi secondi, la camicia con foto (miniatura servita dalla WebUI)"
    step(A, "Aggiungi capi (uno con foto) e vedi la miniatura")(pieces)
    if "w" not in ctx:
        return
    w = ctx["w"]

    def filters():
        found = api(M, "GET", f"{P}/pieces", query={"category": "shirt", "season": "autumn", "q": "azzurra"})
        need(any(i["id"] == w["shirt"] for i in found.get("items") or []), "filtro categoria/stagione/testo non trova la camicia")
        sem = chat("trova la giacca pesante scura #tool wardrobe_search " + json.dumps({"query": "giacca pesante scura"}))
        need(sem["tools"] and sem["tools"][0]["ok"], f"wardrobe_search: {sem['tools'][:1]}")
        hit = f"Cappotto pesante antracite {RUN}" in sem["tools"][0]["preview"]
        return f"filtri ok · ricerca semantica via chat eseguita; trova il cappotto: {hit} (con il LLM finto gli embedding sono casuali)"
    step(A, "Filtri e ricerca «giacca pesante scura» (chat → wardrobe_search)")(filters)

    def suggest():
        api(M, "PATCH", f"{P}/pieces/{w['coat']}", {"status": "laundry"})
        out = api(M, "POST", f"{P}/suggest", {"occasion": "ufficio", "temp_c": 8, "rain": True, "count": 3,
                                              "date": (TODAY + timedelta(days=1)).isoformat()})
        items = out.get("items") or out.get("suggestions") or []
        need(len(items) == 3, f"{len(items)} proposte invece di 3: {str(out)[:300]}")
        need(out.get("occasion") == "office", f"«ufficio» non diventa l'occasione «office» del vocabolario: {out.get('occasion')}")
        text = json.dumps(items, ensure_ascii=False)
        need(w["coat"] not in text, "suggerito il cappotto che è in lavanderia")
        need(w["sandals"] not in text, "suggeriti i sandali estivi con 8 gradi e pioggia")
        why = items[0].get("reasons") or items[0].get("why") or ""
        r = chat("Cosa mi metto domani per ufficio, 8 gradi, pioggia #tool wardrobe_suggest "
                 + json.dumps({"occasion": "ufficio", "temp_c": 8, "rain": True}))
        need(r["tools"] and r["tools"][0]["ok"], f"wardrobe_suggest dalla chat: {r['tools'][:1]}")
        api(M, "PATCH", f"{P}/pieces/{w['coat']}", {"status": "active"})
        return f"{len(items)} proposte senza lavanderia né sandali; motivi: {str(why)[:120]}"
    step(A, "«Cosa mi metto domani, ufficio, 8 gradi, pioggia» (API e chat)")(suggest)

    def outfit_and_worn():
        o = api(M, "POST", f"{P}/outfits", {"name": f"Banco Ufficio pioggia {RUN}", "rating": 4, "favorite": True,
                                            "slots": [{"slot": "top", "piece_id": w["shirt"]},
                                                      {"slot": "mid", "piece_id": w["sweater"]},
                                                      {"slot": "outer", "piece_id": w["raincoat"]},
                                                      {"slot": "bottom", "piece_id": w["trousers"]},
                                                      {"slot": "shoes", "piece_id": w["boots"]}]})
        ctx["outfit"] = o["id"]
        chips = api(M, "GET", f"{P}/quick/outfits")
        items = chips.get("items", chips) if isinstance(chips, dict) else chips
        need(any(c.get("id") == o["id"] for c in items), f"l'outfit preferito non è tra i chip della Home: {str(items)[:200]}")
        out = api(M, "POST", f"{P}/quick/{o['id']}", {})
        shirt = api(M, "GET", f"{P}/pieces/{w['shirt']}")
        need(str(shirt.get("last_worn") or shirt.get("stats", {}).get("last_worn") or "").startswith(TODAY.isoformat()),
             f"la camicia non risulta indossata oggi: {str({k: shirt.get(k) for k in ('last_worn', 'stats')})[:200]}")
        return f"outfit di 5 capi, «{out.get('label', out)}» con un tocco, ultimo uso aggiornato"
    step(A, "Outfit per posizione, «Indossato» con un tocco dalla Home")(outfit_and_worn)

    def donate():
        api(M, "PATCH", f"{P}/pieces/{w['raincoat']}", {"status": "donated"})
        o = api(M, "GET", f"{P}/outfits/{ctx['outfit']}")
        flag = json.dumps(o, ensure_ascii=False)
        need(o.get("complete") is False, f"l'outfit non è «da rivedere» (complete={o.get('complete')}): {flag[:200]}")
        return "outfit segnato «da rivedere» dopo aver donato l'impermeabile"
    step(A, "Donare un capo segna i suoi outfit «da rivedere»")(donate)

    def stats_and_packing():
        st = api(M, "GET", f"{P}/stats")
        need(st, "statistiche vuote")
        pk = api(M, "POST", f"{P}/collections/packing", {"name": f"Banco Milano {RUN}", "from": TODAY.isoformat(),
                                                         "to": (TODAY + timedelta(days=2)).isoformat(),
                                                         "occasion": "ufficio", "temp_c": 9, "rain": True})
        n = len(pk.get("piece_ids") or pk.get("items") or [])
        need(n >= 3, f"valigia con {n} capi: {str(pk)[:300]}")
        code, mc = http("GET", "http://localhost:19017/api/module/context")
        return f"stats chiavi {sorted(st)[:6]} · valigia con {n} voci · contesto: {str((mc or {}).get('text', mc))[:90]}"
    step(A, "Statistiche, valigia per 3 giorni, contesto per l'assistente")(stats_and_packing)


# ── Sistema: agenda, presenza, impostazioni, plugin, MCP esterno ─────────────

def setting(key: str, value) -> tuple[int, object]:
    """Like the WebUI settings panel (actor = webui)."""
    return http("PUT", f"{WEBUI}/api/webui/central-settings/key/{key}", {"value": value})


def flow_agenda(ctx: dict) -> None:
    A = "Promemoria e agenda (Chronos)"

    def registered():
        items = api("chronos", "GET", "api/agenda/items")["items"]
        keys = {i["key"] for i in items}
        want = {"hercules.reminder", "hygieia.planner", "hygieia.alerts", "wardrobe.reminder", "wardrobe.review"}
        need(want <= keys, f"mancano nell'agenda: {sorted(want - keys)}")
        return f"{len(items)} regole; i moduli nuovi hanno registrato {', '.join(sorted(want))}"
    step(A, "I moduli registrano i loro job nell'agenda dell'assistente")(registered)

    def run_now():
        out = api("chronos", "POST", "api/agenda/items/hygieia.planner/run")
        time.sleep(3)
        runs = api("chronos", "GET", "api/agenda/runs", query={"owner": "hygieia", "limit": 5})
        rows = runs.get("items") or runs.get("runs") or []
        need(rows, f"nessuna esecuzione registrata: {str(runs)[:300]}")
        last = rows[0]
        need(last.get("status") == "ok", f"ultima esecuzione hygieia: {str(last)[:300]}")
        return f"«Esegui ora» → {str(out)[:80]}; esecuzione {last.get('key') or last.get('item_key')} {last.get('status')}"
    step(A, "«Esegui ora» di hygieia.planner da Chronos → esecuzione ok")(run_now)


def flow_presence(ctx: dict) -> None:
    A = "Presenza dell'assistente"

    def awake_from_chat():
        chat("ciao, sono qui")
        st = http("GET", f"{WEBUI}/api/webui/presence")[1]
        need(isinstance(st, dict) and st.get("base") == "awake", f"dopo la chat lo stato è {str(st)[:200]}")
        return f"{st.get('emoji')} {st.get('label')} · effetti {st.get('effects')}"
    step(A, "Chat → stato «Sveglio» (badge WebUI)")(awake_from_chat)

    def dnd():
        code, _ = http("POST", f"{WEBUI}/api/webui/presence/dnd", {"minutes": 5})
        need(code == 200, f"DND → {code}")
        st = http("GET", f"{WEBUI}/api/webui/presence")[1]
        need(st.get("base") == "dnd" and st["effects"].get("notify.level") == "urgent", f"DND: {str(st)[:200]}")
        http("DELETE", f"{WEBUI}/api/webui/presence/dnd")
        back = http("GET", f"{WEBUI}/api/webui/presence")[1]
        need(back.get("base") != "dnd", "DND non si spegne")
        return f"DND → notifiche solo urgenti; spento → {back.get('label')}"
    step(A, "Non disturbare dalla WebUI: notifiche solo urgenti, poi si spegne")(dnd)

    def idle_live_setting():
        code, out = setting("chronos.presence.idle_after", 1)
        need(code == 200, f"impostazione → {code} {str(out)[:200]}")
        deadline, st = time.time() + 150, {}
        while time.time() < deadline:
            st = http("GET", f"{WEBUI}/api/webui/presence")[1]
            if st.get("base") == "idle":
                break
            time.sleep(10)
        waited = int(150 - (deadline - time.time()))
        setting("chronos.presence.idle_after", 5)
        need(st.get("base") == "idle", f"con idle_after=1 dopo {waited} s lo stato è {st.get('base')}")
        chat("eccomi di nuovo")
        again = http("GET", f"{WEBUI}/api/webui/presence")[1]
        need(again.get("base") == "awake", f"dopo la chat: {again.get('base')}")
        return f"soglia 1 min dal pannello → «In attesa» dopo ~{waited} s; la chat riporta «Sveglio»; soglia rimessa a 5"
    step(A, "Soglia «idle» cambiata dal pannello vale subito; la chat risveglia")(idle_live_setting)

    def tool_and_context():
        r = chat("come stai? #tool stato {}")
        need(r["tools"] and r["tools"][0]["ok"], f"stato: {r['tools'][:1]}")
        return f"stato → {r['tools'][0]['preview'][:120]}"
    step(A, "Strumento «stato» dalla chat (come stai?)")(tool_and_context)


def flow_settings(ctx: dict) -> None:
    A = "Impostazioni centrali (Themis)"

    def set_history_undo():
        key = "hygieia.default_pao_months"
        code, out = setting(key, 18)
        need(code == 200, f"PUT → {code} {str(out)[:200]}")
        items = http("GET", f"{WEBUI}/api/webui/central-settings/items?module=hygieia")[1]["items"]
        val = next(i for i in items if i["key"] == key)
        need(val["value"] == 18 and val.get("updated_by") == "webui", f"valore {val['value']} da {val.get('updated_by')}")
        p18 = api("hygieia", "POST", "api/selfcare/products", {"name": f"Banco crema senza PAO {RUN}", "status": "in_use"})
        hist = http("GET", f"{WEBUI}/api/webui/central-settings/key/{key}/history")[1]
        code, _ = http("POST", f"{WEBUI}/api/webui/central-settings/key/{key}/undo", {})
        items = http("GET", f"{WEBUI}/api/webui/central-settings/items?module=hygieia")[1]["items"]
        back = next(i for i in items if i["key"] == key)["value"]
        need(back == 12, f"dopo Annulla il valore è {back}")
        p12 = api("hygieia", "POST", "api/selfcare/products", {"name": f"Banco crema senza PAO bis {RUN}", "status": "in_use"})
        need(abs((p18.get("expires_in") or 0) - 547) <= 2 and abs((p12.get("expires_in") or 0) - 365) <= 2,
             f"scadenza dopo l'apertura: con 18 mesi {p18.get('expires_in')} giorni, con 12 {p12.get('expires_in')}")
        n = len(hist.get("items", hist)) if isinstance(hist, (dict, list)) else "?"
        return f"18 mesi salvato dalla WebUI → nuovo prodotto scade tra {p18['expires_in']} g; storia {n} voci; Annulla → 12 → {p12['expires_in']} g"
    step(A, "Cambia un valore dalla WebUI, storia, Annulla; il modulo lo usa subito")(set_history_undo)

    def bad_value():
        code, out = setting("hygieia.default_pao_months", 999)
        need(code in (400, 422), f"valore fuori range accettato: {code}")
        return f"999 rifiutato ({code}): {str(out)[:100]}"
    step(A, "Un valore fuori dai limiti viene rifiutato")(bad_value)

    def modules():
        mods = http("GET", f"{WEBUI}/api/webui/central-settings/modules")[1]["modules"]
        names = {m["module"] for m in mods}
        want = {"hercules", "hygieia", "wardrobe", "chronos", "oracle", "hermes", "themis"}
        need(want <= names, f"moduli senza impostazioni nel pannello: {sorted(want - names)}")
        return f"{len(names)} moduli nel pannello"
    step(A, "Tutti i moduli dichiarano le loro impostazioni")(modules)


def flow_plugins(ctx: dict) -> None:
    A = "Plugin dei moduli nella WebUI"

    def catalog():
        cat = http("GET", f"{WEBUI}/api/webui/plugins/catalog")[1]
        mods = {m["module"]: m for m in cat["modules"]}
        want = {"hercules", "hygieia", "wardrobe", "scout", "hub", "argus", "athena", "chronos", "hermes", "themis",
                "hephaestus", "metis", "oracle", "mcp"}
        need(want <= set(mods), f"plugin mancanti: {sorted(want - set(mods))}")
        offline = [m for m, v in mods.items() if not v.get("online")]
        need(not offline, f"plugin offline: {offline}")
        ctx["catalog"] = cat
        c = cat["contributions"]["webui"]
        return (f"{len(mods)} moduli · {len(c['page'])} pagine · {len(c['widget'])} widget · "
                f"{len(c['quick_action'])} azioni rapide")
    step(A, "Catalogo: tutti i moduli online con pagine, widget e azioni rapide")(catalog)

    def quick_sources():
        c = (ctx.get("catalog") or {}).get("contributions", {}).get("webui", {})
        bad, counts = [], []
        for q in c.get("quick_action") or []:
            if not q.get("source"):
                continue
            code, out = http("GET", f"{WEBUI}/api/webui/plugins/{q['module']}/call{q['source']}")
            items = (out.get("items") if isinstance(out, dict) else out) if code == 200 else None
            if code != 200 or not isinstance(items, list):
                bad.append(f"{q['id']}:{code}")
            else:
                counts.append(f"{q['id']} {len(items)}")
        need(not bad, f"sorgenti dei chip in errore: {bad}")
        return " · ".join(counts)
    step(A, "Home: ogni azione rapida con chip ha la sua lista")(quick_sources)

    def forbidden_path():
        code, _ = http("GET", f"{WEBUI}/api/webui/plugins/hygieia/call/api/wardrobe/pieces")
        need(code == 403, f"un plugin chiama un altro modulo e ottiene {code}")
        code, _ = http("GET", f"{WEBUI}/api/webui/plugins/wardrobe/call/health")
        need(code == 403, f"un plugin chiama un percorso fuori dal suo prefisso e ottiene {code}")
        return "fuori dal proprio prefisso → 403"
    step(A, "Un plugin può chiamare solo il proprio modulo")(forbidden_path)

    def bundles():
        c = (ctx.get("catalog") or {}).get("contributions", {}).get("webui", {})
        bad = []
        for bnd in c.get("bundle") or []:
            file = bnd["entry"].split("/ui/webui/", 1)[-1]
            code, body = http("GET", f"{WEBUI}/api/webui/plugins/{bnd['module']}/bundle/{file}")
            if code != 200 or len(str(body)) < 500:
                bad.append(f"{bnd['module']}:{code}")
        need(c.get("bundle") and not bad, f"bundle non serviti: {bad}")
        return f"{len(c['bundle'])} bundle JS serviti"
    step(A, "I bundle dei plugin sono serviti")(bundles)

    def icons():
        c = (ctx.get("catalog") or {}).get("contributions", {}).get("webui", {})
        used = {x.get("icon") for k in ("page", "widget", "quick_action") for x in c.get(k) or []}
        used |= {m.get("icon") for m in (ctx.get("catalog") or {}).get("modules", [])}
        src = (ROOT / "Hestia-WebUI/frontend/src/app/ui/icon.component.ts").read_text(encoding="utf-8")
        known = set(re.findall(r"^\s+'?([a-z-]+)'?:", src, re.M))
        missing = sorted(i for i in used - known if i)
        need(not missing, f"icone dei plugin che la WebUI non conosce (mostra «info»): {missing}")
        return f"{len(used - {None, ''})} icone dei plugin tutte disegnate"
    step(A, "Ogni icona usata dai plugin esiste nella WebUI")(icons)

def flow_mcp(ctx: dict) -> None:
    A = "MCP esterno (Accessi AI)"
    door = f"{WEBUI}/mcp"

    def rpc(token: str, method: str, params: dict | None = None):
        return http("POST", door, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"})

    def create():
        r = api("mcp", "POST", "api/mcp/accesses", {"name": f"Banco lettura {RUN}", "scope": "read", "expires_days": 1})
        tok = r.get("token")
        need(tok, f"nessun token: {str(r)[:200]}")
        ctx["mcp_read"], ctx["mcp_read_id"] = tok, (r.get("access") or r).get("access_id") or (r.get("access") or {}).get("id")
        lines = r.get("setup") or r.get("lines") or {}
        claude = lines.get("claude_code") or lines.get("claude") or json.dumps(lines)[:160]
        need("/mcp" in json.dumps(lines), f"riga di configurazione senza /mcp: {str(lines)[:200]}")
        return f"token creato; riga: {str(claude)[:140]}"
    step(A, "Accessi AI → nuovo token di sola lettura con la riga `claude mcp add`")(create)
    if "mcp_read" not in ctx:
        return

    def list_and_call():
        code, out = rpc(ctx["mcp_read"], "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                         "clientInfo": {"name": "banco", "version": "1"}})
        need(code == 200, f"initialize → {code} {str(out)[:200]}")
        code, out = rpc(ctx["mcp_read"], "tools/list")
        need(code == 200, f"tools/list → {code}")
        tools = [t["name"] for t in out["result"]["tools"]]
        need("forge_tasks" in tools, f"forge_tasks non esposto: {tools[:20]}")
        code, res = rpc(ctx["mcp_read"], "tools/call", {"name": "forge_tasks", "arguments": {}})
        need(code == 200 and not (res.get("result") or {}).get("isError"), f"forge_tasks → {code} {str(res)[:200]}")
        ctx["mcp_tools"] = tools
        return f"{len(tools)} strumenti esterni ({', '.join(tools[:6])}…); forge_tasks risponde"
    step(A, "initialize, tools/list (solo strumenti «external»), forge_tasks")(list_and_call)

    def refusals():
        code, _ = rpc("hestia_sbagliato_123", "tools/list")
        need(code == 401, f"token sbagliato → {code}")
        write_tool = next((t for t in ("settings_propose", "forge_task_note", "forge_develop") if t in ctx.get("mcp_tools", [])),
                          "settings_propose")
        code, out = rpc(ctx["mcp_read"], "tools/call", {"name": write_tool, "arguments": {}})
        need(code == 403 or "403" in str(out) or "sola lettura" in str(out).lower() or "read" in str(out).lower(),
             f"strumento di scrittura con accesso in lettura → {code} {str(out)[:200]}")
        setting("mcp.external.max_calls_per_min", 3)
        codes = [rpc(ctx["mcp_read"], "tools/list")[0] for _ in range(5)]
        setting("mcp.external.max_calls_per_min", 60)
        need(429 in codes, f"oltre il limite (3/min) i codici sono {codes}")
        api("mcp", "POST", f"api/mcp/accesses/{ctx['mcp_read_id']}/revoke")
        code, _ = rpc(ctx["mcp_read"], "tools/list")
        need(code == 401, f"token revocato → {code}")
        return f"sbagliato 401 · scrittura in sola lettura rifiutata · limite {codes} · revocato 401"
    step(A, "401 token sbagliato/revocato, 403 scrittura in sola lettura, 429 oltre il limite")(refusals)

    def oauth_meta():
        code, meta = http("GET", f"{WEBUI}/.well-known/oauth-authorization-server")
        need(code == 200 and "authorization_endpoint" in str(meta), f"metadati OAuth → {code} {str(meta)[:200]}")
        code, prm = http("GET", f"{WEBUI}/.well-known/oauth-protected-resource")
        need(code == 200, f"protected-resource → {code}")
        code, reg = http("POST", f"{WEBUI}/oauth/register", {"client_name": "Banco connector",
                                                            "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"]})
        need(code in (200, 201) and reg.get("client_id"), f"registrazione client → {code} {str(reg)[:200]}")
        return f"metadati OAuth, risorsa protetta e registrazione dinamica ok (client {reg['client_id'][:8]}…)"
    step(A, "Connettore claude.ai: metadati OAuth 2.1 e registrazione client")(oauth_meta)


# ── WebUI in Chromium: pages with data, Home, notifications, chat ────────────

PAGES = ["/home", "/p/hercules/allenamento", "/p/hercules/schede", "/p/hercules/storico", "/p/hercules/progressi",
         "/p/hercules/corpo", "/p/hygieia/oggi", "/p/hygieia/routine", "/p/hygieia/prodotti", "/p/hygieia/statistiche",
         "/p/hygieia/spesa", "/p/wardrobe/capi", "/p/wardrobe/outfit", "/p/wardrobe/cosa-mi-metto",
         "/p/wardrobe/statistiche", "/p/wardrobe/liste", "/p/hermes/notifiche", "/p/hermes/consegne",
         "/p/chronos/agenda", "/p/chronos/esecuzioni", "/p/mcp/accessi", "/p/themis/registro", "/settings"]


def browser():
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    exe = next(iter(sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None)
    pw = sync_playwright().start()
    return pw, pw.chromium.launch(executable_path=str(exe) if exe else None)


def _errors_on(page) -> list[str]:
    """Plugin error states and Angular error toasts visible on the page (shadow DOM included)."""
    return page.evaluate("""() => {
      const out = [];
      const walk = (root) => root.querySelectorAll('*').forEach(el => {
        if (el.tagName === 'HXK-STATE' && el.getAttribute('kind') === 'error') out.push((el.getAttribute('message') || el.textContent || 'errore').trim().slice(0, 120));
        if (el.shadowRoot) walk(el.shadowRoot);
      });
      walk(document);
      return out;
    }""")


def flow_webui(ctx: dict) -> None:
    A = "WebUI nel browser (desktop, telefono, temi)"
    SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        pw, br = browser()
    except Exception as exc:  # noqa: BLE001
        RESULTS.append({"area": A, "name": "Chromium", "ok": False, "detail": str(exc)[:200], "ms": 0})
        return

    def tour(label: str, viewport: dict, scheme: str):
        def run():
            page = br.new_page(viewport=viewport, color_scheme=scheme)
            js: list[str] = []
            page.on("pageerror", lambda e: js.append(str(e)[:160]))
            bad = []
            for href in PAGES:
                page.goto(f"{WEBUI}{href}", wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(1500)
                errs = _errors_on(page)
                wide = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                if errs:
                    bad.append(f"{href}: {errs[0]}")
                if label == "phone" and wide > 4:
                    bad.append(f"{href}: scorre in orizzontale di {wide}px")
                page.screenshot(path=str(SHOTS / f"{label}-{scheme}-{href.strip('/').replace('/', '_')}.png"), full_page=True)
            page.close()
            need(not bad and not js, f"problemi: {bad[:6]} · errori JS: {js[:3]}")
            return f"{len(PAGES)} pagine senza errori, screenshot {label}-{scheme}-*.png"
        return run
    step(A, "Giro delle pagine con i dati del banco — desktop, tema chiaro")(tour("desk", {"width": 1440, "height": 900}, "light"))
    step(A, "Giro delle pagine — telefono 360 px, tema scuro")(tour("phone", {"width": 360, "height": 780}, "dark"))

    def home_quick():
        page = br.new_page(viewport={"width": 390, "height": 844})
        page.goto(f"{WEBUI}/home", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)
        chip = page.get_by_text(re.compile(r"Banco Crema mani|Banco Viso sera")).first
        need(chip.count(), "nessun chip self care sulla Home")
        before = len(api("hygieia", "GET", "api/selfcare/logs", query={"days": 1})["items"])
        chip.click()
        page.wait_for_timeout(2500)
        page.screenshot(path=str(SHOTS / "phone-home-quick.png"), full_page=True)
        after = len(api("hygieia", "GET", "api/selfcare/logs", query={"days": 1})["items"])
        undo = page.get_by_text("Annulla").first
        undone = None
        if undo.count():
            undo.click()
            page.wait_for_timeout(2000)
            undone = len(api("hygieia", "GET", "api/selfcare/logs", query={"days": 1})["items"])
        page.close()
        need(after != before or undone is not None, f"il tocco non ha cambiato i registri ({before}→{after})")
        return f"tocco sul chip: registri {before}→{after}, Annulla → {undone}"
    step(A, "Home sul telefono: un tocco su un chip self care, poi Annulla")(home_quick)

    def notification_button():
        rid = ctx.get("hands")
        if rid:
            hub("hermes", "POST", "api/events/ingest", {"event_type": "service.action_required", "domain": "system",
                "entity_id": f"selfcare.reminder.{rid}", "payload": {
                    "kind": "selfcare.reminder", "service": "hygieia", "source": "hygieia", "domain": "selfcare",
                    "_source": "hygieia", "_title": "Self care", "target": "owner", "replaces": f"selfcare.reminder.{rid}",
                    "level": "info", "_message": "Banco: crema mani dal browser", "_link": {"module": "hygieia", "page": f"routine/{rid}"},
                    "_actions": [{"id": "skip", "label": "Salta", "service": "hygieia", "method": "POST",
                                  "path": f"/api/selfcare/routines/{rid}/skip", "body": {}}]}})
        page = br.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{WEBUI}/p/hermes/notifiche", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)
        btn = page.get_by_text("Salta", exact=True).first
        need(btn.count(), "nessun bottone «Salta» nella pagina Notifiche")
        btn.click()
        page.wait_for_timeout(2500)
        page.screenshot(path=str(SHOTS / "desk-notifiche-risposta.png"), full_page=True)
        page.close()
        logs = api("hygieia", "GET", "api/selfcare/logs", query={"routine_id": rid, "days": 1})["items"] if rid else []
        need(not rid or any(l.get("status") == "skipped" for l in logs), "«Salta» dal browser non ha registrato lo skip")
        return "bottone «Salta» nella pagina Notifiche → il modulo registra lo skip"
    step(A, "Notifiche: rispondere con un bottone dal browser")(notification_button)

    def webui_chat_presence():
        setting("chronos.presence.idle_after", 1)
        deadline = time.time() + 150
        while time.time() < deadline and http("GET", f"{WEBUI}/api/webui/presence")[1].get("base") != "idle":
            time.sleep(10)
        page = br.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{WEBUI}/chat", wait_until="networkidle", timeout=60000)
        deadline = time.time() + 150      # opening the page may count: wait for idle again, then type
        while time.time() < deadline and http("GET", f"{WEBUI}/api/webui/presence")[1].get("base") != "idle":
            time.sleep(10)
        idle = http("GET", f"{WEBUI}/api/webui/presence")[1].get("base")
        box = page.locator("textarea").first
        box.fill("cosa uso stasera? #tool selfcare_today {}")
        box.press("Enter")
        page.wait_for_timeout(12000)
        page.screenshot(path=str(SHOTS / "desk-chat-strumento.png"), full_page=True)
        page.close()
        st = http("GET", f"{WEBUI}/api/webui/presence")[1]
        setting("chronos.presence.idle_after", 5)
        need(idle == "idle", f"prima di scrivere lo stato era {idle}")
        need(st.get("base") == "awake", f"dopo un messaggio nella chat WebUI lo stato è ancora «{st.get('label')}»")
        return "da «In attesa» un messaggio nella chat WebUI riporta «Sveglio»; risposta con lo strumento nello screenshot"
    step(A, "Chat WebUI: scrivere riporta la presenza a «Sveglio»")(webui_chat_presence)

    br.close()
    pw.stop()


AREAS = {"hercules": flow_hercules, "hygieia": flow_hygieia, "wardrobe": flow_wardrobe, "agenda": flow_agenda,
         "presence": flow_presence, "settings": flow_settings, "plugins": flow_plugins, "mcp": flow_mcp, "webui": flow_webui}


def main(argv: list[str]) -> int:
    wanted = [a for a in argv if a in AREAS] or list(AREAS)
    ctx: dict = {}
    notes: list[str] = []
    for name in wanted:
        try:
            AREAS[name](ctx)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            notes.append(f"{name}: interrotto da {exc.__class__.__name__}: {exc}")
    path = write_report(notes)
    print(f"event=flows_done ok={sum(r['ok'] for r in RESULTS)} failed={sum(not r['ok'] for r in RESULTS)} report={path}")
    return 1 if any(not r["ok"] for r in RESULTS) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
