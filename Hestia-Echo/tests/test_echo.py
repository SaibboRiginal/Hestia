"""Echo: text made speakable, sentence cutting, silence, providers/keys, chains (fallback, quota skip, external mode),
uses, files and streams, kept audio rules, usage, endpoints and manifest.

Fake engines and a fake Archive: no model, no network. Tests that convert audio need ffmpeg (skipped without it).
Markers: unit, api
"""
import base64
import math
import struct
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.core import audio  # noqa: E402
from app.core.blocks import Blocks, ChainExhausted, key_env  # noqa: E402
from app.core.keep import Keep  # noqa: E402
from app.core.service import Echo, Invalid, NotFound  # noqa: E402
from app.core.standards import STANDARDS, EngineError, Standard  # noqa: E402

pytestmark = pytest.mark.unit
needs_ffmpeg = pytest.mark.skipif(not audio.ffmpeg_available(), reason="ffmpeg not installed")


def tone(seconds=1.0, silence_tail=0.0, rate=16000):
    """16 kHz mono WAV: a 440 Hz tone, then silence."""
    frames = bytearray()
    for i in range(int(seconds * rate)):
        frames += struct.pack("<h", int(0.3 * 32767 * math.sin(2 * math.pi * 440 * i / rate)))
    frames += b"\x00\x00" * int(silence_tail * rate)
    return audio.wav_bytes(bytes(frames), rate)


class FakeEngine(Standard):
    id, label, directions = "fake", "Finto", ("ascolto", "voce")
    options = []

    def __init__(self):
        self.fail = {}            # provider name → exception
        self.calls = []

    def transcribe(self, provider, model, data, mime, language, opts):
        self.calls.append(("t", provider["name"], model, mime))
        if provider["name"] in self.fail:
            raise self.fail[provider["name"]]
        return {"text": f"ciao da {provider['name']}", "language": language}

    def speak(self, provider, model, voice, text, language, opts):
        self.calls.append(("s", provider["name"], voice, text))
        if provider["name"] in self.fail:
            raise self.fail[provider["name"]]
        return tone(0.3), "audio/wav"


class FakeKeyed(FakeEngine):
    id, needs_key = "fake_keyed", True


class FakeArchive:
    def __init__(self):
        self.rows, self.blobs, self.down, self.n = {}, {}, False, 0

    def ok(self, service, method, path, *, body=None, query=None, timeout=8):
        if self.down:
            raise OSError("archive down")
        if service == "hermes":
            return {"ok": True}
        if path == "api/echo-store/records" and method == "PUT":
            for r in body["rows"]:
                self.rows[(r["kind"], r["id"])] = dict(r)
            return {"applied": [], "stale": []}
        if path == "api/echo-store/records":
            q = query or {}
            rows = [r for r in self.rows.values() if not r.get("deleted")]
            for k in ("kind", "ref_id"):
                if q.get(k):
                    rows = [r for r in rows if r.get(k) == q[k]]
            if q.get("at_from"):
                rows = [r for r in rows if (r.get("at") or "") >= q["at_from"]]
            if q.get("order") == "-at":
                rows.sort(key=lambda r: r.get("at") or "", reverse=True)
            return {"rows": rows}
        if path == "api/blobs" and method == "POST":
            self.n += 1
            bid = f"b{self.n}"
            self.blobs[bid] = (body["data_base64"], body["content_type"])
            return {"blob_id": bid}
        if path.startswith("api/blobs/") and path.endswith("/base64"):
            data, mime = self.blobs[path.split("/")[2]]
            return {"data_b64": data, "mime": mime}
        if path.startswith("api/blobs/") and method == "DELETE":
            self.blobs.pop(path.split("/")[2], None)
            return {"status": "deleted"}
        raise AssertionError(f"unexpected {service} {method} {path}")

    call = None


@pytest.fixture
def engine(monkeypatch):
    fake, keyed = FakeEngine(), FakeKeyed()
    monkeypatch.setitem(STANDARDS, "fake", fake)
    monkeypatch.setitem(STANDARDS, "fake_keyed", keyed)
    return fake


