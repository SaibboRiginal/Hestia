import asyncio
import os
from typing import Optional

import requests

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def _is_blocked(html: str) -> bool:
    text = (html or "").lower()
    # Only treat as blocked when known challenge fingerprints are present.
    blocked_markers = [
        "captcha-delivery",
        "geo.captcha-delivery.com",
        "ddblock",
        "datadome",
        "why_captcha",
        "/captcha/",
    ]
    return any(marker in text for marker in blocked_markers)


def _cdp_endpoints(default_port: int) -> list[str]:
    configured = [
        item.strip()
        for item in os.getenv("FETCH_CDP_ENDPOINTS", "").split(",")
        if item.strip()
    ]
    if configured:
        return configured
    return [f"http://localhost:{default_port}"]


def _is_edge_cdp(endpoint: str, timeout_seconds: int = 2) -> bool:
    try:
        response = requests.get(
            f"{endpoint}/json/version", timeout=timeout_seconds)
        if response.status_code >= 400:
            return False
        payload = response.json() if response.content else {}
        browser_name = str(payload.get("Browser") or "").lower()
        return "microsoft edge" in browser_name or "edg/" in browser_name
    except Exception:
        return False


def fetch_via_cdp(url: str, timeout_seconds: int, wait_ms: int, endpoint_override: Optional[str] = None) -> Optional[dict]:
    if not PLAYWRIGHT_AVAILABLE:
        return None

    edge_bin = os.getenv("EDGE_BIN")
    if not edge_bin:
        if os.name == "nt":
            edge_bin = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
            if not os.path.exists(edge_bin):
                edge_bin = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
        else:
            edge_bin = "microsoft-edge"  # Assumes it's in PATH for linux/mac

    edge_data_dir = os.getenv("EDGE_DATA_DIR", os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "data", "edge_profile")))
    if not os.path.exists(edge_data_dir):
        os.makedirs(edge_data_dir, exist_ok=True)

    async def run() -> Optional[dict]:
        async with async_playwright() as p:
            # We use launch_persistent_context to run Edge with the specific user data dir
            context = await p.chromium.launch_persistent_context(
                user_data_dir=edge_data_dir,
                executable_path=edge_bin,
                headless=False,  # We want it visible if needed, like the original bat script
                # Keep the port for compatibility if needed
                args=["--remote-debugging-port=9222"]
            )

            # Close all pre-existing pages that are opened on launch (e.g. startup page)
            for p_page in context.pages:
                await p_page.close()

            page = await context.new_page()
            page.set_default_timeout(timeout_seconds * 1000)
            await page.goto(url, wait_until="networkidle", timeout=timeout_seconds * 1000)
            if wait_ms > 0:
                await page.wait_for_timeout(wait_ms)
            html = await page.content()
            final_url = page.url

            await context.close()

            return {
                "fetch_method": "edge_local",
                "url": url,
                "final_url": final_url,
                "http_status": 200,
                "blocked": _is_blocked(html),
                "content_length": len(html),
                "html": html,
                "cdp_endpoint": None,
            }

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run())
    finally:
        loop.close()


def fetch_html(url: str, timeout_seconds: int, wait_ms: int, strategy: str, cdp_endpoint: Optional[str]) -> dict:
    if strategy not in {"cdp", "edge_cdp"}:
        raise ValueError(
            "Unsupported strategy: Fetch service is restricted to Edge CDP only (use 'edge_cdp').")

    result = fetch_via_cdp(
        url, timeout_seconds, wait_ms, endpoint_override=cdp_endpoint)
    if not result:
        raise RuntimeError(
            "Edge CDP is not reachable or returned no content. Start Edge with --remote-debugging-port=9222 and project-local user-data-dir.")

    # Return HTML even when blocked markers are present so callers can inspect/debug.
    # Strict failure can be re-enabled by setting FETCH_FAIL_ON_BLOCKED=true.
    fail_on_blocked = str(os.getenv("FETCH_FAIL_ON_BLOCKED", "false")).strip().lower() in {
        "1", "true", "yes", "on"}
    if result.get("blocked") and fail_on_blocked:
        raise RuntimeError(
            "Edge CDP returned a blocked/captcha page. Solve it in the attached Edge profile and retry.")

    return result
