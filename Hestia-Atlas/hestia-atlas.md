# Hestia-Atlas

Role: Integration service running on host OS (Windows/Linux), not in Docker.
Named after Atlas, conveying strength and support for shared fetching.

## Purpose

Provides a shared API for HTML fetching so all Hestia services can reuse one hardened fetch layer.
Primary use case: bypass bot protection by delegating to a real host Edge browser session.
Policy: Atlas is restricted to Edge CDP attach only (no plain requests, no headless fallback).

## Endpoints

- GET `/health`
- POST `/api/fetch/html`

Request body:

```json
{
  "url": "https://www.idealista.it/immobile/35072211",
  "timeout_seconds": 30,
  "wait_ms": 3000,
  "strategy": "edge_cdp",
  "cdp_endpoint": null
}
```

Response body:

```json
{
  "status": "ok",
  "fetch_method": "cdp",
  "url": "https://...",
  "final_url": "https://...",
  "http_status": 200,
  "blocked": false,
  "content_length": 120345,
  "html": "<html>..."
}
```

## Strategy

- `edge_cdp` (default): attach to host Edge with remote debugging.
- `cdp`: alias accepted for compatibility.

## Hub registration

Registers as service `atlas` in Hub with capability `fetch_html_endpoint=/api/fetch/html`.
Other services reach Atlas via Hub routing: `/api/route/atlas/api/fetch/html`.

## Host startup

Windows:

```bat
cd Hestia-Atlas
run_host.bat
```

The script auto-creates and uses: `Hestia-Atlas/data/edge_profile`

Linux/Raspberry:

```bash
cd Hestia-Atlas
chmod +x run_host.sh
./run_host.sh
```

The script auto-creates and uses: `Hestia-Atlas/data/edge_profile`

## Notes for Docker callers

Containers should call through Hub routing (`/api/route/atlas/...`) to stay aligned with Hestia communication policy.
If direct access is needed, use host address reachable from container (`host.docker.internal` on Docker Desktop).