@pytest.fixture
def world(engine, monkeypatch):
    values = {
        "echo.providers": {"uno": {"type": "fake"}, "due": {"type": "fake"}, "chiuso": {"type": "fake_keyed"},
                           "fuori": {"type": "fake"}},
        "echo.chains": {"ascolto": {"label": "A", "direction": "ascolto", "steps": [
                            {"provider": "chiuso", "model": "m0"}, {"provider": "uno", "model": "m1"},
                            {"provider": "due", "model": "m2"}]},
                        "voce": {"label": "V", "direction": "voce", "steps": [
                            {"provider": "uno", "voice": "v1"}, {"provider": "due", "voice": "v2"}]},
                        "solo-due": {"label": "D", "direction": "ascolto", "steps": [{"provider": "due", "model": "x"}]}},
        "echo.usecases": {}, "echo.mode": "interna", "echo.external.provider": "fuori",
        "echo.external.fallback": "interna", "echo.language": "it", "echo.voce.max_chars": 1200,
        "echo.ascolto.max_seconds": 600, "echo.audio.space_mb": 2048, "echo.audio.generated_days": 30,
        "echo.chains.cooldown": 60, "echo.pricing": {"uno/m1": {"minute": 0.5}},
    }
    monkeypatch.delenv(key_env("chiuso"), raising=False)
    get = lambda k, d=None: values.get(k, d)  # noqa: E731
    registry = [{"name": "telegram", "capabilities": {"voice_usecases": [
        {"id": "telegram.vocale", "label": "Vocali", "direction": "ascolto", "chain": "solo-due"}]}}]
    arch = FakeArchive()
    notes = []
    blocks = Blocks(get, lambda: registry)
    keep = Keep(arch, get, notes.append)
    return {"values": values, "blocks": blocks, "keep": keep, "echo": Echo(blocks, keep, get), "archive": arch,
            "engine": engine, "notes": notes}


# ── text and sound helpers ───────────────────────────────────────────────────
def test_speakable_drops_markdown_links_code_and_emoji():
    t = audio.speakable("**Ciao** Marko! 🎉 Vedi [qui](https://x.y) e `codice`.\n```py\nprint(1)\n```\n- punto uno")
    assert "**" not in t and "🎉" not in t and "https" not in t and "print" not in t
    assert "Ciao Marko!" in t and "Vedi qui" in t and "punto uno." in t


def test_shorten_cuts_at_sentence():
    text = "Prima frase lunga abbastanza. Seconda frase anche lei. Terza frase che non entra."
    short, cut = audio.shorten(text, 60)
    assert cut and short.endswith(".") and "Terza" not in short
    assert audio.shorten("corto", 100) == ("corto", False)


def test_sentence_cutter_streams_complete_sentences():
    c = audio.SentenceCutter(min_chars=10)
    assert c.feed("Ciao Marko, oggi") == []
    assert c.feed(" va bene. Domani piove") == ["Ciao Marko, oggi va bene."]
    assert c.feed(" forte. Il") == ["Domani piove forte."]
    assert c.feed(" 3.5 non taglia") == []
    assert c.flush() == ["Il 3.5 non taglia"]


def test_sentence_cutter_joins_short_pieces():
    c = audio.SentenceCutter(min_chars=24)
    assert c.feed("Sì. Ok. Ecco la frase vera e lunga. ") == ["Sì. Ok. Ecco la frase vera e lunga."]


def test_piped_wav_header_does_not_make_audio_endless():
    """ffmpeg piping WAV writes 0xFFFFFFFF as size: a 2.5 s answer read as 134217 s, «audio troppo lungo» (bench)."""
    wav = bytearray(tone(1.0))
    wav[4:8] = b"\xff\xff\xff\xff"
    wav[40:44] = b"\xff\xff\xff\xff"
    assert audio.wav_duration(bytes(wav)) == 1.0
    fixed = audio.to_pcm16k(bytes(wav))
    assert audio.wav_duration(fixed) == 1.0 and fixed[40:44] != b"\xff\xff\xff\xff"


def test_trailing_silence():
    assert audio.trailing_silence_ms(tone(0.5, silence_tail=1.0)) >= 900
    assert audio.trailing_silence_ms(tone(0.5)) == 0


# ── blocks ───────────────────────────────────────────────────────────────────
def test_provider_key_from_env_only(world, monkeypatch):
    b = world["blocks"]
    assert b.providers()["chiuso"]["key"] == ""
    assert b.provider_state(b.providers()["chiuso"]) == "no_key"
    monkeypatch.setenv("ECHO_KEY_CHIUSO", "k")
    assert b.provider_state(b.providers()["chiuso"]) == "ready"
    assert key_env("kokoro-fast") == "ECHO_KEY_KOKORO_FAST"


