"""Offline heuristic extractor — keyword/regex signal extraction, no LLM.

Used by the xlsx importer (and anywhere) when no Anthropic key is configured, so
the pipeline runs fully offline. It is deliberately conservative: it only tags a
dimension when a clear keyword is present, and returns empty otherwise (matching
the "only extract what's stated" rule). Quality is far below the Claude
extractor — with a key set, use that instead.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from . import taxonomy

POSITIVE = [
    "interested", "keen", "excited", "love to", "happy to", "let's proceed",
    "move forward", "subscribe", "commit", "commitment", "allocate", "count us in",
    "looks great", "very interested", "would like to invest",
]
NEGATIVE = [
    "not interested", "no longer", "pass on", "decline", "unfortunately",
    "too high", "not a fit", "pausing", "hold off", "not now", "step back",
]
SERVICING = [
    "capital call", "k-1", "k1", "tax", "wire", "statement", "invoice",
    "login", "password", "reporting", "distribution notice", "nav ",
]

MONEY_RE = re.compile(
    r"(?:€|\$|£|eur|usd|gbp|chf)\s?\d[\d,\.]*\s?(?:k|m|mn|million|bn|billion|b)?",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _fund_needles() -> list[tuple[str, str]]:
    """(needle, canonical_name) pairs from canonical_funds.json."""
    from .normalize import _load_canonical

    out: list[tuple[str, str]] = []
    for fund in _load_canonical().values():
        name = fund["canonical_name"]
        out.append((name.lower(), name))
        for alias in fund.get("aliases", []):
            out.append((alias.lower(), name))
    # Longest needles first so specific aliases win.
    out.sort(key=lambda t: len(t[0]), reverse=True)
    return out


def _map_keywords(text: str, mapping: dict[str, str], *, multi: bool = True) -> list[str]:
    found: list[str] = []
    for needle, label in mapping.items():
        if needle in text and label not in found:
            found.append(label)
            if not multi:
                break
    return found


def _pad(text: str) -> str:
    # Pad so " us " / " uk " word-boundary needles can match at the edges.
    return f" {text.lower()} "


def heuristic_extract(
    *, contact_id: str, call_id: str, call_date: str, title: str, body: str
) -> dict[str, Any]:
    raw = f"{title}\n{body}"
    text = _pad(raw)

    # Funds mentioned (raw strings; normalize.py canonicalizes later).
    funds: list[str] = []
    for needle, canonical in _fund_needles():
        if needle in text and canonical not in funds:
            funds.append(canonical)

    asset_classes = _map_keywords(text, taxonomy.ASSET_CLASS_KEYWORDS)
    gics = _map_keywords(text, taxonomy.GICS_KEYWORDS)
    geographies = _map_keywords(text, taxonomy.GEOGRAPHY_KEYWORDS)
    currencies = _map_keywords(text, taxonomy.CURRENCY_KEYWORDS)
    caps = _map_keywords(text, taxonomy.CAP_KEYWORDS, multi=False)

    # Sentiment.
    is_servicing = any(s in text for s in SERVICING) and not funds and not asset_classes
    if is_servicing:
        sentiment = "neutral"
    elif any(n in text for n in NEGATIVE):
        sentiment = "negative"
    elif any(p in text for p in POSITIVE):
        sentiment = "positive"
    else:
        sentiment = "neutral"

    # Money: near commit/allocate -> ticket; near fund/target/raise -> fund size.
    ticket = None
    fund_size = None
    for m in MONEY_RE.finditer(raw):
        span = raw[max(0, m.start() - 40) : m.end() + 40].lower()
        val = m.group(0).strip()
        if any(w in span for w in ("commit", "allocate", "invest", "ticket", "subscrib")):
            ticket = ticket or val
        elif any(w in span for w in ("fund size", "target", "raising", "raise", "aum")):
            fund_size = fund_size or val
        else:
            ticket = ticket or val

    # If purely servicing, emit no investment signal.
    if is_servicing:
        funds, asset_classes, gics, geographies, currencies = [], [], [], [], []
        ticket = fund_size = None
        caps = []

    # A short evidence quote: first sentence that carries a signal word.
    quote = ""
    if funds or asset_classes or sentiment != "neutral":
        for sentence in re.split(r"(?<=[.!?])\s+", body.strip()):
            s = sentence.strip()
            low = s.lower()
            if 8 <= len(s) <= 200 and (
                any(p in low for p in POSITIVE)
                or any(n in low for n in NEGATIVE)
                or any(a.lower() in low for a in asset_classes)
                or any(f.lower() in low for f in funds)
            ):
                quote = s
                break

    return {
        "contact_id": contact_id,
        "call_id": call_id,
        "call_date": call_date,
        "funds_mentioned": funds,
        "asset_classes": asset_classes,
        "gics_sectors": gics,
        "geographies": geographies,
        "currency": currencies[0] if currencies else None,
        "fund_size_hint": fund_size,
        "cap_size": caps[0] if caps else None,
        "sentiment": sentiment,
        "pain_points": [],
        "ticket_size_hint": ticket,
        "urgency": "not_applicable",
        "next_steps": None,
        "evidence_quote": quote,
    }
