#!/usr/bin/env python3
"""Cloud test bench: run the whole Hestia stack in a Claude cloud session or a GitHub Codespace.

Usage (from the repo root, Linux, Docker):
  python tools/cloud_test.py all        # prepare + up + check (the usual one-shot)
  python tools/cloud_test.py prepare    # docker daemon, network, base images, .env files
  python tools/cloud_test.py up         # build and start every service (Telegram only with a bot token)
  python tools/cloud_test.py check      # health, Hub registry, smoke calls, WebUI screenshots → .cloud-test/
  python tools/cloud_test.py flows [area…]  # real-run flows (modules, chat→tools, Hermes, MCP, WebUI) → .cloud-test/flows.md
  python tools/cloud_test.py token      # WebUI login link (Codespaces: the forwarded port needs the token)
  python tools/cloud_test.py logs SVC   # last log lines of one service
  python tools/cloud_test.py down       # stop and remove the containers (volumes kept)

What it adapts, and only here (docker-compose.cloud-test.yml + this script; up-all.bat is untouched):
- Restricted network (Claude cloud): Docker Hub rate-limits shared IPs and Debian's package servers are
  not allowed, Ubuntu's are. Base images come from mirror.gcr.io / mcr.microsoft.com and are re-tagged
  under the names the Dockerfiles use; python:3.12-slim and dotnet/aspnet:9.0 become Ubuntu 24.04
  stand-ins (same Python 3.12, same .NET runtime) so `apt-get install` works. Full network (Codespaces):
  official images, untouched.
- TLS proxy: when a proxy CA exists (HESTIA_CLOUD_TEST_CA, or the Claude session's one) it is layered into
  the base images so pip, npm, NuGet and the services trust it. Nothing of this reaches the real images.
- LLM: GEMINI_API_KEY in the environment → Oracle's models switch to Gemini (Themis); otherwise a
  deterministic fake Ollama answers "[LLM finto] …" and the report says so.
Generated .env files hold no personal data and are git-ignored; existing ones are never overwritten.
SPEC: docs/work/2026-10-19-banco-prova-cloud/SPEC.md
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "tools" / "cloud_test" / "base"
OUT = ROOT / ".cloud-test"
COMPOSE = ["docker", "compose", "-f", "docker-compose.global.yml", "-f", "docker-compose.cloud-test.yml"]
NETWORK = "hestia_net"
# Claude cloud: ca-bundle.crt holds both interception CAs (agent proxy + egress gateway) and the public roots.
CA_CANDIDATES = [os.getenv("HESTIA_CLOUD_TEST_CA", ""), "/root/.ccr/ca-bundle.crt"]
MIRROR = "mirror.gcr.io"
UBUNTU = f"{MIRROR}/library/ubuntu:24.04"
# Images used by Dockerfiles (FROM) or compose (image:), with where to get them on a restricted network.
BASE_IMAGES = {
    "python:3.12-slim": f"{MIRROR}/library/python:3.12-slim",
    "node:22-alpine": f"{MIRROR}/library/node:22-alpine",
    "mcr.microsoft.com/dotnet/sdk:9.0": "mcr.microsoft.com/dotnet/sdk:9.0",
    "mcr.microsoft.com/dotnet/aspnet:9.0": "mcr.microsoft.com/dotnet/aspnet:9.0",
    "ankane/pgvector": f"{MIRROR}/ankane/pgvector",
    "swaggerapi/swagger-ui": f"{MIRROR}/swaggerapi/swagger-ui",
}
NEEDS_CA = ("node:22-alpine", "mcr.microsoft.com/dotnet/sdk:9.0")  # build stages that download packages
GEMINI_MODELS = {"generic": "gemini-2.5-flash", "reasoning": "gemini-2.5-flash"}
WEBUI = "http://localhost:19015"


def log(event: str, **kv) -> None:
    print(f"event={event} " + " ".join(f"{k}={v}" for k, v in kv.items()), flush=True)


def run(cmd: list[str], check: bool = True, quiet: bool = False, **kw) -> subprocess.CompletedProcess:
    if not quiet:
        log("run", cmd=json.dumps(" ".join(cmd)[:200]))
    out = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=quiet, **kw)
    if check and out.returncode != 0:
        if quiet:
            sys.stderr.write((out.stdout or "") + (out.stderr or ""))
        raise SystemExit(f"[cloud-test] failed ({out.returncode}): {' '.join(cmd)}")
    return out


def ok(cmd: list[str]) -> bool:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True).returncode == 0


def http(method: str, url: str, body=None, timeout: float = 15.0) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # localhost: never the proxy
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read().decode("utf-8", "replace"), exc.code
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(exc)
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


# ── prepare ──────────────────────────────────────────────────────────────────

def proxy_ca() -> Path | None:
    for cand in CA_CANDIDATES:
        if cand and Path(cand).is_file():
            return Path(cand)
    return None


def restricted_network() -> bool:
    """True when Debian's package servers cannot be resolved (Claude cloud session policy)."""
    if os.getenv("HESTIA_CLOUD_TEST_RESTRICTED") in ("0", "1"):
        return os.getenv("HESTIA_CLOUD_TEST_RESTRICTED") == "1"
    try:
        socket.getaddrinfo("deb.debian.org", 443)
        return False
    except OSError:
        return True