def test_chain_skips_step_without_key_and_falls_back(world):
    out, info = world["blocks"].run("x.y", "ascolto", lambda p, s: p["name"])
    assert out == "uno" and info["step"] == 1 and info["fallback"] is True
    world["engine"].fail["uno"] = EngineError("boom", 500)
    result, info = world["blocks"].run("x.y", "ascolto",
                                       lambda p, s: STANDARDS["fake"].transcribe(p, s["model"], b"", "", "it", {}))
    assert info["provider"] == "due"
    assert not world["blocks"].exhausted_until("uno", "m1")          # a 500 does not skip the pair later


def test_quota_skips_pair_in_every_chain(world):
    world["engine"].fail["uno"] = EngineError("quota", 429, retry_after=120)
    call = lambda p, s: STANDARDS["fake"].transcribe(p, s["model"], b"", "", "it", {})  # noqa: E731
    world["blocks"].run("x.y", "ascolto", call)
    assert world["blocks"].exhausted_until("uno", "m1") > 0
    world["engine"].fail.clear()
    _, info = world["blocks"].run("x.y", "ascolto", call)
    assert info["provider"] == "due"                                  # still skipped until reset
    world["blocks"].clear_exhausted("uno")
    _, info = world["blocks"].run("x.y", "ascolto", call)
    assert info["provider"] == "uno"


def test_chain_exhausted(world):
    world["engine"].fail.update({"uno": EngineError("x"), "due": EngineError("y")})
    with pytest.raises(ChainExhausted):
        world["blocks"].run("x.y", "ascolto", lambda p, s: STANDARDS["fake"].transcribe(p, "", b"", "", "", {}))


def test_usecases_declared_by_callers_and_overrides(world):
    b = world["blocks"]
    assert b.usecase_config("telegram.vocale", "ascolto")["chain"] == "solo-due"
    world["values"]["echo.usecases"] = {"telegram.vocale": {"chain": "ascolto"}}
    assert b.usecase_config("telegram.vocale", "ascolto")["chain"] == "ascolto"
    world["values"]["echo.usecases"] = {"telegram.vocale": {"chain": "voce"}}      # wrong direction → default
    assert b.usecase_config("telegram.vocale", "ascolto")["chain"] == "ascolto"
    b.usecase_config("nuovo.uso", "voce")
    rows = {r["id"]: r for r in b.describe_usecases()}
    assert rows["nuovo.uso"]["undeclared"] and rows["telegram.vocale"]["module"] == "telegram"


def test_external_mode_proxies_and_falls_back(world):
    world["values"]["echo.mode"] = "esterna"
    _, info = world["blocks"].run("x.y", "ascolto", lambda p, s: p["name"])
    assert info == {**info, "mode": "esterna", "provider": "fuori"}
    def boom(p, s):
        if p["name"] == "fuori":
            raise EngineError("down")
        return p["name"]
    out, info = world["blocks"].run("x.y", "ascolto", boom)
    assert out == "uno" and info["mode"] == "interna" and info["fallback"]
    world["values"]["echo.external.fallback"] = "nessuno"
    with pytest.raises(ChainExhausted):
        world["blocks"].run("x.y", "ascolto", boom)
    world["values"]["echo.usecases"] = {"x.y": {"mode": "interna"}}              # a use can stay internal
    assert world["blocks"].run("x.y", "ascolto", boom)[1]["mode"] == "interna"


def test_describe_chains_states(world):
    steps = world["blocks"].describe_chains()["ascolto"]["steps"]
    assert [s["state"] for s in steps] == ["no_key", "ready", "ready"]


# ── files ────────────────────────────────────────────────────────────────────
def b64(data):
    return base64.b64encode(data).decode()


def test_transcribe_wav_records_usage(world):
    out = world["echo"].transcribe({"audio_b64": b64(tone(1.2)), "mime_type": "audio/wav", "use_case": "x.y"})
    assert out["text"] == "ciao da uno" and out["provider"] == "uno" and out["duration_s"] == pytest.approx(1.2)
    usage = world["keep"].usage(1)
    assert usage[0]["kind"] == "ascolto" and usage[0]["cost"] == pytest.approx(0.01, abs=1e-3)
    assert world["echo"].recent[0]["provider"] == "uno"


