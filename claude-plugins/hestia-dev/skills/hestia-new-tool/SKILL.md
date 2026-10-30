---
name: hestia-new-tool
description: Use when a Hestia module needs a new MCP tool or command (MCPTool in hestia_common.mcp_helpers): naming, clients, Telegram, external AIs.
---

- Declare `MCPTool(...)` in the module's `app/main.py`; name `<domain>_<verb>` (e.g. `wardrobe_add`).
- `clients`: who sees it (`ui`, `telegram`, `oracle`…). Add `"external"` only if an outside AI (Claude via the
  `hestia` plugin, ChatGPT) may use it; writes there must stay proposals or be undoable.
- R5: every function is reachable from Telegram: `telegram_group` + `telegram={"section": …}` and a `display` block.
- Service-to-service calls only through Hub `POST {HUB_API_URL}/route/<svc>/<path>`; LLM only through Oracle;
  voice only through Echo (`hestia_common.voice_client`).
- Swagger entry for the endpoint; module md lists the tool.