def ensure_docker() -> None:
    if ok(["docker", "info"]):
        return
    if not shutil.which("dockerd") or os.geteuid() != 0:
        raise SystemExit("[cloud-test] Docker is not running and cannot be started here.")
    log("dockerd_start")
    subprocess.Popen(["dockerd"], stdout=open("/tmp/hestia-dockerd.log", "ab"), stderr=subprocess.STDOUT,
                     start_new_session=True)
    for _ in range(60):
        if ok(["docker", "info"]):
            return
        time.sleep(1)
    raise SystemExit("[cloud-test] dockerd did not start (see /tmp/hestia-dockerd.log)")


def image_exists(tag: str) -> bool:
    return ok(["docker", "image", "inspect", tag])


def pull_as(source: str, tag: str) -> None:
    run(["docker", "pull", "-q", source], quiet=True)
    if source != tag:
        run(["docker", "tag", source, tag], quiet=True)


def build_base(dockerfile: str, tag: str, **args: str) -> None:
    cmd = ["docker", "build", "-q", "-f", str(BASE_DIR / dockerfile), "-t", tag]
    for key, value in args.items():
        cmd += ["--build-arg", f"{key}={value}"]
    run(cmd + [str(BASE_DIR)], quiet=True)


def prepare_images(force: bool) -> None:
    ca = proxy_ca()
    restricted = restricted_network()
    ca_dir = BASE_DIR / "ca"
    shutil.rmtree(ca_dir, ignore_errors=True)
    ca_dir.mkdir(parents=True)
    if ca:  # one file per certificate: update-ca-certificates expects that
        pems = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", ca.read_text(), re.S)
        for i, pem in enumerate(pems):
            (ca_dir / f"proxy-ca-{i:03d}.crt").write_text(pem + "\n")
    log("base_images", restricted=restricted, proxy_ca=bool(ca))
    marker = "hestia.cloud-test"
    for tag, source in BASE_IMAGES.items():
        stand_in = restricted and tag in ("python:3.12-slim", "mcr.microsoft.com/dotnet/aspnet:9.0")
        built = stand_in or (ca is not None and tag in NEEDS_CA)
        if image_exists(tag) and not force:
            labels = run(["docker", "image", "inspect", "-f", "{{json .Config.Labels}}", tag],
                         quiet=True, check=False).stdout
            if not built or marker in labels:
                log("base_image_ready", tag=tag)
                continue
        if stand_in and tag == "python:3.12-slim":
            build_base("python.Dockerfile", tag, UBUNTU_IMAGE=UBUNTU)
        elif stand_in:
            pull_as(source, "hestia-cloud-test/upstream-aspnet:9.0")
            build_base("aspnet.Dockerfile", tag, UPSTREAM="hestia-cloud-test/upstream-aspnet:9.0", UBUNTU_IMAGE=UBUNTU)
        elif built:
            upstream = f"hestia-cloud-test/upstream-{tag.split('/')[-1].replace(':', '-')}"
            pull_as(source if restricted else tag, upstream)
            build_base("ca-layer.Dockerfile", tag, UPSTREAM=upstream)
        else:
            pull_as(source if restricted else tag, tag)
            log("base_image_pulled", tag=tag)
            continue
        relabel(tag, marker)
        log("base_image_built", tag=tag)


