from .registry import ServiceRegistry


def discover_module_tools(registry: ServiceRegistry) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}

    for service in registry.all_services():
        capabilities = service.get("capabilities") or {}
        domains = capabilities.get("module_tool_domains") or []
        endpoint = capabilities.get("module_tool_endpoint")
        if not endpoint:
            continue

        for domain in domains:
            normalized_domain = str(domain).strip().lower()
            if not normalized_domain:
                continue
            mapping.setdefault(normalized_domain, []).append(
                endpoint.rstrip("/"))

    return mapping
