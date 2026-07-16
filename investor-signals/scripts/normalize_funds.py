#!/usr/bin/env python3
"""Deterministic fund-name normalization for investor-signal extraction.

Maps a raw fund mention (as it appears in a HubSpot call summary / email) to a
canonical fund in ``funds.json``. Used by the extraction skill so normalization
is reproducible rather than eyeballed, and by the test suite.

Matching order (first hit wins):
  1. exact   — normalized raw == normalized canonical name
  2. alias   — normalized raw == a normalized alias (incl. brand fixups)
  3. fuzzy   — token-overlap / containment above threshold
  4. unmatched

Brand fixups: HubSpot's AI summaries mis-transcribe "Moonfare" as "Moonfair",
"Moonsphere", etc. These are rewritten before matching (see ``_brand_aliases``).

No third-party dependencies (stdlib only).

Usage:
    python3 normalize_funds.py "Moonfair Tech Fund" "EQT" "Horovich fund"
    echo "CVC" | python3 normalize_funds.py -
    python3 normalize_funds.py --test
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FUNDS_PATH = os.path.join(HERE, "..", "funds.json")

FUZZY_THRESHOLD = 0.5
_WORD_RE = re.compile(r"[a-z0-9]+")


def _load_funds(path: str = FUNDS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _brand_fixup(text: str, brand_aliases: dict) -> str:
    out = text
    for canonical, variants in brand_aliases.items():
        for variant in variants:
            out = re.sub(re.escape(variant), canonical, out, flags=re.IGNORECASE)
    return out


def _norm(text: str) -> str:
    """Lowercase, drop parentheticals/quotes/punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"\(.*?\)", " ", text)        # drop parenthetical qualifiers
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)     # drop quotes/punctuation
    text = re.sub(r"\b(the|fund|funds|capital|partners)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> set:
    return set(_WORD_RE.findall(text))


def _token_score(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    # Jaccard-ish, but reward full containment of the shorter side.
    return max(inter / len(ta | tb), inter / min(len(ta), len(tb)) * 0.9)


class FundNormalizer:
    def __init__(self, funds_doc: dict | None = None):
        self.doc = funds_doc or _load_funds()
        self.brand_aliases = self.doc.get("_brand_aliases", {})
        self.brand_aliases = {
            k: v for k, v in self.brand_aliases.items() if not k.startswith("_")
        }
        self.funds = self.doc.get("funds", [])
        self.competitors = self.doc.get("competitors", [])

        # Precompute normalized name/alias index.
        self._alias_index: dict[str, dict] = {}
        self._name_index: dict[str, dict] = {}
        for f in self.funds:
            self._name_index[self._prep(f["name"])] = f
            for alias in [f["name"], f.get("short_name", "")] + f.get("aliases", []):
                if alias:
                    self._alias_index.setdefault(self._prep(alias), f)

        self._competitor_index: dict[str, dict] = {}
        for c in self.competitors:
            for alias in [c["name"]] + c.get("aliases", []):
                self._competitor_index.setdefault(self._prep(alias), c)

    def _prep(self, text: str) -> str:
        return _norm(_brand_fixup(text, self.brand_aliases))

    def match(self, raw: str) -> dict:
        prepped = self._prep(raw)
        result = {
            "raw": raw,
            "canonical": None,
            "fund_id": None,
            "asset_class": None,
            "match": "unmatched",
            "confidence": 0.0,
        }
        if not prepped:
            return result

        # 1. exact name
        f = self._name_index.get(prepped)
        if f:
            return self._hit(result, f, "exact", 1.0)

        # 2. alias
        f = self._alias_index.get(prepped)
        if f:
            return self._hit(result, f, "alias", 0.95)

        # 3. fuzzy over names + aliases
        best, best_score = None, 0.0
        for f in self.funds:
            candidates = [f["name"], f.get("short_name", "")] + f.get("aliases", [])
            for cand in candidates:
                if not cand:
                    continue
                score = _token_score(prepped, self._prep(cand))
                if score > best_score:
                    best, best_score = f, score
        if best and best_score >= FUZZY_THRESHOLD:
            return self._hit(result, best, "fuzzy", round(min(best_score, 0.9), 2))

        return result

    def competitor(self, raw: str) -> dict | None:
        prepped = self._prep(raw)
        c = self._competitor_index.get(prepped)
        if c:
            return {"competitor_id": c["competitor_id"], "name": c["name"]}
        for c in self.competitors:
            for alias in [c["name"]] + c.get("aliases", []):
                if _token_score(prepped, self._prep(alias)) >= 0.8:
                    return {"competitor_id": c["competitor_id"], "name": c["name"]}
        return None

    @staticmethod
    def _hit(result: dict, fund: dict, kind: str, conf: float) -> dict:
        result.update(
            canonical=fund["name"],
            fund_id=fund["fund_id"],
            asset_class=fund.get("asset_class"),
            match=kind,
            confidence=conf,
        )
        return result


def _selftest() -> int:
    n = FundNormalizer()
    cases = [
        ("Moonfair Tech Fund", "moonfare_tech_fund", "alias"),
        ("Moonsphere Secondary Fund", "moonfare_secondary_fund", "alias"),
        ("Moonfare Tech Fund", "moonfare_tech_fund", "exact"),
        ("MTF", "moonfare_tech_fund", "alias"),
        ("EQT", "eqt_xi", "alias"),
        ("EQT XI (US)", "eqt_xi", "alias"),
        ("Bonaccord", "bonacord_iii", "alias"),
        ("BCP III", "bonacord_iii", "alias"),
        ("General Catalyst", "general_catalyst_xiii", "alias"),
        ("Databricks", "databricks", "exact"),
        ("Mid-Market Fund", "moonfare_mid_market", "alias"),
    ]
    ok = True
    for raw, want_id, want_kind in cases:
        got = n.match(raw)
        status = "ok" if got["fund_id"] == want_id else "FAIL"
        if got["fund_id"] != want_id:
            ok = False
        print(f"[{status}] {raw!r:34} -> {got['fund_id']} ({got['match']}, {got['confidence']})")

    # Unmatched + competitor checks
    unmatched = n.match("Horovich fund")
    print(f"[{'ok' if unmatched['match'] == 'unmatched' else 'FAIL'}] "
          f"'Horovich fund' -> unmatched")
    ok = ok and unmatched["match"] == "unmatched"
    comp = n.competitor("Hamilton Lane")
    print(f"[{'ok' if comp else 'FAIL'}] 'Hamilton Lane' -> competitor {comp}")
    ok = ok and comp is not None
    print("\nALL PASS" if ok else "\nSOME FAILED")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    if argv[0] == "--test":
        return _selftest()

    raws: list[str]
    if argv == ["-"]:
        raws = [line.strip() for line in sys.stdin if line.strip()]
    else:
        raws = argv

    n = FundNormalizer()
    out = [n.match(r) for r in raws]
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