def relabel(tag: str, marker: str) -> None:
    """Mark a bench-built base image so later runs reuse it (and never confuse it with an official one)."""
    proc = subprocess.run(["docker", "build", "-q", "--label", f"{marker}=1", "-t", tag, "-"], cwd=ROOT,
                          input=f"FROM {tag}\n", text=True, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)


def prepare_env() -> None:
    run([sys.executable, "tools/init_env.py"])


def cmd_prepare(force: bool = False) -> None:
    ensure_docker()
    if not ok(["docker", "network", "inspect", NETWORK]):
        run(["docker", "network", "create", NETWORK])
    prepare_images(force)
    prepare_env()
    OUT.mkdir(exist_ok=True)


# ── up ───────────────────────────────────────────────────────────────────────

def services() -> list[str]:
    names = run(COMPOSE + ["config", "--services"], quiet=True).stdout.split()
    skip = set()
    if not os.getenv("TELEGRAM_BOT_TOKEN") and not env_value("Hestia-Telegram/app/.env", "TELEGRAM_BOT_TOKEN"):
        skip.add("telegram")  # no bot token in a test bench: it would only crash-loop
    return [n for n in names if n not in skip]


def env_value(rel: str, key: str) -> str:
    path = ROOT / rel
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def cmd_up() -> None:
    ensure_docker()
    names = services()
    env = {**os.environ, "COMPOSE_PARALLEL_LIMIT": os.getenv("COMPOSE_PARALLEL_LIMIT", "4")}
    run(COMPOSE + ["build"] + names, env=env)
    run(COMPOSE + ["up", "-d", "--no-build"] + names, env=env)
    wait_healthy(names)
    if os.getenv("GEMINI_API_KEY"):
        use_gemini()


def ports() -> dict[str, int]:
    """Published host port of each service (first mapping)."""
    cfg = json.loads(run(COMPOSE + ["config", "--format", "json"], quiet=True).stdout)
    out = {}
    for name, svc in cfg.get("services", {}).items():
        for mapping in svc.get("ports") or []:
            if mapping.get("published"):
                out[name] = int(mapping["published"])
                break
    return out


NO_HTTP = {"archive_db", "fake_llm"}  # Postgres; the fake LLM answers "/" like Ollama


def health_url(name: str, port: int) -> str:
    return f"http://localhost:{port}/" if name == "swagger" else f"http://localhost:{port}/health"


def wait_healthy(names: list[str], timeout: int = 240) -> dict[str, int]:
    port_of = ports()
    pending = {n for n in names if n in port_of and n not in NO_HTTP}
    status: dict[str, int] = {}
    deadline = time.time() + timeout
    while pending and time.time() < deadline:
        for name in sorted(pending):
            code, _ = http("GET", health_url(name, port_of[name]), timeout=5)
            status[name] = code
            if 200 <= code < 300:
                pending.discard(name)
        if pending:
            time.sleep(5)
    log("health_wait_done", healthy=len(names) - len(pending), pending=",".join(sorted(pending)) or "-")
    return status


def use_gemini() -> None:
    """Point Oracle's chat models at Gemini through Themis (the key comes from the environment)."""
    for use_case, model in GEMINI_MODELS.items():
        for field, value in (("provider", "gemini"), ("model", model)):
            key = f"oracle.models.{use_case}.{field}"
            code, _ = http("PUT", f"http://localhost:{ports().get('themis', 19016)}/api/settings/key/{key}",
                           {"value": value, "actor": "cloud-test"})
            log("setting_set", key=key, status=code)


# ── check ────────────────────────────────────────────────────────────────────