def test_transcribe_rejects_empty_and_long(world):
    with pytest.raises(Invalid):
        world["echo"].transcribe({"audio_b64": "", "mime_type": "audio/wav"})
    world["values"]["echo.ascolto.max_seconds"] = 1
    with pytest.raises(Invalid):
        world["echo"].transcribe({"audio_b64": b64(tone(2)), "mime_type": "audio/wav"})


@needs_ffmpeg
def test_recording_is_kept_small_and_found_by_message(world):
    out = world["echo"].transcribe({"audio_b64": b64(tone(1)), "mime_type": "audio/wav", "use_case": "x.y",
                                    "keep": {"kind": "recording", "message_id": "m1", "session_id": "s1"}})
    row = world["keep"].find("m1")
    assert out["blob_id"] == row["id"] and row["data"]["class"] == "recording" and row["data"]["text"] == "ciao da uno"
    assert world["archive"].blobs[row["id"]][1] == "audio/ogg"


@needs_ffmpeg
def test_speak_cleans_text_encodes_and_reuses_kept_audio(world):
    body = {"text": "**Ciao** 🎉 [link](http://a.b)", "format": "ogg_opus", "use_case": "r.x",
            "keep": {"kind": "generated", "message_id": "m9"}}
    first = world["echo"].speak(body)
    assert first["mime_type"] == "audio/ogg" and first["provider"] == "uno"
    assert world["engine"].calls[-1][3] == "Ciao link."
    calls = len(world["engine"].calls)
    again = world["echo"].speak(body)
    assert again["reused"] and len(world["engine"].calls) == calls                  # no new synthesis
    changed = world["echo"].speak({**body, "text": "Altro testo"})
    assert not changed.get("reused")


@needs_ffmpeg
def test_speak_long_text_says_the_rest_is_written(world):
    world["values"]["echo.voce.max_chars"] = 200
    world["echo"].speak({"text": "Una frase di prova abbastanza lunga. " * 20, "format": "wav"})
    assert world["engine"].calls[-1][3].endswith("Il resto è nel testo.")


# ── streams ──────────────────────────────────────────────────────────────────
def test_listen_stream_partials_silence_and_end(world):
    sid = world["echo"].listen_open({"use_case": "x.y", "mime_type": "audio/wav"})["stream_id"]
    one = world["echo"].listen_chunk(sid, {"seq": 0, "audio_b64": b64(tone(0.5, silence_tail=1.2))})
    assert one["partial"] == "ciao da uno" and one["silence_ms"] >= 1000
    dup = world["echo"].listen_chunk(sid, {"seq": 0, "audio_b64": b64(tone(0.5))})      # retried chunk ignored
    assert dup["partial"] == "ciao da uno"
    out = world["echo"].listen_end(sid)
    assert out["text"] == "ciao da uno"
    assert [u["kind"] for u in world["keep"].usage(1)] == ["ascolto"]                    # partials not counted
    with pytest.raises(NotFound):
        world["echo"].listen_chunk(sid, {"audio_b64": b64(tone(0.2))})


@needs_ffmpeg
def test_say_stream_speaks_sentence_by_sentence_and_keeps_whole(world):
    sid = world["echo"].say_open({"use_case": "webui.risposta", "format": "mp3",
                                  "keep": {"kind": "generated", "message_id": "r1"}})["stream_id"]
    assert world["echo"].say_text(sid, {"delta": "Ciao Marko, oggi"})["blocks"] == []
    blocks = world["echo"].say_text(sid, {"delta": " hai dormito male. Domani"})["blocks"]
    assert [b["text"] for b in blocks] == ["Ciao Marko, oggi hai dormito male."] and blocks[0]["seq"] == 0
    end = world["echo"].say_end(sid, {"delta": " andrà meglio, promesso."})
    assert [b["seq"] for b in end["blocks"]] == [1] and end["blob_id"]
    assert world["keep"].find("r1")["data"]["text"].startswith("Ciao Marko")


# ── keeping ──────────────────────────────────────────────────────────────────
def _age(world, blob_id, days):
    row = world["archive"].rows[("audio", blob_id)]
    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    row["data"]["last_played"] = old
    row["at"] = old


def test_cleanup_drops_expired_generated_never_recordings(world):
    k = world["keep"]
    rec = k.save("recording", b"r" * 100, "audio/ogg", {"message_id": "a"})
    gen = k.save("generated", b"g" * 100, "audio/ogg", {"message_id": "b", "text": "x"})
    _age(world, rec, 400)
    _age(world, gen, 40)
    out = k.cleanup()
    assert out["expired"] == 1 and rec in world["archive"].blobs and gen not in world["archive"].blobs


