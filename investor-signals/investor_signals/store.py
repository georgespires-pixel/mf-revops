"""Local SQLite store for aggregated per-contact investor signals.

This is the only system of record for extracted signal — nothing is written back
to HubSpot. Live name/email/lifecycle are joined from HubSpot at read time (see
app.py), never duplicated here, since they go stale.

Aggregation rule (from the skill): merge new extraction results into the
existing contact row rather than replacing it wholesale. A contact who asked
about the Tech Fund in call 1 and confirmed a ticket size in call 3 should show
both.

Incremental sync: a ``sync_state`` table tracks the newest processed timestamp
per object type so each run only processes engagements newer than the last run.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS contact_signals (
    contact_id        TEXT PRIMARY KEY,
    contact_owner_id  TEXT,
    funds_mentioned   TEXT NOT NULL DEFAULT '[]',   -- JSON array of canonical names
    asset_classes     TEXT NOT NULL DEFAULT '[]',   -- JSON array (buyout, VC, ...)
    gics_sectors      TEXT NOT NULL DEFAULT '[]',   -- JSON array (GICS sectors)
    geographies       TEXT NOT NULL DEFAULT '[]',   -- JSON array
    currencies        TEXT NOT NULL DEFAULT '[]',   -- JSON array
    fund_size_hint    TEXT,                          -- most recent non-null
    cap_size          TEXT,                          -- buyout cap bucket
    sentiment_latest  TEXT,
    pain_points       TEXT NOT NULL DEFAULT '[]',   -- JSON array (most recent 3-5)
    ticket_size_hint  TEXT,
    evidence          TEXT NOT NULL DEFAULT '[]',   -- JSON array of {call_id, call_date, quote}
    unmatched_funds   TEXT NOT NULL DEFAULT '[]',   -- JSON array of raw strings flagged for review
    last_signal_date  TEXT,
    last_synced_at    TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
    object_type    TEXT PRIMARY KEY,
    last_ts_ms     INTEGER NOT NULL,
    updated_at     TEXT NOT NULL
);

-- Per-engagement audit log so a rep can trace every processed record.
CREATE TABLE IF NOT EXISTS processed_engagements (
    engagement_key TEXT PRIMARY KEY,   -- "<object_type>:<id>"
    contact_id     TEXT,
    call_owner_id  TEXT,
    processed_at   TEXT NOT NULL
);

-- Local contact directory. In production, name/email/lifecycle are joined LIVE
-- from HubSpot at render time and never persisted (they go stale). This table
-- exists only to make the MVP demoable with synthetic data when HubSpot is not
-- connected; app.py prefers a live HubSpot join and falls back to this.
CREATE TABLE IF NOT EXISTS contact_directory (
    contact_id      TEXT PRIMARY KEY,
    name            TEXT,
    email           TEXT,
    lifecycle_stage TEXT,
    owner_id        TEXT
);

-- Owner directory, same rationale (offline fallback for the rep filter).
CREATE TABLE IF NOT EXISTS owners (
    owner_id TEXT PRIMARY KEY,
    name     TEXT,
    email    TEXT
);
"""

MAX_PAIN_POINTS = 5
MAX_EVIDENCE = 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        k = it.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


