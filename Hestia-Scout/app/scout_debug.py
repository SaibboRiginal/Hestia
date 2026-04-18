#!/usr/bin/env python3
"""
Hestia Scout Debugger - Uses EXACT production Scout code path
Run with: python scout_debug.py <URL>
"""
from core.atlas_client import AtlasClient, FetchResult
from worker.sites.registry import SiteHandlerRegistry
import json
import re
import sys
import os
from typing import Optional
from bs4 import BeautifulSoup, Comment

# Import production Scout modules from either root or app entrypoint.
THIS_DIR = os.path.dirname(__file__)
APP_DIR = THIS_DIR if os.path.isdir(os.path.join(
    THIS_DIR, "worker")) else os.path.join(THIS_DIR, "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def log_section(title: str):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*70}")
    print(f"  {title.upper()}")
    print(f"{'='*70}{Colors.ENDC}")


def log_success(msg: str):
    print(f"{Colors.GREEN}✓ {msg}{Colors.ENDC}")


def log_warning(msg: str):
    print(f"{Colors.YELLOW}⚠ {msg}{Colors.ENDC}")


def log_error(msg: str):
    print(f"{Colors.RED}✗ {msg}{Colors.ENDC}")


def log_info(msg: str):
    print(f"{Colors.BLUE}ℹ {msg}{Colors.ENDC}")


# Configuration
SCOUT_DEBUG_PRINT_SANITIZED = str(os.getenv(
    "SCOUT_DEBUG_PRINT_SANITIZED", "true")).strip().lower() in {"1", "true", "yes", "on"}
SCOUT_DEBUG_SANITIZED_PATH = os.getenv(
    "SCOUT_DEBUG_SANITIZED_PATH", "data/sanitized_listing.html").strip()
SCOUT_DEBUG_SANITIZED_MAX_PRINT_CHARS = int(os.getenv(
    "SCOUT_DEBUG_SANITIZED_MAX_PRINT_CHARS", "16000"))
SCOUT_DEBUG_RAW_HTML_PATH = os.getenv(
    "SCOUT_DEBUG_RAW_HTML_PATH", "data/raw_listing.html").strip()
SCOUT_DEBUG_PRINT_FULL_JSON = str(os.getenv(
    "SCOUT_DEBUG_PRINT_FULL_JSON", "true")).strip().lower() in {"1", "true", "yes", "on"}
SCOUT_DEBUG_ENRICHED_JSON_PATH = os.getenv(
    "SCOUT_DEBUG_ENRICHED_JSON_PATH", "data/debug_enriched_payload.json").strip()
SCOUT_DEBUG_CANONICAL_JSON_PATH = os.getenv(
    "SCOUT_DEBUG_CANONICAL_JSON_PATH", "data/debug_canonical_payload.json").strip()


