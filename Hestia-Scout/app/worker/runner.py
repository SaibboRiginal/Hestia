import os
import time
import logging
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
)
from worker.pre_parser import pre_parse_records, select_representative_records
from worker.status_updater import StatusUpdater


logger = logging.getLogger("hestia_scout.runner")


class ScoutWorker:
    def __init__(self, target_domain: str, target_source: str, target_filter: str | None = None, target_filters: list[str] | None = None):
        self.target_domain = target_domain
        self.target_source = target_source
        configured_filters = target_filters if target_filters else [
            target_filter] if target_filter else []
        self.target_filters = [str(item).strip()
                               for item in configured_filters if str(item).strip()]

        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")

        self.vault = ArchiveClient(
            api_url="",
            hub_api_url=self.hub_api_url,
        )
        self.brain = get_extractor_brain()
        self.geocoder = GeocodingService(user_agent="hestia-scout-worker/1.0")
        self.status_updater = StatusUpdater(
            vault=self.vault, target_domain=target_domain
        )
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

    def _is_step_pending(self, payload: dict, step_name: str, legacy_key: str | None = None) -> bool:
        pending_steps = payload.get("pending_steps") if isinstance(
            payload.get("pending_steps"), dict) else {}
        if pending_steps.get(step_name) is True:
            return True
        return bool(legacy_key and payload.get(legacy_key) is False)

    def _set_step_pending(self, payload: dict, step_name: str, pending: bool, legacy_key: str | None = None) -> dict:
        updated = dict(payload)
        pending_steps = updated.get("pending_steps") if isinstance(
            updated.get("pending_steps"), dict) else {}
        pending_steps = dict(pending_steps)
        pending_steps[step_name] = bool(pending)
        updated["pending_steps"] = pending_steps
        if legacy_key and legacy_key in updated:
            updated.pop(legacy_key, None)
        return updated

    def _publish_entity_event(self, entity_id: str, payload: dict) -> bool:
        """Publish entity.upserted to Hermes via Hub. Returns True on success."""
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
                logger.warning(
                    "event=hermes_route_call_failed_hub Hermes route call failed via Hub | entity_id=%s status=%s body=%s",
                    entity_id,
                    response.status_code,
                    response.text[:250],
                )
                return False

            routed = response.json() or {}
            routed_status = int(routed.get("status_code", 500) or 500)
            if routed_status >= 400:
                logger.warning(
                    "event=hermes_rejected_event_hub Hermes rejected event via Hub | entity_id=%s routed_status=%s target=%s payload=%s",
                    entity_id,
                    routed_status,
                    routed.get("target"),
                    str(routed.get("payload"))[:250],
                )
                return False

            logger.info(
                "event=hermes_event_published_hub Hermes event published via Hub | entity_id=%s target=%s",
                entity_id,
                routed.get("target"),
            )
            return True
        except Exception as error:
            logger.warning(
                "event=failed_publishing_event_hermes_hub Failed publishing event to Hermes via Hub | error=%s",
                error,
            )
            return False

    def reconcile_entities(self):
        logger.info(
            "event=scout_reconciliation_checking_existing_entities \n[🧹] Scout reconciliation: checking existing entities for missing geo/date/url...")

        records = self.vault.get_entity_records(
            domain=self.target_domain, status="active", limit=2000)
        if not records:
            logger.info(
                "event=active_entities_found_reconciliation [🧹] No active entities found for reconciliation.")
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

        logger.info(
            "event=reconciliation_geo_enrichment_complete_entities Reconciliation geo enrichment complete | enriched=%s",
            enriched,
        )

        # ── Listing enrichment retry ───────────────────────────────────────────
        # Any entity with pending_steps.listing_content_enrichment=true
        # is retried here (legacy atlas_enriched=False is still read).
        if self.enable_listing_enrichment:
            enrichment_retried = 0
            enrichment_failed_again = 0
            for record in records:
                entity_id = record.get("entity_id")
                payload = record.get("payload") if isinstance(
                    record.get("payload"), dict) else {}
                if not entity_id or not payload:
                    continue

                if not self._is_step_pending(
                    payload,
                    "listing_content_enrichment",
                    legacy_key="atlas_enriched",
                ):
                    continue

                logger.info(
                    "event=retrying_listing_enrichment Retrying listing enrichment | entity_id=%s",
                    entity_id,
                )
                enriched_payload = enrich_payload_from_listing(payload)
                if self._is_step_pending(
                    enriched_payload,
                    "listing_content_enrichment",
                    legacy_key="atlas_enriched",
                ):
                    enrichment_failed_again += 1
                    continue

                enriched_payload = self._set_step_pending(
                    enriched_payload,
                    "listing_content_enrichment",
                    False,
                    legacy_key="atlas_enriched",
                )

                upsert_payload = {
                    "entity_id": str(entity_id),
                    "domain": record.get("domain", self.target_domain),
                    "status": record.get("status", "active"),
                    "payload": enriched_payload,
                }
                if self.vault.upsert_entity(upsert_payload):
                    enrichment_retried += 1
                    logger.info(
                        "event=listing_enrichment_succeeded Listing enrichment succeeded | entity_id=%s",
                        entity_id,
                    )

            if enrichment_retried or enrichment_failed_again:
                logger.info(
                    "event=listing_enrichment_retry_complete Listing enrichment retry complete | succeeded=%s pending=%s",
                    enrichment_retried,
                    enrichment_failed_again,
                )

        # ── Notification retry ──────────────────────────────────────────────────
        # Entities marked pending for dispatch were successfully stored in
        # Archive but the Hermes/Hub call failed at the time. Re-fetch fresh
        # records (enrichment retry above may have just updated some of them)
        # and notify Hermes for any that are still pending.
        # We intentionally notify even if enrichment is still pending — the user
        # deserves to know about the entity even with partial data.
        logger.info(
            "event=checking_entities_pending_hermes_notification [🔔] Checking for entities pending Hermes notification...")
        fresh_records = self.vault.get_entity_records(
            domain=self.target_domain, status="active", limit=2000)
        hermes_retried = 0
        hermes_still_pending = 0
        for record in (fresh_records or []):
            entity_id = record.get("entity_id")
            payload = record.get("payload") if isinstance(
                record.get("payload"), dict) else {}
            if not entity_id or not payload:
                continue
            if not self._is_step_pending(
                payload,
                "event_dispatch",
                legacy_key="hermes_notified",
            ):
                continue  # Not pending; skip

            logger.info(
                "event=retrying_hermes_notification Retrying Hermes notification | entity_id=%s",
                entity_id,
            )
            ok = self._publish_entity_event(entity_id, payload)
            if ok:
                # Clear the pending flag in archive
                notified_payload = self._set_step_pending(
                    payload,
                    "event_dispatch",
                    False,
                    legacy_key="hermes_notified",
                )
                self.vault.upsert_entity({
                    "entity_id": str(entity_id),
                    "domain": record.get("domain", self.target_domain),
                    "status": record.get("status", "active"),
                    "payload": notified_payload,
                })
                hermes_retried += 1
                logger.info(
                    "event=hermes_notification_sent Hermes notification sent | entity_id=%s",
                    entity_id,
                )
            else:
                hermes_still_pending += 1

        if hermes_retried or hermes_still_pending:
            logger.info(
                "event=hermes_retry_complete Hermes retry complete | notified=%s pending=%s",
                hermes_retried,
                hermes_still_pending,
            )

        cleanup_result = self.vault.cleanup_entities(
            domain=self.target_domain,
            required_fields=["url", "location.lat", "location.lon"],
            require_created_at=True,
            dry_run=False,
        )
        if cleanup_result:
            logger.info(
                "event=cleanup_complete_scanned_deleted Cleanup complete | scanned=%s deleted=%s",
                cleanup_result.get("scanned", 0),
                cleanup_result.get("deleted", 0),
            )

    def _trigger_fetch_for_filter(self, filter_query: str) -> int:
        command = {
            "domain": self.target_domain,
            "source": self.target_source,
            "filter_query": filter_query,
        }
        try:
            response = requests.post(
                f"{self.hub_api_url}/route/hecate/api/ingest/trigger",
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
                    logger.info(
                        "event=gateway_fetched_matching_items Gateway fetched matching items | fetched=%s",
                        fetched,
                    )
                    return fetched

            logger.warning(
                "event=gateway_error_hub Gateway error via Hub | status_code=%s detail=%s",
                response.status_code,
                response.text if response.status_code != 200 else routed.get(
                    "payload"),
            )
            return 0
        except Exception as error:
            logger.warning(
                "event=could_not_reach_gateway_hub Could not reach Gateway via Hub | error=%s",
                error,
            )
            return 0

    def command_gateway_to_fetch(self):
        if not self.target_filters:
            logger.info(
                "event=target_filters_configured_scout_ingestion \n[⚠] No target filters configured for Scout ingestion.")
            return

        total_fetched = 0
        for filter_query in self.target_filters:
            logger.info(
                "event=commanding_gateway_fetch Commanding Gateway fetch | filter_query=%s",
                filter_query,
            )
            total_fetched += self._trigger_fetch_for_filter(filter_query)

        logger.info(
            "event=gateway_fetch_round_complete Gateway fetch round complete | filters=%s total_fetched=%s",
            len(self.target_filters),
            total_fetched,
        )

    def run_cycle(self):
        """Main work cycle for the Scout worker.

        Optimized pipeline:
        1. Command Ingest to fetch new emails.
        2. Fetch all unevaluated email records.
        3. Pre-parse every email (no LLM) to extract listing URLs.
        4. Load all known entity IDs from Archive for the domain.
        5. Classify each URL as new or existing.
        6. Status-update path: existing URLs not covered by LLM records
           → keyword scan → patch listing_status if changed.
        7. LLM extraction path: one representative record per new URL
           (deduplicated) + unclassified records (no detected URLs).
        8. Mark all email records as parsed.
        """
        logger.info(
            "event=hestia_scout_activating_parser_extractor === Hestia-Scout: Activating Parser & Extractor ===")
        self._cycle_counter += 1

        if self.reconcile_every_cycles > 0 and self._cycle_counter % self.reconcile_every_cycles == 0:
            self.reconcile_entities()

        self.command_gateway_to_fetch()

        # ── 1. Fetch emails ──────────────────────────────────────────
        logger.info(
            "event=checking_vault_unread_emails \n[*] Checking Vault for unread emails...")
        pending_records = self.vault.get_unevaluated(domain=self.target_domain)
        if not pending_records:
            logger.info(
                "event=new_emails_found_going_back [*] No new emails found. Going back to sleep.")
            return

        if len(pending_records) < max(1, self.min_batch_size):
            logger.info(
                "event=only_emails_found Waiting for minimum batch size | emails_found=%s min_batch_size=%s",
                len(pending_records),
                self.min_batch_size,
            )
            return

        if self.batch_debounce_seconds > 0:
            logger.info(
                "event=debounce_window_active Debounce window active | seconds=%s",
                self.batch_debounce_seconds,
            )
            time.sleep(self.batch_debounce_seconds)
            pending_records = self.vault.get_unevaluated(
                domain=self.target_domain)
            if not pending_records:
                logger.info(
                    "event=pending_records_after_debounce [*] No pending records after debounce.")
                return

        logger.info(
            "event=found_unread_emails_process Found unread emails to process | count=%s",
            len(pending_records),
        )

        # ── 2. Pre-parse: extract URLs from all emails without LLM ───
        logger.info(
            "event=pre_parse_extracting_listing_urls [PRE-PARSE] Extracting listing URLs from all emails (no LLM)...")
        parsed = pre_parse_records(pending_records)

        total_unique_urls = len(parsed.url_to_record_ids)
        logger.info(
            "event=pre_parse_found_unique_listing Pre-parse URL summary | unique_urls=%s emails=%s unclassified=%s",
            total_unique_urls,
            len(pending_records),
            len(parsed.unclassified_record_ids),
        )

        # ── 3. Load all known entity IDs from Archive ────────────────
        logger.info(
            "event=dedup_loading_known_entity_ids [DEDUP] Loading known entity IDs from Archive...")
        known_entity_ids = self.vault.get_all_entity_ids(
            domain=self.target_domain)
        logger.info(
            "event=dedup_entities_already_archive Existing entities loaded from Archive | count=%s",
            len(known_entity_ids),
        )

        new_urls: set[str] = set()
        existing_urls: set[str] = set()
        for url in parsed.url_to_record_ids:
            if url in known_entity_ids:
                existing_urls.add(url)
            else:
                new_urls.add(url)

        logger.info(
            "event=dedup_classification_urls Dedup classification complete | new=%s existing=%s",
            len(new_urls),
            len(existing_urls),
        )

        # ── 4. Select representative records for LLM extraction ──────
        # One record per new URL (deduplicated) + all unclassified records.
        representative_ids = select_representative_records(
            new_urls=new_urls,
            url_to_record_ids=parsed.url_to_record_ids,
            record_id_to_clean_text=parsed.record_id_to_clean_text,
        )
        representative_ids.update(parsed.unclassified_record_ids)

        logger.info(
            "event=llm_records_queued_llm_extraction LLM extraction queue built | queued=%s new_urls=%s unclassified=%s",
            len(representative_ids),
            len(new_urls),
            len(parsed.unclassified_record_ids),
        )

        # ── 5. Status-update path for already-known listings ─────────
        # Only process existing URLs whose covering records are NOT already
        # going to the LLM (those will be re-upserted by the LLM path).
        status_update_count = 0
        for url in existing_urls:
            covering_record_ids = parsed.url_to_record_ids.get(url, [])
            if any(rid in representative_ids for rid in covering_record_ids):
                # The LLM path will refresh this entity — skip.
                continue

            combined_text = "\n\n".join(
                parsed.record_id_to_clean_text[rid]
                for rid in covering_record_ids
                if rid in parsed.record_id_to_clean_text
            )
            existing_entity = self.vault.get_entity_by_id(url) or {}
            updated = self.status_updater.check_and_update(
                entity_id=url,
                combined_email_text=combined_text,
                existing_entity=existing_entity,
            )
            if updated:
                status_update_count += 1

        logger.info(
            "event=status_existing_listing_updates Existing listing status updates complete | count=%s",
            status_update_count,
        )

        # ── 6. LLM extraction path ────────────────────────────────────
        if not representative_ids:
            logger.info(
                "event=llm_records_require_llm_extraction [LLM] No records require LLM extraction.")
        else:
            record_map = {r["id"]: r for r in pending_records}
            llm_records = [
                record_map[rid]
                for rid in representative_ids
                if rid in record_map
            ]

            batch_size = max(1, self.max_batch_size)
            batches = [
                llm_records[i: i + batch_size]
                for i in range(0, len(llm_records), batch_size)
            ]

            quota_exhausted = False
            for batch_index, batch in enumerate(batches):
                logger.info(
                    "event=llm_batch LLM batch start | batch_index=%s batch_total=%s batch_size=%s",
                    batch_index + 1,
                    len(batches),
                    len(batch),
                )
                quota_exhausted = self._process_llm_batch(
                    batch_index, batch, parsed.record_id_to_clean_text
                )
                if quota_exhausted:
                    break

                logger.info(
                    "event=cooling_down Cooling down for RPM limits | seconds=%s",
                    self.batch_cooldown_seconds,
                )
                time.sleep(max(0, self.batch_cooldown_seconds))

        # ── 7. Mark ALL email records as parsed ───────────────────────
        # Records that went through neither path (e.g. empty-text emails)
        # are marked skipped_empty so they don't accumulate.
        for record in pending_records:
            record_id = record["id"]
            clean_text = parsed.record_id_to_clean_text.get(record_id, "")
            if len(clean_text) <= 20:
                self.vault.save_evaluation(
                    record_id, {"status": "skipped_empty"})
            else:
                self.vault.save_evaluation(record_id, {"status": "parsed"})

        logger.info("event=cycle_complete \n[✓] Cycle complete.")

    # ─────────────────────────────────────────────────────────────────
    #  Private helpers
    # ─────────────────────────────────────────────────────────────────

    def _process_llm_batch(
        self,
        batch_index: int,
        batch: list[dict],
        record_id_to_clean_text: dict[int, str],
    ) -> bool:
        """Run LLM extraction on one batch of email records.

        Returns ``True`` if the quota was exhausted (caller should stop).
        """
        combined_text_to_read = ""
        for item_index, record in enumerate(batch):
            record_id = record["id"]
            clean_text = record_id_to_clean_text.get(record_id) or (
                record.get("payload", {}).get("body", "")
                + " "
                + record.get("payload", {}).get("title", "")
            )
            if isinstance(clean_text, str) and len(clean_text) > 20:
                combined_text_to_read += f"\n\n--- EMAIL {item_index + 1} ---\n{clean_text}"

        if not combined_text_to_read.strip():
            logger.info(
                "event=all_emails_this_batch_were [!] All emails in this batch were empty. Skipping.")
            return False

        ai_response = self.brain.evaluate(combined_text_to_read)
        raw_text = ai_response.get("raw_response", "").strip()

        if ai_response.get("error"):
            logger.warning(
                "event=ai_evaluate_error AI evaluate error | error=%s",
                ai_response.get("error"),
            )
            if "All models exhausted" in ai_response["error"]:
                logger.info(
                    "event=global_quota_hit_shutting_down [🛑] Global Quota hit. Shutting down for the day.")
                return True
            return False

        try:
            extracted_data = parse_ai_entities(raw_text)
            found_entities = 0
            logger.info(
                "event=ai_parsed_entities_from_ai Parsed entities from AI response | count=%s",
                len(extracted_data),
            )

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

                raw_summary = str(payload.get("summary", "")).strip(
                ) if isinstance(payload, dict) else ""
                raw_address = str(payload.get("address", "")).strip(
                ) if isinstance(payload, dict) else ""
                logger.info(
                    "event=ai_raw_entity AI raw entity | entity_id=%s",
                    entity_id,
                )
                logger.info(
                    "event=raw_summary_len_raw_address AI raw fields | raw_summary_len=%s raw_address=%s",
                    len(raw_summary),
                    raw_address,
                )
                if raw_summary and (raw_summary.endswith("...") or raw_summary.endswith("…")):
                    logger.warning(
                        "event=ai_returned_truncated_summary AI returned truncated summary | preview=%s",
                        raw_summary[:150],
                    )

                normalized_entity_id = normalize_listing_url(str(entity_id))
                payload_url = payload.get("url") if isinstance(
                    payload, dict) else None
                if payload_url:
                    payload["url"] = normalize_listing_url(str(payload_url))
                else:
                    payload["url"] = normalized_entity_id

                payload = enrich_payload_geolocation(payload, self.geocoder)
                if self.enable_listing_enrichment:
                    payload = enrich_payload_from_listing(payload)

                house = HouseEntity.from_extracted(
                    entity_id=normalized_entity_id,
                    payload=payload,
                    domain=self.target_domain,
                    status=item.get("status", "active"),
                )
                normalized_entity_id = house.entity_id
                payload = house.payload.model_dump()

                final_summary = str(payload.get("summary", "")).strip()
                final_address = str(payload.get("address", "")).strip()
                final_location = payload.get("location") if isinstance(
                    payload.get("location"), dict) else {}
                has_geo = final_location.get("lat") is not None
                summary_truncated = final_summary.endswith(
                    "...") or final_summary.endswith("…")
                logger.info(
                    "event=entity_processed Entity processed | entity_id=%s",
                    normalized_entity_id,
                )
                logger.info(
                    "event=address_geo Entity address and geo | address=%s geo=%s",
                    final_address,
                    "yes" if has_geo else "no",
                )
                logger.info(
                    "event=summary_len_truncated Entity summary stats | summary_len=%s truncated=%s",
                    len(final_summary),
                    summary_truncated,
                )
                if summary_truncated:
                    logger.warning(
                        "event=truncated_summary Truncated summary | preview=%s",
                        final_summary[:150],
                    )

                entity_upsert_payload = house.to_archive_upsert_payload()
                if self.vault.upsert_entity(entity_upsert_payload):
                    found_entities += 1
                    ok = self._publish_entity_event(
                        entity_id=normalized_entity_id,
                        payload=payload,
                    )
                    if not ok:
                        # Mark as pending notification so reconcile can retry
                        # when Hermes / Hub recovers.
                        pending_payload = self._set_step_pending(
                            payload,
                            "event_dispatch",
                            True,
                            legacy_key="hermes_notified",
                        )
                        self.vault.upsert_entity({
                            "entity_id": str(normalized_entity_id),
                            "domain": self.target_domain,
                            "status": house.status,
                            "payload": pending_payload,
                        })

            logger.info(
                "event=extracted_entities_using Extracted entities | count=%s model=%s",
                found_entities,
                ai_response.get("model_used"),
            )

        except Exception as error:
            logger.warning(
                "event=failed_parse_ai_json Failed to parse AI JSON | error=%s",
                error,
            )
            with open(f"debug_broken_batch_{batch_index}.txt", "w", encoding="utf-8") as handle:
                handle.write(raw_text)

        return False
