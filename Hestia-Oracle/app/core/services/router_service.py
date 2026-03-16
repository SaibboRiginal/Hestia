import json


class RouterService:
    def __init__(self, router_agent, fallback_router_agent):
        self.router = router_agent
        self.fallback_router = fallback_router_agent

    def route(self, route_prompt: str, available_domains: list[str]):
        selected_domains = ["general"]
        active_filters = {}
        filters_gt = {}
        filters_lt = {}
        sort_by = None
        sort_order = "desc"

        try:
            router_response = self.router.ask(route_prompt).strip()
        except Exception:
            router_response = self.fallback_router.ask(route_prompt).strip()

        try:
            start_idx, end_idx = router_response.find(
                "{"), router_response.rfind("}")
            if start_idx != -1 and end_idx != -1:
                route_data = json.loads(
                    router_response[start_idx: end_idx + 1])
                selected_domains = [str(d).lower() for d in (
                    route_data.get("domains") or ["general"])]
                active_filters = route_data.get("filters") or {}
                filters_gt = route_data.get("filters_gt") or {}
                filters_lt = route_data.get("filters_lt") or {}
                sort_by = route_data.get("sort_by")
                sort_order = "asc" if str(route_data.get(
                    "sort_order", "desc")).lower() == "asc" else "desc"
        except Exception:
            pass

        valid_domains = [
            d for d in selected_domains if d in available_domains or d == "general"] or ["general"]
        return valid_domains, active_filters, filters_gt, filters_lt, sort_by, sort_order
