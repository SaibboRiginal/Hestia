import os
import time
import requests

from core.archive_client import ArchiveClient
from domain.house_entity import HouseEntity
from tools.geocoding import GeocodingService
from worker.extractor import (
    enrich_payload_from_listing,
    enrich_payload_geolocation,
    get_extractor_brain,
    normalize_listing_url,
    parse_ai_entities,
    sanitize_email_for_ai,
)


class ScoutWorker:
    def __init__(self, target_domain: str, target_source: str, target_filter: str | None = None, target_filters: list[str] | None = None):
        self.target_domain = target_domain
        self.target_source = target_source
        configured_filters = target_filters if target_filters else [
            target_filter] if target_filter else []
        self.target_filters = [str(item).strip()
                               for item in configured_filters if str(item).strip()]

        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:8005/api").rstrip("/")

        self.vault = ArchiveClient(
            api_url="",
            hub_api_url=self.hub_api_url,
        )
        self.brain = get_extractor_brain()
        self.geocoder = GeocodingService(user_agent="hestia-scout-worker/1.0")
        self.reconcile_every_cycles = int(
            os.getenv("SCOUT_RECONCILE_EVERY_CYCLES", "1"))
        self.min_batch_size = int(os.getenv("SCOUT_MIN_BATCH_SIZE", "1"))
        self.max_batch_size = int(os.getenv("SCOUT_MAX_BATCH_SIZE", "5"))
        self.batch_debounce_seconds = int(
            os.getenv("SCOUT_BATCH_DEBOUNCE_SECONDS", "45"))
        self.batch_cooldown_seconds = int(
            os.getenv("SCOUT_BATCH_COOLDOWN_SECONDS", "15"))
        self.enable_listing_enrichment = os.getenv(
            "SCOUT_ENABLE_LISTING_ENRICHMENT", "1").strip().lower() not in {"0", "false", "no"}
        self._cycle_counter = 0

    def _publish_entity_event(self, entity_id: str, payload: dict):
        event_payload = {
            "event_type": "entity.upserted",
            "domain": self.target_domain,
            "entity_id": str(entity_id),
            "payload": payload,
        }
        route_body = {
            "method": "POST",
            "body": event_payload,
            "headers": {},
            "query": {},
            "timeout_seconds": 8,
        }
        hub_endpoint = f"{self.hub_api_url}/route/hermes/api/events/ingest"
        try:
            response = requests.post(
                hub_endpoint,
                json=route_body,
                timeout=8,
            )
            if response.status_code != 200:
                print(
                    f"[!] Hermes route call failed via Hub | entity_id={entity_id} status={response.status_code} body={response.text[:250]}"
                )
                return

            routed = response.json() or {}
            routed_status = int(routed.get("status_code", 500) or 500)
            if routed_status >= 400:
                print(
                    f"[!] Hermes rejected event via Hub | entity_id={entity_id} routed_status={routed_status} target={routed.get('target')} payload={str(routed.get('payload'))[:250]}"
                )
                return

            print(
                f"[✓] Hermes event published via Hub | entity_id={entity_id} target={routed.get('target')}"
            )
        except Exception as error:
            print(f"[!] Failed publishing event to Hermes via Hub: {error}")

    def reconcile_entities(self):
        print(
            "\n[🧹] Scout reconciliation: checking existing entities for missing geo/date/url...")

        records = self.vault.get_entity_records(
            domain=self.target_domain, status="active", limit=2000)
        if not records:
            print("[🧹] No active entities found for reconciliation.")
            return

        enriched = 0
        for record in records:
            entity_id = record.get("entity_id")
            payload = record.get("payload") if isinstance(
                record.get("payload"), dict) else {}
            if not entity_id or not payload:
                continue

            location = payload.get("location") if isinstance(
                payload.get("location"), dict) else {}
            has_geo = location.get("lat") is not None and location.get(
                "lon") is not None
            if has_geo:
                continue

            enriched_payload = enrich_payload_geolocation(
                payload, self.geocoder)
            new_location = enriched_payload.get("location") if isinstance(
                enriched_payload.get("location"), dict) else {}
            if new_location.get("lat") is None or new_location.get("lon") is None:
                continue

            upsert_payload = {
                "entity_id": str(entity_id),
                "domain": record.get("domain", self.target_domain),
                "status": record.get("status", "active"),
                "payload": enriched_payload,
            }
            if self.vault.upsert_entity(upsert_payload):
                enriched += 1

        print(
            f"[🧹] Reconciliation geo enrichment complete: {enriched} entities updated.")

        cleanup_result = self.vault.cleanup_entities(
            domain=self.target_domain,
            required_fields=["url", "location.lat", "location.lon"],
            require_created_at=True,
            dry_run=False,
        )
        if cleanup_result:
            print(
                f"[🧹] Cleanup complete: scanned={cleanup_result.get('scanned', 0)} deleted={cleanup_result.get('deleted', 0)}")

    def _trigger_fetch_for_filter(self, filter_query: str) -> int:
        command = {
            "domain": self.target_domain,
            "source": self.target_source,
            "filter_query": filter_query,
        }
        try:
            response = requests.post(
                f"{self.hub_api_url}/route/ingest/api/ingest/trigger",
                json={
                    "method": "POST",
                    "headers": {},
                    "query": {},
                    "body": command,
                    "timeout_seconds": 8,
                },
                timeout=9,
            )
            if response.status_code == 200:
                routed = response.json() or {}
                status_code = int(routed.get("status_code", 500))
                payload = routed.get("payload") or {}
                if status_code < 400:
                    fetched = int(payload.get("fetched", 0) or 0)
                    print(f"[✓] Gateway fetched {fetched} matching items.")
                    return fetched

            print(
                f"[!] Gateway error via Hub: {response.text if response.status_code != 200 else routed.get('payload')}")
            return 0
        except Exception as error:
            print(f"[-] Could not reach Gateway via Hub: {error}")
            return 0

    def command_gateway_to_fetch(self):
        if not self.target_filters:
            print("\n[⚠] No target filters configured for Scout ingestion.")
            return

        total_fetched = 0
        for filter_query in self.target_filters:
            print(f"\n[⚡] Commanding Gateway to fetch: {filter_query}...")
            total_fetched += self._trigger_fetch_for_filter(filter_query)

        print(
            f"[✓] Gateway fetch round complete across {len(self.target_filters)} filter(s). Total fetched: {total_fetched}")

    def run_cycle(self):
        print("=== Hestia-Scout: Activating Parser & Extractor ===")
        self._cycle_counter += 1

        if self.reconcile_every_cycles > 0 and self._cycle_counter % self.reconcile_every_cycles == 0:
            self.reconcile_entities()

        self.command_gateway_to_fetch()

        print("\n[*] Checking Vault for unread emails...")
        pending_records = self.vault.get_unevaluated(domain=self.target_domain)
        if not pending_records:
            print("[*] No new emails found. Going back to sleep.")
            return

        if len(pending_records) < max(1, self.min_batch_size):
            print(
                f"[*] Only {len(pending_records)} emails found. Waiting for minimum batch size {self.min_batch_size}.")
            return

        if self.batch_debounce_seconds > 0:
            print(
                f"[*] Debounce window active ({self.batch_debounce_seconds}s) to accumulate near-simultaneous emails.")
            time.sleep(self.batch_debounce_seconds)
            pending_records = self.vault.get_unevaluated(
                domain=self.target_domain)
            if not pending_records:
                print("[*] No pending records after debounce.")
                return

        print(f"[*] Found {len(pending_records)} unread emails to parse.\n")

        batch_size = max(1, self.max_batch_size)
        batches = [pending_records[i: i + batch_size]
                   for i in range(0, len(pending_records), batch_size)]

        for batch_index, batch in enumerate(batches):
            print(
                f"\n-> Processing Batch {batch_index + 1}/{len(batches)} (Contains {len(batch)} emails)...")

            combined_text_to_read = ""
            record_ids_in_batch = []

            for item_index, record in enumerate(batch):
                record_id = record["id"]
                record_ids_in_batch.append(record_id)

                raw_html = record["payload"].get(
                    "body", "") + " " + record["payload"].get("title", "")
                clean_text = sanitize_email_for_ai(raw_html)

                if len(clean_text) > 20:
                    combined_text_to_read += f"\n\n--- EMAIL {item_index + 1} ---\n{clean_text}"
                else:
                    self.vault.save_evaluation(
                        record_id, {"status": "skipped_empty"})

            if not combined_text_to_read.strip():
                print("   [!] All emails in this batch were empty. Skipping.")
                continue

            ai_response = self.brain.evaluate(combined_text_to_read)
            raw_text = ai_response.get("raw_response", "").strip()

            if ai_response.get("error"):
                print(f"   [!] {ai_response['error']}")
                if "All models exhausted" in ai_response["error"]:
                    print("   [🛑] Global Quota hit. Shutting down for the day.")
                    break
                continue

            try:
                extracted_data = parse_ai_entities(raw_text)
                found_entities = 0
                print(
                    f"   [AI] Parsed {len(extracted_data)} entities from AI response")

                for item in extracted_data:
                    entity_id = item.get("entity_id")
                    payload = item.get("payload")

                    if not isinstance(payload, dict):
                        payload = item
                        entity_id = entity_id or item.get("url")
                    elif not entity_id:
                        entity_id = payload.get("url")

                    if not entity_id or entity_id in ["", "null", None]:
                        continue

                    # Log raw AI extraction before enrichment
                    raw_summary = str(payload.get("summary", "")).strip(
                    ) if isinstance(payload, dict) else ""
                    raw_address = str(payload.get("address", "")).strip(
                    ) if isinstance(payload, dict) else ""
                    print(f"   [AI-RAW] entity={entity_id}")
                    print(
                        f"      raw_summary_len={len(raw_summary)} raw_address='{raw_address}'")
                    if raw_summary and (raw_summary.endswith("...") or raw_summary.endswith("…")):
                        print(
                            f"      WARNING: AI returned truncated summary: {raw_summary[:150]}")

                    normalized_entity_id = normalize_listing_url(
                        str(entity_id))
                    payload_url = payload.get("url") if isinstance(
                        payload, dict) else None
                    if payload_url:
                        payload["url"] = normalize_listing_url(
                            str(payload_url))
                    else:
                        payload["url"] = normalized_entity_id

                    payload = enrich_payload_geolocation(
                        payload, self.geocoder)
                    if self.enable_listing_enrichment:
                        payload = enrich_payload_from_listing(payload)

                    # Canonicalize the entity shape before Archive upsert.
                    house = HouseEntity.from_extracted(
                        entity_id=normalized_entity_id,
                        payload=payload,
                        domain=self.target_domain,
                        status=item.get("status", "active"),
                    )
                    normalized_entity_id = house.entity_id
                    payload = house.payload.model_dump()

                    # Log final payload state before upsert
                    final_summary = str(payload.get("summary", "")).strip()
                    final_address = str(payload.get("address", "")).strip()
                    final_location = payload.get("location") if isinstance(
                        payload.get("location"), dict) else {}
                    has_geo = final_location.get("lat") is not None
                    summary_truncated = final_summary.endswith(
                        "...") or final_summary.endswith("…")
                    print(f"   [ENTITY] {normalized_entity_id}")
                    print(
                        f"      address='{final_address}' geo={'yes' if has_geo else 'NO'}")
                    print(
                        f"      summary_len={len(final_summary)} truncated={summary_truncated}")
                    if summary_truncated:
                        print(
                            f"      WARNING: Truncated summary: {final_summary[:150]}")

                    entity_upsert_payload = house.to_archive_upsert_payload()
                    if self.vault.upsert_entity(entity_upsert_payload):
                        found_entities += 1
                        self._publish_entity_event(
                            entity_id=normalized_entity_id,
                            payload=payload,
                        )

                print(
                    f"   [✓] Extracted {found_entities} entities using {ai_response.get('model_used')}.")

                for record_id in record_ids_in_batch:
                    self.vault.save_evaluation(record_id, {"status": "parsed"})

            except Exception as error:
                print(f"   [!] Failed to parse AI JSON: {error}")
                with open(f"debug_broken_batch_{batch_index}.txt", "w", encoding="utf-8") as handle:
                    handle.write(raw_text)

            print(
                f"   [-] Sleeping for {self.batch_cooldown_seconds} seconds to respect RPM limits...")
            time.sleep(max(0, self.batch_cooldown_seconds))

        print("\n[✓] All batches processed.")