def container_states() -> dict[str, str]:
    raw = run(COMPOSE + ["ps", "-a", "--format", "json"], quiet=True, check=False).stdout.strip()
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("["):
            rows.extend(json.loads(line))
        elif line:
            rows.append(json.loads(line))
    return {r.get("Service", "?"): r.get("State", "?") + (f" ({r['Health']})" if r.get("Health") else "") for r in rows}


def smoke() -> list[tuple[str, bool, str]]:
    port_of = ports()
    hub, oracle = port_of.get("hub", 19001), port_of.get("oracle", 19004)
    checks: list[tuple[str, bool, str]] = []

    code, body = http("GET", f"http://localhost:{hub}/api/registry/services")
    items = body.get("services", body) if isinstance(body, dict) else body
    names = sorted({(s.get("name") or s.get("service_name") or "?") for s in items}) if isinstance(items, list) else []
    checks.append(("Hub: servizi registrati", code == 200 and len(names) > 5, f"{len(names)}: {', '.join(names)}"))

    code, body = http("GET", f"http://localhost:{hub}/api/ui/map?probe=true", timeout=30)
    if isinstance(body, dict):
        checks.append(("Hub: mappa (online/offline)", code == 200,
                       f"online {body.get('online_count')} · offline {body.get('offline_count')}"))

    code, body = http("POST", f"http://localhost:{oracle}/api/llm/generate", {"prompt": "Ciao Hestia, come stai?"},
                      timeout=120)
    answer = body.get("response", "") if isinstance(body, dict) else str(body)
    fake = "[LLM finto]" in str(answer)
    checks.append(("Oracle: risposta LLM" + (" (finto)" if fake else ""), code == 200 and bool(answer),
                   f"{body.get('provider', '?') if isinstance(body, dict) else '?'}: {str(answer)[:160]}"))

    code, body = http("GET", f"http://localhost:{port_of.get('themis', 19016)}/api/settings/modules")
    count = len(body.get("modules", body)) if isinstance(body, (dict, list)) else 0
    checks.append(("Themis: moduli con impostazioni", code == 200 and count > 0, str(count)))

    code, body = http("GET", f"http://localhost:{port_of.get('mcp', 19013)}/health")
    checks.append(("Hestia-MCP: health", code == 200, str(body)[:120]))
    return checks


