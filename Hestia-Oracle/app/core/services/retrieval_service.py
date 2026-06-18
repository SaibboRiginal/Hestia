import requests
import time
import logging


logger = logging.getLogger(f"hestia_oracle.{__name__}")


class RetrievalService:
    def __init__(self, archive_url: str, hub_api_url: str, module_registry, embedder):
        self.archive_url = archive_url
        self.hub_api_url = hub_api_url.rstrip("/")
        self.module_registry = module_registry
        self.embedder = embedder

    def retrieve_entities(
        self,
        user_message: str,
        session_id: str,
        valid_domains: list[str],
        preference_facts: list[str],
        active_filters: dict,
        filters_gt: dict,
        filters_lt: dict,
        sort_by: str | None,
        sort_order: str,
    ) -> list:
        all_entities = []
        query_vector = self.embedder(user_message) if any(
            d != "general" for d in valid_domains) else None
        if query_vector:
            logger.info("event=embedding_generated_with_dimensions Embedding generated with %s dimensions",
                        len(query_vector))
        else:
            logger.info(
                "event=embedding_used_this_query_general No embedding used for this query (general-only route)")

        for domain in valid_domains:
            if domain == "general":
                continue

            logger.info("event=retrieval_start_domain Retrieval start for domain '%s'", domain)
            domain_start = time.perf_counter()

            module_payload = {
                "domain": domain,
                "query": user_message,
                "session_id": session_id,
                "limit": 30,
                "filters": active_filters or {},
                "filters_gt": filters_gt or {},
                "filters_lt": filters_lt or {},
                "sort_by": sort_by,
                "sort_order": sort_order or "desc",
                "preferences": preference_facts or [],
            }
            entities = self.module_registry.query(domain, module_payload)
            source = "module_tool"
            if not entities:
                source = "archive_fallback"
                entities = self._archive_search(
                    domain=domain,
                    active_filters=active_filters,
                    filters_gt=filters_gt,
                    filters_lt=filters_lt,
                    sort_by=sort_by,
                    sort_order=sort_order,
                    query_vector=query_vector,
                )

            elapsed_ms = int((time.perf_counter() - domain_start) * 1000)
            logger.info(
                "event=retrieval_complete_domain_item_ms Retrieval complete for domain '%s': %s item(s) via %s in %sms",
                domain,
                len(entities),
                source,
                elapsed_ms,
            )
            all_entities.extend(entities)

        return all_entities

    def _archive_search(
        self,
        domain: str,
        active_filters: dict,
        filters_gt: dict,
        filters_lt: dict,
        sort_by: str | None,
        sort_order: str,
        query_vector,
    ) -> list:
        try:
            start = time.perf_counter()
            response = requests.post(
                f"{self.hub_api_url}/route/archive/api/entities/search",
                json={
                    "method": "POST",
                    "headers": {},
                    "query": {},
                    "body": {
                        "domain": domain,
                        "limit": 40,
                        "filters": active_filters,
                        "filters_gt": filters_gt,
                        "filters_lt": filters_lt,
                        "sort_by": sort_by,
                        "sort_order": sort_order,
                        "query_vector": query_vector,
                    },
                    "timeout_seconds": 8,
                },
                timeout=9,
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            if response.status_code == 200:
                routed = response.json() or {}
                status_code = int(routed.get("status_code", 500))
                data = routed.get("payload") if status_code < 400 else []
                if not isinstance(data, list):
                    data = []
                logger.info("event=archive_search_domain_returned_item Archive search domain '%s' returned %s item(s) in %sms", domain, len(
                    data), elapsed_ms)
                return data
            logger.warning("event=archive_search_domain_returned_status Archive search domain '%s' returned status %s in %sms",
                           domain, response.status_code, elapsed_ms)
        except Exception as error:
            logger.warning(
                "event=archive_search_failed_domain Archive search failed for domain '%s': %s", domain, error)
            pass
        return []