class Store:
    def __init__(self, path: str):
        self._path = path
        # check_same_thread=False lets the FastAPI threadpool reuse this
        # connection; a lock serializes access so concurrent handlers are safe.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        """Add newer dimension columns to a pre-existing contact_signals table.

        SQLite has no ADD COLUMN IF NOT EXISTS, so check pragma table_info first.
        """
        existing = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(contact_signals)")
        }
        additions = {
            "asset_classes": "TEXT NOT NULL DEFAULT '[]'",
            "gics_sectors": "TEXT NOT NULL DEFAULT '[]'",
            "geographies": "TEXT NOT NULL DEFAULT '[]'",
            "currencies": "TEXT NOT NULL DEFAULT '[]'",
            "fund_size_hint": "TEXT",
            "cap_size": "TEXT",
        }
        for col, decl in additions.items():
            if col not in existing:
                self._conn.execute(
                    f"ALTER TABLE contact_signals ADD COLUMN {col} {decl}"
                )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    # -- incremental sync state -------------------------------------------

    def get_last_ts(self, object_type: str) -> int | None:
        with self._read() as c:
            row = c.execute(
                "SELECT last_ts_ms FROM sync_state WHERE object_type = ?",
                (object_type,),
            ).fetchone()
        return int(row["last_ts_ms"]) if row else None

    def set_last_ts(self, object_type: str, ts_ms: int) -> None:
        with self._tx() as c:
            c.execute(
                """
                INSERT INTO sync_state (object_type, last_ts_ms, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(object_type) DO UPDATE SET
                    last_ts_ms = excluded.last_ts_ms,
                    updated_at = excluded.updated_at
                """,
                (object_type, ts_ms, _now_iso()),
            )

    def is_processed(self, object_type: str, object_id: str) -> bool:
        key = f"{object_type}:{object_id}"
        with self._read() as c:
            row = c.execute(
                "SELECT 1 FROM processed_engagements WHERE engagement_key = ?", (key,)
            ).fetchone()
        return row is not None

    def mark_processed(
        self, object_type: str, object_id: str, contact_id: str, call_owner_id: str | None
    ) -> None:
        key = f"{object_type}:{object_id}"
        with self._tx() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO processed_engagements
                    (engagement_key, contact_id, call_owner_id, processed_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, contact_id, call_owner_id, _now_iso()),
            )

    # -- aggregation -------------------------------------------------------

    def upsert_signal(
        self,
        *,
        contact_id: str,
        contact_owner_id: str | None,
        normalized_funds: list[dict],
        extraction: dict[str, Any],
    ) -> None:
        """Merge one extraction result into the contact's aggregated row.

        ``normalized_funds`` entries carry ``name``/``unmatched``. Matched fund
        names accumulate in ``funds_mentioned``; unmatched raw strings accumulate
        in ``unmatched_funds`` for later review.
        """
        call_date = extraction.get("call_date") or ""
        matched = [f["name"] for f in normalized_funds if not f["unmatched"]]
        unmatched = [f["raw"] for f in normalized_funds if f["unmatched"]]

        with self._tx() as c:
            row = c.execute(
                "SELECT * FROM contact_signals WHERE contact_id = ?", (contact_id,)
            ).fetchone()

            def _existing_list(col: str) -> list[str]:
                return json.loads(row[col]) if row else []

            # Asset classes: accept the new field, fall back to the legacy name.
            new_asset_classes = list(
                extraction.get("asset_classes")
                or extraction.get("industry_or_asset_class")
                or []
            )
            funds = _dedupe_keep_order(_existing_list("funds_mentioned") + matched)
            asset_classes = _dedupe_keep_order(
                _existing_list("asset_classes") + new_asset_classes
            )
            gics = _dedupe_keep_order(
                _existing_list("gics_sectors") + list(extraction.get("gics_sectors", []))
            )
            geos = _dedupe_keep_order(
                _existing_list("geographies") + list(extraction.get("geographies", []))
            )
            currency_val = extraction.get("currency")
            currencies = _dedupe_keep_order(
                _existing_list("currencies") + ([currency_val] if currency_val else [])
            )
            unmatched_all = _dedupe_keep_order(
                _existing_list("unmatched_funds") + unmatched
            )

            existing_pains = _existing_list("pain_points")
            pain_points = _dedupe_keep_order(
                list(extraction.get("pain_points", [])) + existing_pains
            )[:MAX_PAIN_POINTS]

            # Evidence: append, sort by date desc, keep most recent 1-2.
            evidence = json.loads(row["evidence"]) if row else []
            quote = extraction.get("evidence_quote") or ""
            if quote:
                evidence = evidence + [
                    {
                        "call_id": extraction.get("call_id"),
                        "call_date": call_date,
                        "quote": quote,
                    }
                ]
            evidence.sort(key=lambda e: e.get("call_date") or "", reverse=True)
            evidence = evidence[:MAX_EVIDENCE]

            # "Most recent" scalar fields only update if this call is >= newest.
            prev_date = (row["last_signal_date"] if row else "") or ""
            is_newer = call_date >= prev_date
            sentiment_latest = row["sentiment_latest"] if row else None
            ticket = row["ticket_size_hint"] if row else None
            fund_size = row["fund_size_hint"] if row else None
            cap_size = row["cap_size"] if row else None
            if is_newer and extraction.get("sentiment"):
                sentiment_latest = extraction["sentiment"]
            for field_name, current, key_in in (
                ("ticket", ticket, "ticket_size_hint"),
                ("fund_size", fund_size, "fund_size_hint"),
                ("cap_size", cap_size, "cap_size"),
            ):
                new_val = extraction.get(key_in)
                if new_val and (is_newer or not current):
                    if field_name == "ticket":
                        ticket = new_val
                    elif field_name == "fund_size":
                        fund_size = new_val
                    else:
                        cap_size = new_val

            last_signal_date = max(prev_date, call_date)

            c.execute(
                """
                INSERT INTO contact_signals (
                    contact_id, contact_owner_id, funds_mentioned, asset_classes,
                    gics_sectors, geographies, currencies, fund_size_hint, cap_size,
                    sentiment_latest, pain_points, ticket_size_hint, evidence,
                    unmatched_funds, last_signal_date, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(contact_id) DO UPDATE SET
                    contact_owner_id = excluded.contact_owner_id,
                    funds_mentioned  = excluded.funds_mentioned,
                    asset_classes    = excluded.asset_classes,
                    gics_sectors     = excluded.gics_sectors,
                    geographies      = excluded.geographies,
                    currencies       = excluded.currencies,
                    fund_size_hint   = excluded.fund_size_hint,
                    cap_size         = excluded.cap_size,
                    sentiment_latest = excluded.sentiment_latest,
                    pain_points      = excluded.pain_points,
                    ticket_size_hint = excluded.ticket_size_hint,
                    evidence         = excluded.evidence,
                    unmatched_funds  = excluded.unmatched_funds,
                    last_signal_date = excluded.last_signal_date,
                    last_synced_at   = excluded.last_synced_at
                """,
                (
                    contact_id,
                    contact_owner_id or (row["contact_owner_id"] if row else None),
                    json.dumps(funds),
                    json.dumps(asset_classes),
                    json.dumps(gics),
                    json.dumps(geos),
                    json.dumps(currencies),
                    fund_size,
                    cap_size,
                    sentiment_latest,
                    json.dumps(pain_points),
                    ticket,
                    json.dumps(evidence),
                    json.dumps(unmatched_all),
                    last_signal_date,
                    _now_iso(),
                ),
            )

    # -- queries -----------------------------------------------------------

    @staticmethod
    def _jget(row: sqlite3.Row, col: str) -> list[str]:
        keys = row.keys()
        return json.loads(row[col]) if col in keys and row[col] else []

    @classmethod
    def _row_to_dict(cls, row: sqlite3.Row) -> dict[str, Any]:
        keys = row.keys()
        return {
            "contact_id": row["contact_id"],
            "contact_owner_id": row["contact_owner_id"],
            "funds_mentioned": cls._jget(row, "funds_mentioned"),
            "asset_classes": cls._jget(row, "asset_classes"),
            "gics_sectors": cls._jget(row, "gics_sectors"),
            "geographies": cls._jget(row, "geographies"),
            "currencies": cls._jget(row, "currencies"),
            "fund_size_hint": row["fund_size_hint"] if "fund_size_hint" in keys else None,
            "cap_size": row["cap_size"] if "cap_size" in keys else None,
            "sentiment_latest": row["sentiment_latest"],
            "pain_points": cls._jget(row, "pain_points"),
            "ticket_size_hint": row["ticket_size_hint"],
            "evidence": cls._jget(row, "evidence"),
            "unmatched_funds": cls._jget(row, "unmatched_funds"),
            "last_signal_date": row["last_signal_date"],
            "last_synced_at": row["last_synced_at"],
        }

    def query_contacts(
        self,
        *,
        fund: str | None = None,
        asset_class: str | None = None,
        sector: str | None = None,
        geography: str | None = None,
        currency: str | None = None,
        cap_size: str | None = None,
        sentiment: str | None = None,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query aggregated signals. JSON-array membership filters are applied in
        Python (SQLite JSON1 exact-membership filtering is brittle)."""
        clauses: list[str] = []
        params: list[Any] = []
        if sentiment:
            clauses.append("sentiment_latest = ?")
            params.append(sentiment)
        if owner_id:
            clauses.append("contact_owner_id = ?")
            params.append(owner_id)
        if cap_size:
            clauses.append("cap_size = ?")
            params.append(cap_size)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM contact_signals {where} ORDER BY last_signal_date DESC"
        with self._read() as c:
            rows = [self._row_to_dict(r) for r in c.execute(sql, params)]

        def _has(row: dict, key: str, value: str) -> bool:
            return value in row.get(key, [])

        if fund:
            rows = [r for r in rows if _has(r, "funds_mentioned", fund)]
        if asset_class:
            rows = [r for r in rows if _has(r, "asset_classes", asset_class)]
        if sector:
            rows = [r for r in rows if _has(r, "gics_sectors", sector)]
        if geography:
            rows = [r for r in rows if _has(r, "geographies", geography)]
        if currency:
            rows = [r for r in rows if _has(r, "currencies", currency)]
        return rows

    def asset_class_interest(self) -> list[dict[str, Any]]:
        """% of contacts that expressed interest in each asset class."""
        rows = self.all_signals()
        total = len(rows) or 1
        counts: dict[str, dict[str, int]] = {}
        for r in rows:
            positive = r.get("sentiment_latest") == "positive"
            for ac in r.get("asset_classes", []):
                d = counts.setdefault(ac, {"contacts": 0, "positive": 0})
                d["contacts"] += 1
                if positive:
                    d["positive"] += 1
        out = [
            {
                "asset_class": ac,
                "contacts": d["contacts"],
                "positive": d["positive"],
                "pct": round(100 * d["contacts"] / total),
            }
            for ac, d in counts.items()
        ]
        out.sort(key=lambda x: x["contacts"], reverse=True)
        return out

    def overview(self) -> dict[str, Any]:
        """Aggregates for the Overview dashboard."""
        rows = self.all_signals()
        n = len(rows)

        def count_field(list_key: str) -> list[dict[str, Any]]:
            counts: dict[str, int] = {}
            for r in rows:
                for v in r.get(list_key, []):
                    counts[v] = counts.get(v, 0) + 1
            return sorted(
                ({"label": k, "count": v} for k, v in counts.items()),
                key=lambda x: x["count"],
                reverse=True,
            )

        sentiment: dict[str, int] = {}
        with_signal = 0
        for r in rows:
            s = r.get("sentiment_latest") or "unknown"
            sentiment[s] = sentiment.get(s, 0) + 1
            if r.get("funds_mentioned") or r.get("asset_classes"):
                with_signal += 1

        positive = sentiment.get("positive", 0)
        return {
            "totals": {
                "contacts": n,
                "with_signal": with_signal,
                "positive": positive,
                "positive_pct": round(100 * positive / n) if n else 0,
                "funds": len(count_field("funds_mentioned")),
            },
            "sentiment": [
                {"label": k, "count": v}
                for k, v in sorted(sentiment.items(), key=lambda x: x[1], reverse=True)
            ],
            "asset_class_interest": self.asset_class_interest(),
            "geographies": count_field("geographies"),
            "gics_sectors": count_field("gics_sectors"),
            "currencies": count_field("currencies"),
            "funds": count_field("funds_mentioned"),
        }

    def all_signals(self) -> list[dict[str, Any]]:
        with self._read() as c:
            return [
                self._row_to_dict(r)
                for r in c.execute(
                    "SELECT * FROM contact_signals ORDER BY last_signal_date DESC"
                )
            ]

    # -- local directory (offline fallback for name/email/rep) -------------

    def upsert_contact_directory(
        self,
        contact_id: str,
        *,
        name: str | None,
        email: str | None,
        lifecycle_stage: str | None,
        owner_id: str | None,
    ) -> None:
        with self._tx() as c:
            c.execute(
                """
                INSERT INTO contact_directory
                    (contact_id, name, email, lifecycle_stage, owner_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(contact_id) DO UPDATE SET
                    name = excluded.name, email = excluded.email,
                    lifecycle_stage = excluded.lifecycle_stage,
                    owner_id = excluded.owner_id
                """,
                (contact_id, name, email, lifecycle_stage, owner_id),
            )

    def get_contact_directory(self, contact_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not contact_ids:
            return {}
        placeholders = ",".join("?" for _ in contact_ids)
        with self._read() as c:
            rows = c.execute(
                f"SELECT * FROM contact_directory WHERE contact_id IN ({placeholders})",
                contact_ids,
            ).fetchall()
        return {r["contact_id"]: dict(r) for r in rows}

    def upsert_owner(self, owner_id: str, name: str | None, email: str | None) -> None:
        with self._tx() as c:
            c.execute(
                """
                INSERT INTO owners (owner_id, name, email) VALUES (?, ?, ?)
                ON CONFLICT(owner_id) DO UPDATE SET
                    name = excluded.name, email = excluded.email
                """,
                (owner_id, name, email),
            )

    def list_owners(self) -> list[dict[str, Any]]:
        with self._read() as c:
            rows = c.execute("SELECT * FROM owners ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._read() as c:
            total = c.execute(
                "SELECT COUNT(*) AS n FROM contact_signals"
            ).fetchone()["n"]
            processed = c.execute(
                "SELECT COUNT(*) AS n FROM processed_engagements"
            ).fetchone()["n"]
        return {"contacts": total, "processed_engagements": processed}