def screenshots(shots: Path) -> list[str]:
    """Drive the WebUI like a user (localhost = no token) and save one PNG per page."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        run([sys.executable, "-m", "pip", "install", "-q", "playwright"], check=False)
        try:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError:
            return ["playwright non installabile: screenshot saltati"]
    shots.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    exe = next(iter(sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=str(exe) if exe else None)
        except Exception as exc:  # noqa: BLE001 — Codespaces: install the browser once
            notes.append(f"chromium: {exc.__class__.__name__}, provo `playwright install chromium`")
            run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"], check=False)
            browser = pw.chromium.launch()
        for label, viewport in (("desk", {"width": 1440, "height": 900}), ("phone", {"width": 390, "height": 844})):
            page = browser.new_page(viewport=viewport)
            errors: list[str] = []
            page.on("pageerror", lambda exc, errs=errors: errs.append(str(exc)[:200]))
            page.goto(f"{WEBUI}/home", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(shots / f"{label}-home.png"), full_page=True)
            if label == "phone":
                notes.append(f"phone: home ok, errori JS {len(errors)}")
                page.close()
                continue
            links = page.eval_on_selector_all("a[href^='/p/'], a[href^='/d/']", "els => els.map(e => e.getAttribute('href'))")
            targets = ["/chat", "/settings"] + sorted(dict.fromkeys(links))[:40]
            for href in targets:
                name = href.strip("/").replace("/", "_") or "root"
                try:
                    page.goto(f"{WEBUI}{href}", wait_until="networkidle", timeout=45000)
                    page.wait_for_timeout(1200)
                    page.screenshot(path=str(shots / f"{label}-{name}.png"), full_page=True)
                except Exception as exc:  # noqa: BLE001 — one broken page must not stop the tour
                    notes.append(f"{href}: {exc.__class__.__name__}")
            notes.extend(chat_roundtrip(page, shots))
            notes.append(f"desk: {len(targets)} pagine, errori JS {len(errors)}" + (f" — {errors[:3]}" if errors else ""))
            page.close()
        browser.close()
    return notes


def chat_roundtrip(page, shots: Path) -> list[str]:
    try:
        page.goto(f"{WEBUI}/chat", wait_until="networkidle", timeout=45000)
        box = page.locator("textarea").first
        box.fill("Ciao Hestia, questo è il banco di prova: rispondi in una riga.")
        box.press("Enter")
        page.wait_for_timeout(15000)
        page.screenshot(path=str(shots / "desk-chat-roundtrip.png"), full_page=True)
        return ["chat: messaggio inviato, vedi desk-chat-roundtrip.png"]
    except Exception as exc:  # noqa: BLE001
        return [f"chat: {exc.__class__.__name__}: {str(exc)[:120]}"]


def cmd_check(with_screens: bool = True) -> int:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    states = container_states()
    port_of = ports()
    health = {n: http("GET", health_url(n, port_of[n]), timeout=8)[0]
              for n in sorted(states) if n in port_of and n not in NO_HTTP}
    checks = smoke()
    notes = screenshots(OUT / "screens") if with_screens else ["screenshot saltati (--no-screens)"]
    llm = "Gemini (GEMINI_API_KEY)" if os.getenv("GEMINI_API_KEY") else "LLM finto (fake Ollama, nessun modello reale)"
    lines = [f"# Banco di prova — {stamp}", "", f"- Rete ristretta: {restricted_network()} · CA proxy: {bool(proxy_ca())}",
             f"- Cervello: {llm}", "", "## Container", "", "| Servizio | Stato | Health |", "|---|---|---|"]
    for name in sorted(states):
        code = health.get(name)
        lines.append(f"| {name} | {states[name]} | {code if code is not None else '-'} |")
    lines += ["", "## Smoke", ""]
    lines += [f"- {'✅' if passed else '❌'} {label}: {detail}" for label, passed, detail in checks]
    lines += ["", "## WebUI", ""] + [f"- {n}" for n in notes]
    lines += ["", f"Screenshot: `{(OUT / 'screens').relative_to(ROOT)}/`"]
    OUT.mkdir(exist_ok=True)
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    bad = [n for n, c in health.items() if not (c and 200 <= c < 300)] + [c[0] for c in checks if not c[1]]
    log("check_done", failed=len(bad), report=str((OUT / "report.md").relative_to(ROOT)))
    return 1 if bad else 0


# ── misc ─────────────────────────────────────────────────────────────────────

def cmd_token() -> None:
    """Ask the WebUI admin API (from inside the Docker network) for a login token and print the link."""
    proc = run(["docker", "exec", "hestia_webui", "curl", "-s", "-X", "POST",
                "http://localhost:19015/api/webui/admin/generate-token"], quiet=True, check=False)
    try:
        body = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        body = {}
    token = body.get("token") or body.get("access_token")
    if not token:
        raise SystemExit(f"[cloud-test] no token: {proc.stdout[:200]} {proc.stderr[:200]}")
    base = os.getenv("CODESPACE_NAME") and \
        f"https://{os.environ['CODESPACE_NAME']}-19015.{os.getenv('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', 'app.github.dev')}"
    print(f"Login: {base or WEBUI}/login?token={token}")


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "all"
    force = "--force" in argv
    if cmd == "prepare":
        cmd_prepare(force)
    elif cmd == "up":
        cmd_up()
    elif cmd == "check":
        return cmd_check("--no-screens" not in argv)
    elif cmd == "all":
        cmd_prepare(force)
        cmd_up()
        return cmd_check("--no-screens" not in argv)
    elif cmd == "flows":
        sys.path.insert(0, str(ROOT / "tools" / "cloud_test"))
        import flows  # noqa: PLC0415 — only this command needs it
        return flows.main(argv[2:])
    elif cmd == "token":
        cmd_token()
    elif cmd == "logs":
        run(COMPOSE + ["logs", "--tail", "120", argv[2]] if len(argv) > 2 else COMPOSE + ["logs", "--tail", "40"])
    elif cmd == "down":
        run(COMPOSE + ["down"])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
