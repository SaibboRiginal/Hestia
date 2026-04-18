"""Status updater for real estate listings that are already stored in Archive.

When an email mentions a listing we already know about, there is no need to
run a full LLM extraction.  This module checks whether the email text signals
a status change and, if so, patches only the ``listing_status`` field of the
stored entity payload — leaving all other enriched data intact.
"""

from __future__ import annotations

from domain.listing_status import ListingStatus, detect_listing_status
from core.archive_client import ArchiveClient


class StatusUpdater:
    """Checks for listing-status changes and patches Archive entities.

    Parameters
    ----------
    vault:
        An initialised ``ArchiveClient`` used to load current entity state
        and write partial updates.
    target_domain:
        The Archive domain under which real estate entities are stored.
    """

    def __init__(self, vault: ArchiveClient, target_domain: str) -> None:
        self._vault = vault
        self._target_domain = target_domain

    # ─────────────────────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────────────────────

    def check_and_update(
        self,
        entity_id: str,
        combined_email_text: str,
        existing_entity: dict,
    ) -> bool:
        """Detect status change from email text and patch Archive if needed.

        Returns ``True`` when the Archive was updated, ``False`` otherwise.
        A return value of ``False`` does **not** indicate an error — it simply
        means no update was necessary.
        """
        detected = detect_listing_status(combined_email_text)

        if detected is ListingStatus.UNKNOWN:
            print(
                f"[STATUS] No status signal for {entity_id} \u2014 keeping existing status."
            )
            return False

        existing_payload = (
            existing_entity.get("payload")
            if isinstance(existing_entity.get("payload"), dict)
            else {}
        )
        current_raw = existing_payload.get("listing_status", "unknown")
        current = _coerce_safely(current_raw)

        if detected == current:
            print(
                f"[STATUS] Status unchanged ({current.value}) for {entity_id}."
            )
            return False

        print(
            f"[STATUS] Status change detected for {entity_id}: "
            f"{current.value} \u2192 {detected.value}"
        )

        updated_payload = dict(existing_payload)
        updated_payload["listing_status"] = detected.value

        upsert_body = {
            "entity_id": entity_id,
            "domain": existing_entity.get("domain", self._target_domain),
            "status": existing_entity.get("status", "active"),
            "payload": updated_payload,
        }
        return self._vault.upsert_entity(upsert_body)


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

def _coerce_safely(raw: object) -> ListingStatus:
    try:
        return ListingStatus(str(raw).strip().lower())
    except ValueError:
        return ListingStatus.UNKNOWN
