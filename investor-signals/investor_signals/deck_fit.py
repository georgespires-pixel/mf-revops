"""Deck-fit report: score an uploaded investment deck against the local signals.

The investment team drops in a PDF/PPTX and gets:
  * a read of the fund (summary, pros/cons, track record, main points, what would
    draw investor attention) — from Claude when a key is set, else key facts
    extracted from the deck heuristically,
  * a Low/Medium/High demand fit with a GRANULAR, auditable breakdown of *why*,
    computed deterministically from the signal store (not invented by the model),
  * stats: for each asset class the deck targets, the % of contacts that have
    expressed interest, and named investor evidence.

Never a bare numeric score: fit is categorical, with the component breakdown
attached so a Medium is explainable. Signals older than ~6 months are flagged
stale rather than presented as current interest.
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic

from . import taxonomy

STALE_AFTER_DAYS = 183  # ~6 months

# ---------------------------------------------------------------------------
# Deck reading
# ---------------------------------------------------------------------------

def extract_deck_text(filename: str, data: bytes) -> str:
    """Extract plain text from a PDF or PPTX deck."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if lower.endswith(".pptx"):
        from pptx import Presentation

        prs = Presentation(io.BytesIO(data))
        chunks: list[str] = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    chunks.append(shape.text_frame.text)
        return "\n".join(chunks)
    raise ValueError("Unsupported deck format — upload a PDF or PPTX.")


_MONEY = r"(?:€|\$|£|EUR|USD|GBP|CHF)\s?\d[\d,\.]*\s?(?:k|m|mn|million|bn|billion|b)?"
_METRIC_PATTERNS = [
    (r"\d+(?:\.\d+)?\s*%\s*(?:net\s*)?irr", "IRR"),
    (r"irr\s*(?:of\s*)?\d+(?:\.\d+)?\s*%", "IRR"),
    (r"\d+(?:\.\d+)?\s*x\s*(?:net\s*)?(?:moic|multiple|tvpi|dpi)", "Multiple"),
    (r"(?:moic|tvpi|dpi)\s*(?:of\s*)?\d+(?:\.\d+)?\s*x", "Multiple"),
    (r"vintage\s*20\d\d", "Vintage"),
    (rf"fund\s*size\s*(?:of\s*)?{_MONEY}", "Fund size"),
    (rf"target(?:ing)?\s*{_MONEY}", "Target"),
]


def _map(text: str, mapping: dict[str, str]) -> list[str]:
    out: list[str] = []
    for needle, label in mapping.items():
        if needle in text and label not in out:
            out.append(label)
    return out


def deck_facts(deck_text: str) -> dict[str, Any]:
    """Structured facts pulled from the deck text (regex/keyword; no LLM)."""
    text = f" {deck_text.lower()} "
    metrics: list[str] = []
    for pattern, _label in _METRIC_PATTERNS:
        for m in re.findall(pattern, deck_text, flags=re.IGNORECASE):
            frag = m if isinstance(m, str) else " ".join(m)
            frag = frag.strip()
            if frag and frag not in metrics:
                metrics.append(frag)
    currencies = _map(text, taxonomy.CURRENCY_KEYWORDS)
    fund_size = None
    fs = re.search(rf"(?:fund\s*size|target(?:ing)?|raising)\s*(?:of\s*)?({_MONEY})",
                   deck_text, flags=re.IGNORECASE)
    if fs:
        fund_size = fs.group(1).strip()
    return {
        "asset_classes": _map(text, taxonomy.ASSET_CLASS_KEYWORDS),
        "gics_sectors": _map(text, taxonomy.GICS_KEYWORDS),
        "geographies": _map(text, taxonomy.GEOGRAPHY_KEYWORDS),
        "currency": currencies[0] if currencies else None,
        "cap_size": (_map(text, taxonomy.CAP_KEYWORDS) or [None])[0],
        "fund_size": fund_size,
        "metrics": metrics[:8],
    }


# ---------------------------------------------------------------------------
# Demand analysis (deterministic — this is what makes the score explainable)
# ---------------------------------------------------------------------------

def _mark_stale(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STALE_AFTER_DAYS)).isoformat()
    for s in signals:
        s["stale"] = bool((s.get("last_signal_date") or "") and s["last_signal_date"] < cutoff)
    return signals


