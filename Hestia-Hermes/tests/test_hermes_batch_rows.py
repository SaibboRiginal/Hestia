"""Entity batch rows (core review 2026-11-27): a queued listing never stays «queued» forever.

Before the fix the Archive row of a batched entity stayed ``queued`` (an active state that blocks dedupe) after the
batch was sent, after Hermes gave up, and after a restart during the settling window: in the last two cases the
listing was never notified again.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _clean_queues():
    from modules import entity_batch_dispatcher as d
    with d._queues_lock:
        for entry in d._queues.values():
            if entry.timer:
                entry.timer.cancel()
        d._queues.clear()
    yield
    with d._queues_lock:
        for entry in d._queues.values():
            if entry.timer:
                entry.timer.cancel()
        d._queues.clear()


@pytest.mark.unit
class TestBatchRows:
    def test_published_batch_marks_rows_delivered(self):
        from modules import entity_batch_dispatcher as d
        writer = MagicMock()
        d.set_publisher(lambda *a, **k: True, writer)
        d.enqueue_entity(subscription_id=1, channel_type="all", channel_target="", domain="real_estate",
                         entity_id="e1", payload={"title": "Flat"}, filters={}, row_id="r1")
        key = d._queue_key(1, "all", "")
        with patch.object(d, "narrate", return_value="text"):
            d._flush(key)
        writer.assert_called_once_with("r1", "delivered", "published in entity batch")

    def test_given_up_batch_marks_rows_failed(self):
        from modules import entity_batch_dispatcher as d
        writer = MagicMock()
        d.set_publisher(lambda *a, **k: False, writer)
        d.enqueue_entity(subscription_id=2, channel_type="all", channel_target="", domain="real_estate",
                         entity_id="e2", payload={"title": "House"}, filters={}, row_id="r2")
        key = d._queue_key(2, "all", "")
        entry = d._queues[key]
        entry.attempts = 99      # next failure is the last one
        with patch.object(d, "narrate", return_value=""):
            d._flush(key)
        writer.assert_called_once_with("r2", "failed", "entity batch gave up")

    def test_restore_puts_queued_rows_back(self):
        from modules import entity_batch_dispatcher as d
        rows = [{"outbound_event_id": "r3", "subscription_id": "7", "domain": "real_estate", "entity_id": "e3",
                 "payload": {"event_payload": {"title": "Loft"}, "audience_key": "client:webui:s1",
                             "filters": {"city": "Lugano"}}},
                {"outbound_event_id": "r4", "payload": {}}]           # nothing to send: skipped
        assert d.restore_queued(rows) == 1
        entry = d._queues[d._queue_key("7", "client:webui:s1", "")]
        assert entry.row_ids == ["r3"] and entry.entities == [{"title": "Loft"}]
        assert entry.filters == {"city": "Lugano"}


def _price_service(rows):
    from modules.service import HermesService
    svc = HermesService.__new__(HermesService)
    svc.archive = MagicMock()
    svc.notifications = MagicMock()
    svc.archive.get_active_subscriptions.return_value = [{"id": "s1", "filters": {}, "channels": [{"type": "all"}]}]
    svc.archive.find_active_outbound_event.return_value = rows[0] if rows else None
    svc.archive.get_outbound_events.return_value = rows
    return svc


def _told(price, state="delivered"):
    return {"lifecycle_state": state, "payload": {"event_payload": {"title": "Loft", "price": price}}}


@pytest.mark.unit
class TestPriceDrop:
    """Core review 2026-11-27 §4.5: a listing already told is told again only when its price falls."""

    def _run(self, rows, price):
        svc = _price_service(rows)
        with patch("modules.service.enqueue_entity") as enqueue:
            svc.process_event("entity.upserted", "real_estate", "e9", {"title": "Loft", "price": price})
        return enqueue

    def test_new_listing_is_queued(self):
        assert self._run([], 300000).call_count == 1

    def test_same_or_higher_price_is_not_told_again(self):
        assert self._run([_told(300000)], 300000).call_count == 0
        assert self._run([_told(300000)], 320000).call_count == 0

    def test_lower_price_is_told_with_the_previous_one(self):
        enqueue = self._run([_told(300000)], 280000)
        assert enqueue.call_count == 1
        assert enqueue.call_args.kwargs["payload"]["previous_price"] == 300000

    def test_compares_with_the_last_price_told(self):
        """After a drop to 280k, 290k is not news: the lowest live row is the last price told."""
        assert self._run([_told(300000), _told(280000)], 290000).call_count == 0

    def test_still_queued_batch_is_not_doubled(self):
        assert self._run([_told(300000, state="queued")], 250000).call_count == 0
