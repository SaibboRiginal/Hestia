from __future__ import annotations

from typing import Any

from .capabilities import build_capabilities
from .service_contract import HestiaServiceBase
from .webui_plugin import ui


class HephaestusService(HestiaServiceBase):
    def build_capabilities(self) -> dict[str, Any]:
        caps = build_capabilities()
        caps.setdefault("when_to_use", "developing and repairing the assistant itself: development tasks, updates, "
                                       "repairs")
        caps.setdefault("manual", "forge_develop starts a development task only on an explicit build request or a "
                                  "«yes» to the proposal; forge_tasks/forge_status/forge_task read; approve, reject, "
                                  "pause, rollback only when the owner says so. aggiornamenti_*: Hestia updates.")
        caps.setdefault("title", "Development")
        caps["mcp_endpoint"] = f"{self.descriptor.base_url.rstrip('/')}/mcp"
        caps.update(ui.capabilities(self.descriptor.base_url))   # WebUI plugin manifest (Sistema)
        return caps
