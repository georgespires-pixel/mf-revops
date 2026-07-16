#!/usr/bin/env python3
"""Validate the signal store and (re)generate the query app's data bundle.

Reads:
  investor-signals/store/signals.jsonl   (canonical, append-only store)
  investor-signals/store/schema.json     (record schema — lightweight validation)
  investor-signals/funds.json            (canonical funds + competitors)
  investor-signals/taxonomy.json         (controlled vocab)

Writes:
  investor-signals/app/data.js           (window.__STORE__ = {...} for index.html)

Validation is intentionally lightweight (stdlib only, no jsonschema dep): it
checks required fields, enum membership, dedup keys, and taxonomy conformance,
and prints a summary. Exits non-zero on hard errors (dupes, missing required
fields, bad enums) so it can gate a commit or a scheduled run.

Usage:
    python3 build_store.py            # validate + rebuild app/data.js
    python3 build_store.py --check    # validate only, do not write data.js
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SIGNALS = os.path.join(ROOT, "store", "signals.jsonl")
SCHEMA = os.path.join(ROOT, "store", "schema.json")
FUNDS = os.path.join(ROOT, "funds.json")
TAXONOMY = os.path.join(ROOT, "taxonomy.json")
DATA_JS = os.path.join(ROOT, "app", "data.js")

REQUIRED = [
    "signal_id", "engagement_id", "engagement_type", "timestamp",
    "interest_level", "sentiment", "asset_classes", "funds", "summary",
    "extracted_at",
]


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_signals(path: str) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit(f"[FATAL] {path}:{i} invalid JSON: {e}")
    return rows


def validate(signals: list[dict], schema: dict, taxonomy: dict) -> list[str]:
    errors: list[str] = []
    enums = {
        "engagement_type": set(taxonomy["engagement_types"]),
        "sentiment": set(taxonomy["sentiment"]),
        "interest_level": set(taxonomy["interest_level"].keys()),
        "urgency": set(taxonomy["urgency"].keys()),
    }
    asset_vocab = set(taxonomy["asset_classes"])
    seen_signal_ids: set[str] = set()
    seen_engagements: set[tuple] = set()

    for s in signals:
        sid = s.get("signal_id", "<no id>")
        for field in REQUIRED:
            if field not in s or s[field] in (None, ""):
                errors.append(f"{sid}: missing required field '{field}'")

        if sid in seen_signal_ids:
            errors.append(f"{sid}: duplicate signal_id")
        seen_signal_ids.add(sid)

        key = (s.get("engagement_type"), s.get("engagement_id"))
        if key in seen_engagements:
            errors.append(f"{sid}: duplicate engagement {key}")
        seen_engagements.add(key)

        for field, allowed in enums.items():
            val = s.get(field)
            if val is not None and val not in allowed:
                errors.append(f"{sid}: {field}={val!r} not in {sorted(allowed)}")

        for ac in s.get("asset_classes", []):
            if ac not in asset_vocab:
                errors.append(f"{sid}: asset_class {ac!r} not in taxonomy")

        # signal_id convention
        expected = f"sig_{s.get('engagement_type')}_{s.get('engagement_id')}"
        if sid != expected:
            errors.append(f"{sid}: expected signal_id {expected!r}")

    return errors


def summarize(signals: list[dict]) -> None:
    from collections import Counter
    investor = [s for s in signals if s.get("interest_level") != "not_investor"]
    by_level = Counter(s["interest_level"] for s in signals)
    by_fund: Counter = Counter()
    unmatched = 0
    for s in investor:
        for f in s.get("funds", []):
            if f.get("match") == "unmatched":
                unmatched += 1
            else:
                by_fund[f.get("canonical")] += 1
    print(f"  signals total          : {len(signals)}")
    print(f"  investor-interest       : {len(investor)}")
    print(f"  by interest_level       : {dict(by_level)}")
    print(f"  top funds by mentions   : {by_fund.most_common(6)}")
    print(f"  unmatched fund mentions : {unmatched}")


def write_data_js(signals, funds_doc, taxonomy) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signal_count": len(signals),
        "signals": signals,
        "funds": funds_doc.get("funds", []),
        "competitors": funds_doc.get("competitors", []),
        "taxonomy": taxonomy,
    }
    os.makedirs(os.path.dirname(DATA_JS), exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    with open(DATA_JS, "w", encoding="utf-8") as fh:
        fh.write("// AUTO-GENERATED by scripts/build_store.py — do not edit by hand.\n")
        fh.write("// Regenerate after editing store/signals.jsonl or funds.json.\n")
        fh.write("window.__STORE__ = ")
        fh.write(body)
        fh.write(";\n")
    print(f"  wrote {os.path.relpath(DATA_JS, ROOT)} ({len(signals)} signals)")


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    signals = _load_signals(SIGNALS)
    schema = _load_json(SCHEMA)
    funds_doc = _load_json(FUNDS)
    taxonomy = _load_json(TAXONOMY)

    print("Validating store...")
    errors = validate(signals, schema, taxonomy)
    if errors:
        print(f"\n[FAIL] {len(errors)} validation error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("  OK — no validation errors")
    summarize(signals)

    if not check_only:
        print("\nBuilding app data bundle...")
        write_data_js(signals, funds_doc, taxonomy)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