def dump_raw_html(raw_html: str) -> str:
    """Persist original fetched HTML to disk for exact debugging parity."""
    log_section("Raw HTML")
    if not raw_html:
        log_warning("Raw HTML is empty")
        return ""

    target_path = SCOUT_DEBUG_RAW_HTML_PATH or "data/raw_listing.html"
    try:
        out_dir = os.path.dirname(target_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(raw_html)
        log_success(f"Raw HTML saved: {target_path} ({len(raw_html)} chars)")
    except Exception as e:
        log_warning(f"Could not save raw HTML file: {e}")

    return target_path


def build_sanitized_html(raw_html: str) -> str:
    """Sanitize HTML for parser design analysis."""
    if not raw_html:
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")

    for tag in soup(["script", "style", "noscript", "template", "svg", "iframe"]):
        tag.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    allowed_attrs = {
        "class", "id", "itemprop", "name", "property", "content",
        "href", "src", "data-testid", "aria-label"
    }
    for tag in soup.find_all(True):
        attrs = dict(tag.attrs)
        for key in list(attrs.keys()):
            if key not in allowed_attrs:
                del tag.attrs[key]

    html = str(soup)
    html = re.sub(r"\n\s*\n\s*\n+", "\n\n", html)
    return html.strip()


def dump_sanitized_html(raw_html: str) -> str:
    """Save and optionally print sanitized HTML."""
    log_section("Sanitized HTML")
    sanitized = build_sanitized_html(raw_html)
    if not sanitized:
        log_warning("Sanitized HTML is empty")
        return ""

    target_path = SCOUT_DEBUG_SANITIZED_PATH or "data/sanitized_listing.html"
    try:
        out_dir = os.path.dirname(target_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(sanitized)
        log_success(
            f"Sanitized HTML saved: {target_path} ({len(sanitized)} chars)")
    except Exception as e:
        log_warning(f"Could not save sanitized HTML file: {e}")

    if SCOUT_DEBUG_PRINT_SANITIZED:
        print("\n----- SANITIZED HTML START -----\n")
        max_chars = max(1000, SCOUT_DEBUG_SANITIZED_MAX_PRINT_CHARS)
        if len(sanitized) <= max_chars:
            print(sanitized)
        else:
            head_len = max_chars // 2
            tail_len = max_chars - head_len
            print(sanitized[:head_len])
            print(f"\n... [{len(sanitized) - max_chars} chars omitted] ...\n")
            print(sanitized[-tail_len:])
        print("\n----- SANITIZED HTML END -----\n")
    else:
        log_info("Sanitized HTML printing disabled by SCOUT_DEBUG_PRINT_SANITIZED")

    return sanitized


def dump_json_snapshot(data: dict, path: str, label: str) -> str:
    """Persist JSON snapshots to inspect full payloads without terminal clipping."""
    target_path = path.strip() if path else ""
    if not target_path:
        return ""

    try:
        out_dir = os.path.dirname(target_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log_success(f"{label} JSON saved: {target_path}")
        return target_path
    except Exception as e:
        log_warning(f"Could not save {label} JSON file: {e}")
        return ""


def debug_url(url: str):
    """Main debug function using production Scout code."""
    from domain.house_entity import HouseEntity

    print(f"\n{Colors.BOLD}{Colors.HEADER}")
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║    HESTIA SCOUT DEBUGGER (Production Code Path)                ║")
    print(f"║  URL: {url[:55]:<55} ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print(f"{Colors.ENDC}")

    # Step 1: Fetch via Atlas (production client)
    log_section("Fetching via Atlas (Production)")
    atlas = AtlasClient()
    result: Optional[FetchResult] = atlas.fetch_html(url, timeout_seconds=30)

    if result is None:
        log_error(
            "Atlas fetch failed. Verify Hub is reachable and Atlas is registered.")
        log_info("Host mode tip: HUB_API_URL=http://localhost:19001/api")
        log_info("Start Atlas with: cd Hestia-Atlas && run_host.bat")
        return

    log_success(f"Atlas fetched {result.content_length} chars")
    log_info(f"Method: {result.fetch_method}")
    log_info(f"Final URL: {result.final_url}")
    log_info(f"Blocked: {result.blocked}")

    # Step 2: Dump raw + sanitized HTML for analysis
    raw_path = dump_raw_html(result.html)
    sanitized_path = dump_sanitized_html(result.html)
    if sanitized_path:
        log_info(f"Sanitized file path: {SCOUT_DEBUG_SANITIZED_PATH}")
    if raw_path:
        log_info(f"Raw file path: {raw_path}")

    # Step 3: Enrich using production site handler
    log_section("Enrichment via Production Site Handler")

    registry = SiteHandlerRegistry()
    handler = registry.get_handler(url)

    if handler is None:
        log_warning(f"No site handler for {url}")
        log_info(
            "To add a handler, create a subclass of BaseSiteHandler in worker/sites/")
        return

    log_info(f"Using handler: {handler.site_name}")
    normalized_url = handler.normalize_url(url)
    log_info(f"Normalized URL: {normalized_url}")

    # Start with minimal payload
    payload = {"url": normalized_url}

    # Parse HTML and enrich
    soup = BeautifulSoup(result.html, "html.parser")
    enriched = handler.enrich(soup, payload)
    entity = HouseEntity.from_extracted(
        entity_id=normalized_url,
        payload=enriched,
        domain="real_estate",
    )
    canonical_payload = entity.payload.model_dump()

    # Step 4: Display enriched data
    log_section("Enriched Payload (Production Output)")
    if SCOUT_DEBUG_PRINT_FULL_JSON:
        print(json.dumps(enriched, indent=2, ensure_ascii=False))
    else:
        log_info("Enriched JSON print disabled by SCOUT_DEBUG_PRINT_FULL_JSON")

    dump_json_snapshot(
        enriched,
        SCOUT_DEBUG_ENRICHED_JSON_PATH,
        "Enriched payload",
    )

    log_section("Canonical Payload (HouseEntity)")
    if SCOUT_DEBUG_PRINT_FULL_JSON:
        print(json.dumps(canonical_payload, indent=2, ensure_ascii=False))
    else:
        log_info("Canonical JSON print disabled by SCOUT_DEBUG_PRINT_FULL_JSON")

    dump_json_snapshot(
        canonical_payload,
        SCOUT_DEBUG_CANONICAL_JSON_PATH,
        "Canonical payload",
    )

    # Step 5: Field analysis
    log_section("Field Analysis")

    missing = []
    if not canonical_payload.get("title"):
        missing.append("title")
    if not canonical_payload.get("price"):
        missing.append("price")
    if not canonical_payload.get("address"):
        missing.append("address")
    if not canonical_payload.get("summary") or len(str(canonical_payload.get("summary", ""))) < 80:
        missing.append("summary (or too short)")

    specs = canonical_payload.get("specs") if isinstance(
        canonical_payload.get("specs"), dict) else {}
    for field in ["surface_m2", "rooms", "floor"]:
        if not specs.get(field):
            missing.append(f"specs.{field}")

    if missing:
        log_warning(f"Missing or incomplete fields: {', '.join(missing)}")
    else:
        log_success("All key fields extracted successfully!")

    # Step 6: Show what the handler extracted
    log_section("Handler Extraction Summary")
    print(f"{Colors.BOLD}What the canonical payload contains:{Colors.ENDC}\n")
    print(
        f"  Source site: {canonical_payload.get('source_site', 'NOT FOUND')}")
    print(f"  Title: {canonical_payload.get('title', 'NOT FOUND')}")
    print(f"  Price: {canonical_payload.get('price', 'NOT FOUND')}")
    print(f"  Address: {canonical_payload.get('address', 'NOT FOUND')}")
    print(f"  Summary: {canonical_payload.get('summary', 'NOT FOUND')}")
    print(f"\n  Specs: {json.dumps(specs, indent=4, ensure_ascii=False)}")

    characteristics = canonical_payload.get("characteristics")
    if isinstance(characteristics, dict) and characteristics:
        print(
            f"\n  Characteristics ({len(characteristics)}): {json.dumps(characteristics, indent=4, ensure_ascii=False)}")

    surfaces = canonical_payload.get("surfaces")
    if isinstance(surfaces, list) and surfaces:
        print(
            f"\n  Surface Distribution ({len(surfaces)} parts): {json.dumps(surfaces, indent=4, ensure_ascii=False)}")

    add_features = canonical_payload.get("additional_features")
    if isinstance(add_features, list) and add_features:
        print(
            f"\n  Additional Features ({len(add_features)}): {json.dumps(add_features, indent=4, ensure_ascii=False)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scout_debug.py <URL>")
        print("Example: python scout_debug.py https://www.idealista.it/immobile/35072211/")
        sys.exit(1)

    url = sys.argv[1]
    debug_url(url)