def demand_analysis(signals: list[dict[str, Any]], facts: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fit from the store: matches, per-asset-class interest %,
    a component score breakdown, and named evidence."""
    from .normalize import _load_canonical

    dataset = _mark_stale([dict(s) for s in signals])
    total = len(dataset) or 1
    deck_text_l = " " + " ".join(
        facts.get("asset_classes", []) + facts.get("gics_sectors", [])
        + facts.get("geographies", [])
    ).lower() + " "

    # Funds the deck names.
    matched_funds = [
        f["canonical_name"]
        for f in _load_canonical().values()
        if any(n in deck_text_l for n in [f["canonical_name"].lower()])
    ]
    deck_acs = set(facts.get("asset_classes", []))
    deck_secs = set(facts.get("gics_sectors", []))
    deck_geos = set(facts.get("geographies", []))

    # Per-asset-class interest across ALL contacts (the requested stat).
    ac_counts: dict[str, dict[str, int]] = {}
    for s in dataset:
        pos = s.get("sentiment_latest") == "positive" and not s["stale"]
        for ac in s.get("asset_classes", []):
            d = ac_counts.setdefault(ac, {"contacts": 0, "positive": 0})
            d["contacts"] += 1
            d["positive"] += 1 if pos else 0
    asset_class_interest = sorted(
        (
            {
                "asset_class": ac,
                "contacts": d["contacts"],
                "positive": d["positive"],
                "pct": round(100 * d["contacts"] / total),
                "in_deck": ac in deck_acs,
            }
            for ac, d in ac_counts.items()
        ),
        key=lambda x: (x["in_deck"], x["contacts"]),
        reverse=True,
    )

    # Named evidence: contacts overlapping the deck on asset class / sector /
    # geography / fund.
    evidence: list[dict[str, Any]] = []
    positive_overlap = 0
    for s in dataset:
        overlaps: list[str] = []
        overlaps += sorted(deck_acs & set(s.get("asset_classes", [])))
        overlaps += sorted(deck_secs & set(s.get("gics_sectors", [])))
        overlaps += sorted(deck_geos & set(s.get("geographies", [])))
        overlaps += sorted(set(matched_funds) & set(s.get("funds_mentioned", [])))
        if not overlaps:
            continue
        sentiment = s.get("sentiment_latest")
        if sentiment == "positive" and not s["stale"]:
            positive_overlap += 1
        quote = (s.get("evidence") or [{}])[0].get("quote", "")
        evidence.append(
            {
                "contact_id": s["contact_id"],
                "fund_or_industry": ", ".join(dict.fromkeys(overlaps)),
                "why": f"sentiment: {sentiment or 'unknown'}" + (" · stale" if s["stale"] else ""),
                "quote": quote,
                "stale": s["stale"],
            }
        )

    # Component score breakdown -> fit level.
    ac_demand = sum(ac_counts.get(ac, {}).get("contacts", 0) for ac in deck_acs)
    ac_positive = sum(ac_counts.get(ac, {}).get("positive", 0) for ac in deck_acs)
    breakdown = [
        {
            "factor": "Asset-class demand",
            "detail": f"{ac_demand} contact(s) interested in {', '.join(deck_acs) or 'the deck asset class(es)'}"
            + (f"; {ac_positive} currently positive" if ac_demand else ""),
            "points": min(3, ac_demand) + (1 if ac_positive else 0),
        },
        {
            "factor": "Fund overlap",
            "detail": f"deck names {len(matched_funds)} fund(s) present in the store"
            if matched_funds else "no Moonfare fund from the store named in the deck",
            "points": min(2, len(matched_funds)),
        },
        {
            "factor": "Positive, current interest",
            "detail": f"{positive_overlap} overlapping contact(s) with positive, non-stale sentiment",
            "points": min(3, positive_overlap),
        },
        {
            "factor": "Sector / geography overlap",
            "detail": f"{len(deck_secs)} sector + {len(deck_geos)} geography theme(s) shared",
            "points": 1 if (deck_secs or deck_geos) and evidence else 0,
        },
    ]
    score = sum(b["points"] for b in breakdown)
    level = "High" if score >= 6 else "Medium" if score >= 2 else "Low"

    summary = (
        f"{len(evidence)} contact(s) in the store overlap the deck's thesis "
        f"({positive_overlap} with current positive sentiment). Fit is {level} "
        f"based on the component breakdown below."
        if evidence
        else "No contacts in the store overlap this deck's asset class, sectors, "
        "geography, or named funds — Low demand fit."
    )
    return {
        "fit_level": level,
        "summary": summary,
        "matched_funds": matched_funds,
        "matched_asset_classes": sorted(
            deck_acs & {ac for s in dataset for ac in s.get("asset_classes", [])}
        ),
        "matched_industries": sorted(
            deck_secs & {s2 for s in dataset for s2 in s.get("gics_sectors", [])}
        ),
        "score_breakdown": breakdown,
        "asset_class_interest": asset_class_interest,
        "evidence": evidence,
    }


def _heuristic_narrative(facts: dict[str, Any]) -> dict[str, Any]:
    """Deck read without an LLM: surface the extracted facts, no prose invented."""
    bits = []
    if facts["asset_classes"]:
        bits.append(f"asset class: {', '.join(facts['asset_classes'])}")
    if facts["geographies"]:
        bits.append(f"geography: {', '.join(facts['geographies'])}")
    if facts["fund_size"]:
        bits.append(f"fund size: {facts['fund_size']}")
    if facts["cap_size"]:
        bits.append(f"cap: {facts['cap_size']}")
    return {
        "fund_summary": "",
        "one_paragraph": "",
        "pros": [],
        "cons": [],
        "track_record": ", ".join(facts["metrics"]) if facts["metrics"] else "",
        "main_points": [b.capitalize() for b in bits],
        "investor_attention": [],
    }


# ---------------------------------------------------------------------------
# LLM narrative
# ---------------------------------------------------------------------------

NARRATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "fund_summary": {"type": "string", "description": "A few sentences on what the fund is."},
        "one_paragraph": {"type": "string", "description": "One-paragraph investor-facing overview."},
        "pros": {"type": "array", "items": {"type": "string"}},
        "cons": {"type": "array", "items": {"type": "string"}},
        "track_record": {"type": "string", "description": "Track record: IRR/MOIC/vintages/prior funds if stated."},
        "main_points": {"type": "array", "items": {"type": "string"}},
        "investor_attention": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What would draw investor attention or interest.",
        },
    },
    "required": [
        "fund_summary", "one_paragraph", "pros", "cons",
        "track_record", "main_points", "investor_attention",
    ],
}

NARRATIVE_PROMPT = """\
You are reading a private-markets fund deck for Moonfare's investment team. From \
the deck text ONLY, produce: a few-sentence summary of the fund, a one-paragraph \
investor-facing overview, pros and cons, the track record (IRR/MOIC/vintages/prior \
funds if stated), the main points, and what would draw investor attention. Be \
concrete and grounded in the deck — do not invent numbers. Do not output any fit \
score; a separate step computes demand fit from CRM signals.
"""


class DeckFitReporter:
    def __init__(self, model: str = "claude-opus-4-8", client: anthropic.Anthropic | None = None):
        self._client = client or anthropic.Anthropic()
        self._model = model

    def _narrative(self, deck_text: str) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=2500,
            system=NARRATIVE_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": NARRATIVE_SCHEMA}},
            messages=[{"role": "user", "content": f"DECK TEXT:\n{deck_text[:40000]}"}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "{}")
        return json.loads(text)

    def assess(self, deck_text: str, signals: list[dict[str, Any]]) -> dict[str, Any]:
        facts = deck_facts(deck_text)
        report = demand_analysis(signals, facts)
        report.update(self._narrative(deck_text))
        report["deck_facts"] = facts
        report["caveats"] = [
            "Fit is categorical with a component breakdown; there is deliberately no numeric score.",
            "Demand fit is computed from the signal store; the fund read is model-generated from the deck.",
        ]
        return report


def heuristic_assess(deck_text: str, signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Fully offline path: deterministic demand analysis + facts-only deck read."""
    facts = deck_facts(deck_text)
    report = demand_analysis(signals, facts)
    report.update(_heuristic_narrative(facts))
    report["deck_facts"] = facts
    report["caveats"] = [
        "Offline mode: the fund read shows facts extracted from the deck (no model summary). "
        "Set an Anthropic API key for a full narrative (summary, pros/cons, track record).",
        "Demand fit is computed from the signal store; fit is categorical with a component breakdown, never a bare number.",
    ]
    return report
