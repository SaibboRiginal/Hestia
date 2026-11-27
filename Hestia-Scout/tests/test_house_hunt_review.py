"""Regression tests of the house-hunt review (docs/work/2026-11-27-scout-house-hunt-review)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ── Immobiliare links survive the email cleaning ─────────────────────────────
def test_immobiliare_listing_links_are_kept():
    from worker.extractor import sanitize_email_for_ai
    html = ('<p><a href="https://www.immobiliare.it/annunci/123456/?utm_source=alert">Trilocale</a></p>'
            '<p><a href="https://www.immobiliare.it/ricerca/?x=1">Tutti</a></p>')
    text = sanitize_email_for_ai(html)
    assert "[PROPERTY_LINK: https://www.immobiliare.it/annunci/123456/?utm_source=alert]" in text
    assert "ricerca" not in text


def test_listing_link_behind_a_tracking_redirect():
    from worker.extractor import listing_link
    wrapped = "https://click.example.com/r?url=https%3A%2F%2Fwww.immobiliare.it%2Fannunci%2F99%2F"
    assert listing_link(wrapped) == "https://www.immobiliare.it/annunci/99/"
    assert listing_link("https://evil.example.com/immobiliare.it/annunci/1") == ""
    assert listing_link("https://www.idealista.it/immobile/42/") == "https://www.idealista.it/immobile/42/"


# ── a status word in one house of an alert does not touch the others ────────
def test_listing_segments_split_an_alert_by_house():
    from worker.pre_parser import listing_segments
    text = ("Trilocale [PROPERTY_LINK: https://www.idealista.it/immobile/1/]\n200.000 in trattativa\n"
            "Bilocale [PROPERTY_LINK: https://www.idealista.it/immobile/2/]\n150.000 luminoso\n")
    parts = listing_segments(text)
    assert "trattativa" in parts["https://www.idealista.it/immobile/1"]
    assert "trattativa" not in parts["https://www.idealista.it/immobile/2"]


# ── prices with thousands separators ─────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [("€ 250.000", 250000), ("250 000 €", 250000), (150000.0, 150000),
                                          ("1.250.000", 1250000), ("3", 3)])
def test_price_with_thousands_separator(raw, expected):
    from domain.house_entity import _to_int_or_none
    assert _to_int_or_none(raw) == expected


def test_pending_steps_are_kept_in_the_payload():
    from domain.house_entity import HouseEntity
    house = HouseEntity.from_extracted(entity_id="https://www.idealista.it/immobile/1/", domain="real_estate",
                                       payload={"pending_steps": {"listing_content_enrichment": True}})
    assert house.payload.model_dump()["pending_steps"] == {"listing_content_enrichment": True}


# ── the search tool really filters ───────────────────────────────────────────
def test_search_request_reads_the_filter_dicts():
    from tools.schemas import RealEstateSearchRequest
    req = RealEstateSearchRequest(filters={"city": "Torino"}, filters_lt={"price": 200000},
                                  filters_gt={"rooms": 3}, limit=100)
    assert (req.city, req.price_max, req.rooms_min, req.limit) == ("Torino", 200000, 3, 50)
    assert RealEstateSearchRequest(city="Asti", filters={"city": "Torino"}).city == "Asti"


def test_search_bounds_are_inclusive_and_city_filters(monkeypatch):
    from tools.retrieval import ScoutRetrievalService
    from tools.schemas import RealEstateSearchRequest

    sent = {}

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"status_code": 200, "payload": [{"url": "u1", "title": "A"},
                                                    {"url": "u2", "title": "B", "user_flag": "discarded"}]}

    def fake_post(url, json=None, timeout=None):
        sent.update(json["body"])
        return Resp()

    monkeypatch.setattr("tools.retrieval.requests.post", fake_post)

    class Geo:
        def geocode(self, q):
            return None

    svc = ScoutRetrievalService("", "real_estate", Geo(), hub_api_url="http://hub/api")
    items = svc.search(RealEstateSearchRequest(city="Torino", rooms_min=3, price_max=200000))
    assert sent["filters"] == {"city": "Torino"}
    assert sent["filters_gt"]["rooms"] < 3 and sent["filters_lt"]["price"] > 200000
    assert [i["url"] for i in items] == ["u1"]          # the discarded house stays out


# ── alert filters of Hermes see city / rooms / surface ───────────────────────
def test_event_carries_flat_fields_for_alert_filters():
    from worker.runner import match_fields
    fields = match_fields({"address": "Via Roma 3, 10100 Torino (TO)", "specs": {"rooms": 3, "surface_m2": 80}})
    assert fields["city"] == "Torino" and fields["rooms"] == 3 and fields["surface_m2"] == 80


# ── emails stay waiting when the model does not answer ───────────────────────
class _Vault:
    def __init__(self, records):
        self.records = records
        self.evaluations = {}

    def get_unevaluated(self, domain):
        return [r for r in self.records if r["id"] not in self.evaluations]

    def get_entity_map(self, domain, **kw):
        return {}

    def save_evaluation(self, record_id, evaluation):
        self.evaluations[record_id] = evaluation
        return True

    def upsert_entity(self, body):
        return True


def test_emails_are_not_marked_read_when_the_model_is_unavailable(monkeypatch):
    from worker import runner as runner_mod
    monkeypatch.setattr(runner_mod.scout_settings, "get_int",
                        lambda key, floor=None: {runner_mod.scout_settings.BATCH_MAX_SIZE: 5}.get(key, 0))
    worker = runner_mod.ScoutWorker.__new__(runner_mod.ScoutWorker)
    worker.target_domain = "real_estate"
    worker._cycle_counter = 0
    worker._llm_failures = {}
    body = '<a href="https://www.idealista.it/immobile/7/">Casa bella con giardino e box</a> 200.000 euro'
    worker.vault = _Vault([{"id": 1, "payload": {"body": body, "title": "Nuovi annunci"}}])

    class DownBrain:
        def evaluate(self, text):
            return {"raw_response": "", "error": "API Error: oracle 503"}

    worker.brain = DownBrain()
    worker.status_updater = None
    worker.run_cycle()
    assert worker.vault.evaluations == {}          # still waiting for the next cycle
