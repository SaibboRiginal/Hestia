from __future__ import annotations

from typing import Any

from .capabilities import build_capabilities
from .service_contract import HestiaServiceBase
from .webui_plugin import ui


class HephaestusService(HestiaServiceBase):
    def build_capabilities(self) -> dict[str, Any]:
        caps = build_capabilities()
        caps["mcp_endpoint"] = f"{self.descriptor.base_url.rstrip('/')}/mcp"
        caps.update(ui.capabilities(self.descriptor.base_url))   # WebUI plugin manifest (Sistema)
        return caps