def test_cleanup_space_rule_and_warning(world):
    k = world["keep"]
    world["values"]["echo.audio.space_mb"] = 0.0001          # ~104 bytes
    n1 = k.save("notification", b"n" * 80, "audio/ogg", {"notification_id": "n1", "text": "a"})
    rec = k.save("recording", b"r" * 60, "audio/ogg", {"message_id": "a"})
    out = k.cleanup()
    assert out["dropped_for_space"] == 1 and n1 not in world["archive"].blobs and rec in world["archive"].blobs
    assert not out["warned"]
    k.save("recording", b"q" * 90, "audio/ogg", {"message_id": "b"})
    assert k.cleanup()["warned"] and world["notes"]


def test_forget_notification_audio_only_regenerable(world):
    k = world["keep"]
    n = k.save("notification", b"n", "audio/ogg", {"notification_id": "n7", "text": "x"})
    assert k.forget(notification_id="n7") == 1 and n not in world["archive"].blobs


# ── endpoints and manifest ───────────────────────────────────────────────────
@pytest.mark.api
def test_endpoints_and_manifest(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main

    fake_arch = FakeArchive()
    monkeypatch.setattr(main.keep, "hub", fake_arch)
    monkeypatch.setitem(STANDARDS, "fake", FakeEngine())
    monkeypatch.setattr(main.settings, "get", lambda k, d=None: {
        "echo.providers": {"uno": {"type": "fake"}},
        "echo.chains": {"ascolto": {"direction": "ascolto", "steps": [{"provider": "uno", "model": "m"}]},
                        "voce": {"direction": "voce", "steps": [{"provider": "uno", "voice": "v"}]}},
    }.get(k, d))
    monkeypatch.setattr(main.blocks, "get", main.settings.get)
    monkeypatch.setattr(main.echo, "get", main.settings.get)
    monkeypatch.setattr(main.keep, "get", main.settings.get)
    main.blocks._reg_cache = (1e18, [])
    client = TestClient(main.app)
    assert client.get("/health").json()["service"] == "hestia_echo"
    std = {s["id"]: s for s in client.get("/api/voice/standards").json()["items"]}
    assert {"whisper_local", "piper", "kokoro", "openai", "google", "elevenlabs", "wyoming"} <= set(std)
    assert any(o["key"] == "initial_prompt" for o in std["whisper_local"]["options"])
    r = client.post("/api/voice/transcribe", json={"audio_b64": b64(tone(0.6)), "mime_type": "audio/wav"})
    assert r.status_code == 200 and r.json()["text"] == "ciao da uno"
    assert client.post("/api/voice/transcribe", json={"audio_b64": ""}).status_code == 422
    assert client.post("/api/voice/listen/nope/chunk", json={"audio_b64": ""}).status_code == 404
    assert client.get("/api/voice/chains").json()["items"]["ascolto"]["steps"][0]["state"] == "ready"
    assert client.get("/api/voice/usage").json()["totals"]["calls"] == 1
    assert client.get("/api/voice/providers/options").json()["options"][1]["value"] == "uno"
    manifest = client.get("/api/ui/manifest").json()
    assert manifest["kind"] == "core" and manifest["clients"]["webui"]["page"][0]["id"] == "voce"
    caps = main._registration()["capabilities"]
    assert caps["voice"]["api"] == "/api/voice"


@pytest.mark.api
def test_blocks_write_goes_through_settings(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main

    puts = []
    monkeypatch.setattr(main.settings, "put", lambda k, v, **kw: puts.append((k, v)) or True)
    client = TestClient(main.app)
    ok = client.put("/api/voice/blocks/chains", json={"value": {"veloce": {"direction": "voce", "steps": []}}})
    assert ok.status_code == 200 and puts == [("echo.chains", {"veloce": {"direction": "voce", "steps": []}})]
    assert client.put("/api/voice/blocks/chains", json={"value": {"x": {"direction": "boh", "steps": []}}}).status_code == 422
    assert client.put("/api/voice/blocks/providers", json={"value": {"x": {"type": "nope"}}}).status_code == 422
    assert client.put("/api/voice/blocks/altro", json={"value": {}}).status_code == 404
