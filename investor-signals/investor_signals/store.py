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
    industries        TEXT NOT NULL DEFAULT '[]',   -- JSON array
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
            self._conn.commit()

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

            if row is None:
                existing = {
                    "funds": [],
                    "industries": [],
                    "pain_points": [],
                    "evidence": [],
                    "unmatched": [],
                    "sentiment_latest": None,
                    "ticket_size_hint": None,
                    "last_signal_date": "",
                }
            else:
                existing = {
                    "funds": json.loads(row["funds_mentioned"]),
                    "industries": json.loads(row["industries"]),
                    "pain_points": json.loads(row["pain_points"]),
                    "evidence": json.loads(row["evidence"]),
                    "unmatched": json.loads(row["unmatched_funds"]),
                    "sentiment_latest": row["sentiment_latest"],
                    "ticket_size_hint": row["ticket_size_hint"],
                    "last_signal_date": row["last_signal_date"] or "",
                }

            funds = _dedupe_keep_order(existing["funds"] + matched)
            industries = _dedupe_keep_order(
                existing["industries"] + list(extraction.get("industry_or_asset_class", []))
            )
            unmatched_all = _dedupe_keep_order(existing["unmatched"] + unmatched)

            # Pain points: most recent first, keep 3-5.
            new_pains = list(extraction.get("pain_points", []))
            pain_points = _dedupe_keep_order(new_pains + existing["pain_points"])[
                :MAX_PAIN_POINTS
            ]

            # Evidence: append, sort by date desc, keep most recent 1-2.
            evidence = existing["evidence"]
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

            # "Most recent" fields only update if this call is at least as new.
            is_newer = call_date >= (existing["last_signal_date"] or "")
            sentiment_latest = existing["sentiment_latest"]
            ticket = existing["ticket_size_hint"]
            if is_newer:
                if extraction.get("sentiment"):
                    sentiment_latest = extraction["sentiment"]
            new_ticket = extraction.get("ticket_size_hint")
            if new_ticket and (is_newer or not ticket):
                ticket = new_ticket

            last_signal_date = max(existing["last_signal_date"] or "", call_date)

            c.execute(
                """
                INSERT INTO contact_signals (
                    contact_id, contact_owner_id, funds_mentioned, industries,
                    sentiment_latest, pain_points, ticket_size_hint, evidence,
                    unmatched_funds, last_signal_date, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(contact_id) DO UPDATE SET
                    contact_owner_id = excluded.contact_owner_id,
                    funds_mentioned  = excluded.funds_mentioned,
                    industries       = excluded.industries,
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
                    json.dumps(industries),
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
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "contact_id": row["contact_id"],
            "contact_owner_id": row["contact_owner_id"],
            "funds_mentioned": json.loads(row["funds_mentioned"]),
            "industries": json.loads(row["industries"]),
            "sentiment_latest": row["sentiment_latest"],
            "pain_points": json.loads(row["pain_points"]),
            "ticket_size_hint": row["ticket_size_hint"],
            "evidence": json.loads(row["evidence"]),
            "unmatched_funds": json.loads(row["unmatched_funds"]),
            "last_signal_date": row["last_signal_date"],
            "last_synced_at": row["last_synced_at"],
        }

    def query_contacts(
        self,
        *,
        fund: str | None = None,
        industry: str | None = None,
        sentiment: str | None = None,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query aggregated signals. JSON-array filters are applied in Python
        (SQLite JSON1 substring filtering is brittle for exact membership)."""
        clauses: list[str] = []
        params: list[Any] = []
        if sentiment:
            clauses.append("sentiment_latest = ?")
            params.append(sentiment)
        if owner_id:
            clauses.append("contact_owner_id = ?")
            params.append(owner_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT * FROM contact_signals {where} ORDER BY last_signal_date DESC"
        )
        with self._read() as c:
            rows = [self._row_to_dict(r) for r in c.execute(sql, params)]

        if fund:
            rows = [r for r in rows if fund in r["funds_mentioned"]]
        if industry:
            rows = [
                r
                for r in rows
                if any(industry.lower() in i.lower() for i in r["industries"])
            ]
        return rows

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
