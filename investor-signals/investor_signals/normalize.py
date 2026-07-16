"""Fuzzy-match extracted fund mentions against the canonical fund list.

AI-generated call summaries and transcripts will not use consistent fund names
("Moonfare Technology Fund", "Moon for Tech Fund", "Moonfair Tech Fund"). This
is a permanent feature of the data, so every extracted fund string is matched
against ``canonical_funds.json`` using case-insensitive substring + fuzzy
matching. Anything that clears the threshold is canonicalized; anything that
doesn't is kept verbatim and flagged ``unmatched`` rather than dropped or
force-matched.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

CANONICAL_PATH = Path(__file__).resolve().parent / "canonical_funds.json"


@dataclass
class FundMatch:
    raw: str
    canonical_name: str | None
    fund_key: str | None
    score: int
    unmatched: bool


@lru_cache(maxsize=1)
def _load_canonical() -> dict[str, dict]:
    return json.loads(CANONICAL_PATH.read_text())


def _norm(text: str) -> str:
    text = text.lower().strip()
    # Drop punctuation, collapse whitespace.
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _ratio(a: str, b: str) -> int:
    return int(round(SequenceMatcher(None, a, b).ratio() * 100))


def match_fund(raw: str, *, threshold: int = 82) -> FundMatch:
    """Match a single raw fund string to a canonical fund."""
    norm_raw = _norm(raw)
    if not norm_raw:
        return FundMatch(raw=raw, canonical_name=None, fund_key=None, score=0, unmatched=True)

    canonical = _load_canonical()
    best_key: str | None = None
    best_score = 0

    for key, fund in canonical.items():
        candidates = [_norm(fund["canonical_name"])]
        candidates += [_norm(a) for a in fund.get("aliases", [])]
        for cand in candidates:
            if not cand:
                continue
            # Substring match in either direction is a strong signal.
            if cand in norm_raw or norm_raw in cand:
                score = max(90, _ratio(norm_raw, cand))
            else:
                score = _ratio(norm_raw, cand)
            if score > best_score:
                best_score = score
                best_key = key

    if best_key is not None and best_score >= threshold:
        return FundMatch(
            raw=raw,
            canonical_name=canonical[best_key]["canonical_name"],
            fund_key=best_key,
            score=best_score,
            unmatched=False,
        )
    return FundMatch(
        raw=raw, canonical_name=None, fund_key=None, score=best_score, unmatched=True
    )


def normalize_funds(raw_funds: list[str], *, threshold: int = 82) -> list[dict]:
    """Normalize a list of raw fund strings.

    Returns a list of dicts. Matched funds carry the canonical name; unmatched
    funds keep the raw string and ``unmatched: true`` so they can be reviewed
    and promoted to new aliases/funds later.
    """
    results: list[dict] = []
    seen: set[str] = set()
    for raw in raw_funds:
        m = match_fund(raw, threshold=threshold)
        display = m.canonical_name or raw
        dedupe_key = (m.fund_key or display).lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        results.append(
            {
                "name": display,
                "raw": raw,
                "fund_key": m.fund_key,
                "score": m.score,
                "unmatched": m.unmatched,
            }
        )
    return results


def canonical_fund_names() -> list[str]:
    """All canonical fund names, for populating dashboard filters."""
    return [f["canonical_name"] for f in _load_canonical().values()]
