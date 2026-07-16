"""Deck-fit report: score an uploaded investment deck against the local signals.

The investment team drops in a PDF/PPTX; they get a Low/Medium/High fit report
with NAMED investor evidence — never a bare numeric score. Per the skill's honesty
check: a fake-precise number invites over-trust; a Low/Medium/High level with the
evidence quote attached is defensible. If asked for a number, we decline and
explain why.

Stale-data check: signals whose last qualifying call is older than ~6 months are
flagged stale rather than presented as current interest.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic

STALE_AFTER_DAYS = 183  # ~6 months

FIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "fit_level": {"type": "string", "enum": ["Low", "Medium", "High"]},
        "summary": {
            "type": "string",
            "description": "Plain-language rationale for the fit level.",
        },
        "matched_funds": {"type": "array", "items": {"type": "string"}},
        "matched_industries": {"type": "array", "items": {"type": "string"}},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "contact_id": {"type": "string"},
                    "fund_or_industry": {"type": "string"},
                    "why": {"type": "string"},
                    "quote": {"type": "string"},
                    "stale": {"type": "boolean"},
                },
                "required": ["contact_id", "fund_or_industry", "why", "quote", "stale"],
            },
        },
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "fit_level",
        "summary",
        "matched_funds",
        "matched_industries",
        "evidence",
        "caveats",
    ],
}

SYSTEM_PROMPT = """\
You assess how well an investment deck fits Moonfare's existing investor demand, \
using ONLY the provided per-contact signal dataset (extracted from investor calls \
and emails).

Rules:
- Output a categorical fit level (Low / Medium / High), never a numeric score. A \
fake-precise number invites over-trust; a level with named evidence is defensible.
- Every point of the assessment must cite specific contacts by contact_id with \
the evidence quote that justifies it. Do not claim interest you cannot point to.
- A contact whose signal is marked stale (last_signal_date older than ~6 months) \
must be flagged stale=true in the evidence and must not be presented as current \
interest.
- If the dataset contains no relevant demand for the deck's thesis, say so \
plainly and return fit_level "Low" with empty evidence.
"""


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


def _mark_stale(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STALE_AFTER_DAYS)).isoformat()
    compact: list[dict[str, Any]] = []
    for s in signals:
        last = s.get("last_signal_date") or ""
        compact.append(
            {
                "contact_id": s["contact_id"],
                "contact_owner_id": s.get("contact_owner_id"),
                "funds_mentioned": s.get("funds_mentioned", []),
                "industries": s.get("industries", []),
                "sentiment_latest": s.get("sentiment_latest"),
                "ticket_size_hint": s.get("ticket_size_hint"),
                "evidence": s.get("evidence", []),
                "last_signal_date": last,
                "stale": bool(last and last < cutoff),
            }
        )
    return compact


def heuristic_assess(deck_text: str, signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Offline deck-fit: keyword overlap between the deck and stored demand.

    Used in MVP/offline mode (no Claude key). Honest by construction — it returns
    a categorical Low/Medium/High with named evidence, and a caveat stating it's a
    keyword-overlap heuristic, not a model assessment. Still never a bare score.
    """
    from .normalize import _load_canonical  # local import to avoid cycle at import

    text = deck_text.lower()
    dataset = _mark_stale(signals)

    # Which canonical funds does the deck reference (by name or alias)?
    matched_funds: list[str] = []
    for fund in _load_canonical().values():
        needles = [fund["canonical_name"].lower()] + [
            a.lower() for a in fund.get("aliases", [])
        ]
        if any(n in text for n in needles):
            matched_funds.append(fund["canonical_name"])

    # Which industries present in the store does the deck reference?
    all_inds = {i for s in dataset for i in s.get("industries", [])}
    matched_inds = sorted(i for i in all_inds if i.lower() in text)

    evidence: list[dict[str, Any]] = []
    strong = 0
    for s in dataset:
        fund_overlap = sorted(set(s.get("funds_mentioned", [])) & set(matched_funds))
        ind_overlap = sorted(set(s.get("industries", [])) & set(matched_inds))
        if not fund_overlap and not ind_overlap:
            continue
        sentiment = s.get("sentiment_latest")
        if sentiment == "positive" and not s["stale"]:
            strong += 1
        quote = ""
        ev = s.get("evidence") or []
        if ev:
            quote = ev[0].get("quote", "")
        evidence.append(
            {
                "contact_id": s["contact_id"],
                "fund_or_industry": ", ".join(fund_overlap + ind_overlap),
                "why": f"Signal sentiment: {sentiment or 'unknown'}"
                + (" (stale)" if s["stale"] else ""),
                "quote": quote,
                "stale": s["stale"],
            }
        )

    if strong >= 3:
        level = "High"
    elif evidence:
        level = "Medium"
    else:
        level = "Low"

    summary = (
        f"Offline keyword-overlap assessment. The deck references "
        f"{len(matched_funds)} known fund(s) and {len(matched_inds)} industry theme(s) "
        f"present in the signal store; {len(evidence)} contact(s) show overlapping "
        f"demand ({strong} with current positive sentiment)."
        if evidence
        else "The deck's themes don't overlap with any current demand in the signal store."
    )
    return {
        "fit_level": level,
        "summary": summary,
        "matched_funds": matched_funds,
        "matched_industries": matched_inds,
        "evidence": evidence,
        "caveats": [
            "Offline heuristic (keyword overlap), not a model assessment — run with "
            "an Anthropic API key for a nuanced read.",
            "Fit is categorical by design; there is deliberately no numeric score.",
        ],
    }


class DeckFitReporter:
    def __init__(self, model: str = "claude-opus-4-8", client: anthropic.Anthropic | None = None):
        self._client = client or anthropic.Anthropic()
        self._model = model

    def assess(self, deck_text: str, signals: list[dict[str, Any]]) -> dict[str, Any]:
        dataset = _mark_stale(signals)
        user_content = (
            "INVESTOR SIGNAL DATASET (JSON):\n"
            f"{json.dumps(dataset, indent=2)}\n\n"
            "DECK TEXT:\n"
            f"{deck_text[:40000]}"  # bound very large decks
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": FIT_SCHEMA}},
            messages=[{"role": "user", "content": user_content}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "{}")
        return json.loads(text)
