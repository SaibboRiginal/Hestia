import time
import logging
import requests


logger = logging.getLogger(f"hestia_oracle.{__name__}")


class ModuleToolRegistry:
    def __init__(self, module_tool_urls: list[str], ttl_seconds: int = 120, hub_api_url: str | None = None):
        self.module_tool_urls = [
            u.rstrip("/") for u in module_tool_urls if u and u.strip()]
        self.ttl_seconds = ttl_seconds
        self.hub_api_url = hub_api_url.rstrip("/") if hub_api_url else None
        self._last_refresh = 0.0
        self._domain_to_urls: dict[str, list[str]] = {}
        self._domain_to_services: dict[str, list[str]] = {}
        # Per-service topology tags from Hub registry (name → set of tags)
        self._service_topology: dict[str, set[str]] = {}

    def _needs_refresh(self) -> bool:
        return (time.time() - self._last_refresh) > self.ttl_seconds or not self._domain_to_urls

    def refresh(self):
        mapping: dict[str, list[str]] = {}
        service_mapping: dict[str, list[str]] = {}
        if self.hub_api_url:
            try:
                response = requests.get(
                    f"{self.hub_api_url}/discovery/module-tools", timeout=4)
                if response.status_code == 200:
                    hub_mapping = response.json().get("mapping", {}) or {}
                    if isinstance(hub_mapping, dict):
                        for domain, urls in hub_mapping.items():
                            normalized_domain = str(domain).strip().lower()
                            if not normalized_domain:
                                continue
                            for endpoint in (urls or []):
                                endpoint_val = str(
                                    endpoint).strip().rstrip("/")
                                if endpoint_val:
                                    mapping.setdefault(
                                        normalized_domain, []).append(endpoint_val)
                        logger.info(
                            "event=module_registry_hydrated_from_hub Module registry hydrated from Hub with %s domain(s)", len(mapping))
            except Exception as error:
                logger.warning("event=hub_discovery_failed Hub discovery failed: %s", error)

            try:
                services_response = requests.get(
                    f"{self.hub_api_url}/registry/services", timeout=4)
                if services_response.status_code == 200:
                    services = services_response.json().get("services", []) or []
                    topo_cache: dict[str, set[str]] = {}
                    for service in services:
                        service_name = str(service.get(
                            "name", "")).strip().lower()
                        capabilities = service.get("capabilities") if isinstance(
                            service.get("capabilities"), dict) else {}
                        # Cache topology tags for dynamic domain-owner resolution
                        raw_tags = service.get("topology_tags") or []
                        topo_cache[service_name] = {str(t).strip().lower() for t in raw_tags if str(t).strip()}
                        for domain in capabilities.get("module_tool_domains", []) or []:
                            normalized_domain = str(domain).strip().lower()
                            if not normalized_domain or not service_name:
                                continue
                            service_mapping.setdefault(
                                normalized_domain, []).append(service_name)
                    self._service_topology = topo_cache
            except Exception as error:
                logger.warning(
                    "event=hub_services_registry_lookup_failed Hub services registry lookup failed: %s", error)

        logger.info("event=refreshing_module_tool_registry_from Refreshing module tool registry from %s endpoint(s)", len(
            self.module_tool_urls))
        for base_url in self.module_tool_urls:
            try:
                response = requests.get(f"{base_url}/domains", timeout=4)
                if response.status_code != 200:
                    logger.warning(
                        "event=module_registry_source_returned_status Module registry source %s returned status %s", base_url, response.status_code)
                    continue
                domains = response.json().get("domains", [])
                logger.info(
                    "event=module_registry_source_exposes_domains Module registry source %s exposes domains: %s", base_url, domains)
                for domain in domains:
                    normalized_domain = str(domain).strip().lower()
                    if not normalized_domain:
                        continue
                    mapping.setdefault(normalized_domain, []).append(base_url)
            except Exception as error:
                logger.warning("event=failed_refreshing_from Failed refreshing from %s: %s",
                               base_url, error)
                continue

        for domain, urls in mapping.items():
            mapping[domain] = list(dict.fromkeys(urls))

        for domain, services in service_mapping.items():
            service_mapping[domain] = list(dict.fromkeys(services))

        self._domain_to_urls = mapping
        self._domain_to_services = service_mapping
        self._last_refresh = time.time()
        logger.info("event=module_registry_cache_refreshed Module registry cache refreshed: %s",
                    self._domain_to_urls)

    def get_services_for_domain(self, domain: str) -> list[str]:
        if self._needs_refresh():
            self.refresh()
        return self._domain_to_services.get(str(domain).strip().lower(), [])

    def get_domain_owners(self, domain: str) -> list[str]:
        """Return only the domain-OWNING services for *domain*.

        A service is considered a domain owner when it declares
        ``layer:domain`` in its Hub topology_tags.  Gateways (layer:gateway),
        foundations (layer:foundation), and cognition services may share a
        domain tag but are NOT domain owners — their tools are filtered out
        so the LLM sees only the primary domain service's tools.
        """
        if self._needs_refresh():
            self.refresh()
        candidates = self._domain_to_services.get(str(domain).strip().lower(), [])
        return [
            svc for svc in candidates
            if "layer:domain" in self._service_topology.get(svc, set())
        ]

    def get_urls_for_domain(self, domain: str) -> list[str]:
        if self._needs_refresh():
            self.refresh()
        return self._domain_to_urls.get(str(domain).strip().lower(), [])

    def query(self, domain: str, payload: dict) -> list:
        if self.hub_api_url:
            for service_name in self.get_services_for_domain(domain):
                try:
                    start = time.perf_counter()
                    response = requests.post(
                        f"{self.hub_api_url}/route/{service_name}/api/module-tools/query",
                        json={
                            "method": "POST",
                            "headers": {},
                            "query": {},
                            "body": payload,
                            "timeout_seconds": 8,
                        },
                        timeout=9,
                    )
                    elapsed_ms = int((time.perf_counter() - start) * 1000)
                    if response.status_code != 200:
                        continue
                    routed = response.json() or {}
                    status_code = int(routed.get("status_code", 500))
                    if status_code >= 400:
                        continue
                    data = routed.get("payload")
                    if isinstance(data, list):
                        logger.info("event=hub_routed_module_tool_domain Hub-routed module tool %s for domain '%s' returned %s items in %sms",
                                    service_name, domain, len(data), elapsed_ms)
                        return data
                    if isinstance(data, dict) and isinstance(data.get("items"), list):
                        logger.info("event=hub_routed_module_tool_domain Hub-routed module tool %s for domain '%s' returned %s items in %sms",
                                    service_name, domain, len(data.get("items")), elapsed_ms)
                        return data.get("items")
                except Exception as error:
                    logger.warning(
                        "event=hub_routed_module_tool_query Hub-routed module tool query failure for %s domain '%s': %s", service_name, domain, error)

        candidate_urls = self.get_urls_for_domain(domain)
        if not candidate_urls:
            logger.info("event=module_tool_registered_domain No module tool registered for domain '%s'", domain)
            return []

        for base_url in candidate_urls:
            try:
                start = time.perf_counter()
                response = requests.post(
                    f"{base_url}/query", json=payload, timeout=8)
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                if response.status_code != 200:
                    logger.warning("event=module_tool_query_domain_returned Module tool %s/query for domain '%s' returned %s in %sms",
                                   base_url, domain, response.status_code, elapsed_ms)
                    continue
                data = response.json()
                if isinstance(data, list):
                    logger.info("event=module_tool_query_domain_returned Module tool %s/query for domain '%s' returned %s items in %sms",
                                base_url, domain, len(data), elapsed_ms)
                    return data
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    logger.info("event=module_tool_query_domain_returned Module tool %s/query for domain '%s' returned %s items in %sms",
                                base_url, domain, len(data.get("items")), elapsed_ms)
                    return data.get("items")
                logger.warning(
                    "event=module_tool_query_domain_returned Module tool %s/query for domain '%s' returned unexpected payload", base_url, domain)
            except Exception as error:
                logger.warning(
                    "event=module_tool_query_failure_domain Module tool query failure for %s domain '%s': %s", base_url, domain, error)
                continue

        return []
