"""Offline tests for the pure-logic modules (no HubSpot / Claude API needed).

Run with:  python -m pytest   (or) python tests/test_core.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from investor_signals.normalize import normalize_funds  # noqa: E402
from investor_signals.store import Store  # noqa: E402


def test_fuzzy_fund_matching():
    res = normalize_funds(
        ["Moon for Tech Fund", "Moonfair Tech Fund", "Some Random Fund"], threshold=82
    )
    matched = [r for r in res if not r["unmatched"]]
    unmatched = [r for r in res if r["unmatched"]]
    # Both tech-fund variants canonicalize to one fund and dedupe.
    assert len(matched) == 1
    assert matched[0]["name"] == "Moonfare Technology Fund"
    # Unknown funds are kept and flagged, never dropped or force-matched.
    assert len(unmatched) == 1
    assert unmatched[0]["raw"] == "Some Random Fund"


def _upsert(store, contact_id, call_id, date, funds, sentiment, ticket, quote, industries):
    store.upsert_signal(
        contact_id=contact_id,
        contact_owner_id="rep1",
        normalized_funds=[
            {"name": f, "raw": f, "fund_key": f, "score": 95, "unmatched": False}
            for f in funds
        ],
        extraction={
            "call_id": call_id,
            "call_date": date,
            "industry_or_asset_class": industries,
            "sentiment": sentiment,
            "pain_points": [],
            "ticket_size_hint": ticket,
            "evidence_quote": quote,
        },
    )


def test_aggregation_merges_not_overwrites():
    db = tempfile.mktemp(suffix=".db")
    store = Store(db)
    try:
        _upsert(store, "c1", "e1", "2026-06-05T10:00:00+00:00",
                ["Moonfare Technology Fund"], "positive", None, "keen on tech", ["technology"])
        _upsert(store, "c1", "e3", "2026-06-20T10:00:00+00:00",
                ["Moonfare Buyout Fund III"], "neutral", "$500k", "commit 500k", ["buyout"])

        row = store.query_contacts(fund="Moonfare Technology Fund")[0]
        # funds accumulate across calls
        assert set(row["funds_mentioned"]) == {
            "Moonfare Technology Fund",
            "Moonfare Buyout Fund III",
        }
        # "most recent" fields come from the newest call
        assert row["sentiment_latest"] == "neutral"
        assert row["ticket_size_hint"] == "$500k"
        assert row["last_signal_date"].startswith("2026-06-20")
        assert len(row["evidence"]) == 2
    finally:
        store.close()
        os.remove(db)


def test_filters_and_incremental_state():
    db = tempfile.mktemp(suffix=".db")
    store = Store(db)
    try:
        _upsert(store, "c1", "e1", "2026-06-05T10:00:00+00:00",
                ["Moonfare Technology Fund"], "positive", None, "q", ["technology"])
        assert len(store.query_contacts(sentiment="positive", owner_id="rep1")) == 1
        assert len(store.query_contacts(sentiment="negative")) == 0
        assert len(store.query_contacts(industry="tech")) == 1

        store.mark_processed("calls", "e1", "c1", "call_owner")
        assert store.is_processed("calls", "e1") is True
        assert store.is_processed("calls", "nope") is False
        store.set_last_ts("calls", 123456)
        assert store.get_last_ts("calls") == 123456
    finally:
        store.close()
        os.remove(db)


def test_synthetic_generation_is_deterministic_and_excludes_servicing():
    from investor_signals.synthetic import generate

    engs1, contacts1 = generate(12, seed=42)
    engs2, _ = generate(12, seed=42)
    # Deterministic for a fixed seed.
    assert [e.call_id for e in engs1] == [e.call_id for e in engs2]
    assert len(contacts1) == 12
    # Servicing engagements exist and carry no buy signal.
    servicing = [e for e in engs1 if not e.truth["funds_mentioned"] and e.title != ""]
    assert any(
        e.truth["sentiment"] == "neutral" and not e.truth["funds_mentioned"]
        for e in servicing
    )
    # Messy fund variants are present (so normalization has real work).
    all_funds = [f for e in engs1 for f in e.truth["funds_mentioned"]]
    assert any(f not in {  # at least one non-canonical variant
        "Moonfare Technology Fund", "Moonfare Buyout Fund III",
        "Moonfare Infrastructure Fund", "Moonfare Private Credit Fund",
        "Moonfare Secondaries Fund II",
    } for f in all_funds)


def test_seed_store_offline_populates_directory_and_signals():
    from investor_signals.config import Config, SyncScope
    from investor_signals.seed import seed_store

    db = tempfile.mktemp(suffix=".db")
    cfg = Config(scope=SyncScope(), store_path=db)
    try:
        report = seed_store(cfg, n_contacts=12, use_llm=False, seed=42)
        assert report.signals_written > 0
        assert report.servicing_skipped > 0  # servicing produced no signal

        store = Store(db)
        try:
            rows = store.query_contacts()
            assert rows, "expected seeded signals"
            # Directory lookup works (names available offline).
            directory = store.get_contact_directory([r["contact_id"] for r in rows])
            assert any(d.get("name") for d in directory.values())
            assert len(store.list_owners()) == 3
            # Normalization resolved messy variants to canonical names.
            for r in rows:
                for f in r["funds_mentioned"]:
                    assert f.startswith("Moonfare ")
        finally:
            store.close()
    finally:
        os.remove(db)


if __name__ == "__main__":
    test_fuzzy_fund_matching()
    test_aggregation_merges_not_overwrites()
    test_filters_and_incremental_state()
    test_synthetic_generation_is_deterministic_and_excludes_servicing()
    test_seed_store_offline_populates_directory_and_signals()
    print("ALL TESTS PASSED")
