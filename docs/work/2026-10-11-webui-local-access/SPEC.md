# SPEC — WebUI: access token only from outside (Cloudflare tunnel)

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | User via external chat (Claude Code cloud session, project thread "token solo da esterno") · 2026-10-11 |
| **Status** | Implemented on main — waiting for the user's .NET build and real run |

User's words (Italian original): "se apro il sito web da locale non mi dovrebbe chiedere il token di accesso…
solo se passo da esterno cloudflare".

## Goal
Opening the WebUI from the home network (`http://<pc>:19015`, `localhost`) needs no token. Through the
Cloudflare tunnel (`*.trycloudflare.com` or any Cloudflare hostname) the token stays mandatory, and forging
or removing headers must never turn an external request into a local one.

## Design
A request is **local** only when ALL of these hold (`Services/LocalAccess.cs`); anything else needs the token:
1. Themis setting `webui.auth.local_without_token` is on (default on; `oracle: none`, the assistant cannot
   propose it — it is a safety switch).
2. **No proxy/tunnel header**: `Cf-Connecting-Ip`, `Cf-Ray`, `Cf-Ipcountry`, `Cf-Visitor`, `Cf-Warp-Tag-Id`,
   `Cdn-Loop`, `X-Forwarded-For`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Real-Ip`, `Forwarded`.
   Cloudflare's edge always adds `Cf-Connecting-Ip`/`Cf-Ray`/`Cdn-Loop` (cloudflared adds `Cf-Warp-Tag-Id`),
   and a client cannot strip them. So the decision only uses the *absence* of headers: forging one can only
   make a request *more* restricted, never less.
3. **Host is not public**: not under `WEBUI_PUBLIC_HOST_SUFFIXES` and not the registered public URL host
   (cloudflared forwards the tunnel hostname as Host) — second, independent tunnel signal.
4. **Socket peer address is loopback/private** (10/8, 172.16/12, 192.168/16, IPv6 ULA/link-local). This is the
   TCP peer as Kestrel sees it: no forwarded-headers middleware is installed, so it cannot be forged.

Where it applies: the `/api/webui/*` token middleware, the SignalR hub (`/hubs/chat`), and the new
`GET /api/webui/auth/access` (`{local, tokenRequired}`) the Angular app asks at start: local → no login page,
no "Esci" button; external → today's flow unchanged.

Residual risk (documented): port 19015 must never be port-forwarded on the router. With Docker Desktop every
published-port connection reaches the container from a private gateway address, so a direct internet request
without Cloudflare would look local. External access goes through the tunnel only; the setting turns the
whole bypass off.

Found while doing this: the token middleware compared the path case-sensitively while ASP.NET routing is
case-insensitive, so `/API/webui/…` skipped the token check. Paths are now compared lowercase.

### WebUI as a Themis module
WebUI declares its settings like the Python modules do (`hestia_common.settings_client` equivalent in .NET,
`Services/WebUISettings.cs`): register at start via Hub (`POST themis /api/settings/register`, retry 60 s,
re-assert hourly), `GET /api/settings/effective`, `POST /api/settings/reload` (internal-network guard).

## Acceptance criteria
- LAN/localhost: the WebUI opens straight on the chat, SignalR connects, API calls work without token.
- Tunnel: login page as before; requests without a valid token → 401; SignalR refused.
- Request with fake `Cf-Ray` from LAN → token required. Request with Host `x.trycloudflare.com` from LAN → token required.
- Setting off (Impostazioni → Sistema → webui) → token required everywhere, at once (live).
