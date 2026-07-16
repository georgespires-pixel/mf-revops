"""Extraction pass: HubSpot call/email body -> structured investor signal.

Sends each qualifying body to the Claude API with a FIXED schema (kept stable so
historical data stays comparable across runs) using forced structured output.

Key principles enforced by the prompt:
  * Only extract what is actually stated — empty arrays if funds/industry weren't
    discussed. A servicing call (tax question, capital-call confirmation) is not
    a buy signal, even if a fund name is incidentally mentioned.
  * ``evidence_quote`` is required so every tag is auditable.
  * Multiple funds per call are normal — always an array.
"""

from __future__ import annotations

from typing import Any

import anthropic

# The analytical fields the model fills. contact_id / call_id / call_date are
# attached in code (they are known facts, not something to infer), so they are
# deliberately excluded from the model's schema.
EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "funds_mentioned": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Fund names the investor expressed interest in. Empty if none discussed.",
        },
        "asset_classes": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "Buyout", "Venture Capital", "Growth Equity", "Secondaries",
                    "Private Credit", "Infrastructure", "Real Estate",
                    "Fund of Funds", "Co-Investment",
                ],
            },
            "description": "Private-markets asset classes discussed as interest.",
        },
        "gics_sectors": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "Energy", "Materials", "Industrials", "Consumer Discretionary",
                    "Consumer Staples", "Health Care", "Financials",
                    "Information Technology", "Communication Services", "Utilities",
                    "Real Estate",
                ],
            },
            "description": "Underlying GICS sector(s) of interest, if stated.",
        },
        "geographies": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Geographies of interest (e.g. North America, Europe, DACH, Asia-Pacific, Global).",
        },
        "currency": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "Currency discussed (USD, EUR, GBP, CHF), else null.",
        },
        "fund_size_hint": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "Target/actual fund size discussed (e.g. '€500M'), else null. Distinct from the investor's ticket.",
        },
        "cap_size": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "For buyout interest: 'Small-cap', 'Mid-cap', or 'Large-cap', else null.",
        },
        "sentiment": {
            "type": "string",
            "enum": ["positive", "neutral", "negative", "not_applicable"],
        },
        "pain_points": {
            "type": "array",
            "items": {"type": "string"},
        },
        "ticket_size_hint": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "Stated or implied ticket size, else null.",
        },
        "urgency": {
            "type": "string",
            "enum": ["high", "medium", "low", "not_applicable"],
        },
        "next_steps": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
        },
        "evidence_quote": {
            "type": "string",
            "description": "The specific line (~25 words max) that justifies the extraction. Empty string if nothing was extracted.",
        },
    },
    "required": [
        "funds_mentioned",
        "asset_classes",
        "gics_sectors",
        "geographies",
        "currency",
        "fund_size_hint",
        "cap_size",
        "sentiment",
        "pain_points",
        "ticket_size_hint",
        "urgency",
        "next_steps",
        "evidence_quote",
    ],
}

SYSTEM_PROMPT = """\
You extract structured investor-interest signals from Moonfare's investor call \
summaries and emails. Moonfare is a private-markets investment platform; the \
contacts are (prospective) investors and the funds are Moonfare's private funds.

Rules:
- Only extract what is actually stated. If the conversation did not touch on \
funds or asset classes, return empty arrays — do not infer interest.
- A servicing/operational conversation is NOT a buy signal. Tax-reporting \
questions, capital-call confirmations, login issues, and spam-filter complaints \
should yield empty funds_mentioned and neutral sentiment even if a fund name is \
mentioned in passing.
- Multiple funds per conversation are normal — always emit an array.
- Capture asset class (buyout, venture capital, growth equity, secondaries, \
private credit, infrastructure, real estate, fund of funds, co-investment), the \
underlying GICS sector, geography, currency, fund size, and buyout cap size ONLY \
when stated or clearly implied; otherwise leave empty / null.
- evidence_quote must be the specific line that justifies the extraction \
(~25 words max). If nothing substantive was extracted, use an empty string.
- Do not invent a numeric interest score. Sentiment and urgency are categorical.
"""


class Extractor:
    """Wraps the Claude API for signal extraction."""

    def __init__(self, model: str = "claude-opus-4-8", client: anthropic.Anthropic | None = None):
        # The SDK resolves credentials from ANTHROPIC_API_KEY or an
        # `ant auth login` profile — no need to pass a key explicitly.
        self._client = client or anthropic.Anthropic()
        self._model = model

    def extract(
        self,
        *,
        contact_id: str,
        call_id: str,
        call_date: str,
        title: str,
        body: str,
    ) -> dict[str, Any]:
        """Extract a signal record for one call/email body.

        Returns the full fixed-schema record with the id/date fields attached.
        """
        user_content = (
            f"Conversation title: {title or '(none)'}\n\n"
            f"Conversation body:\n{body}"
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            output_config={
                "format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}
            },
            messages=[{"role": "user", "content": user_content}],
        )

        import json

        text = next((b.text for b in response.content if b.type == "text"), "{}")
        fields = json.loads(text)

        # Attach the known facts.
        return {
            "contact_id": contact_id,
            "call_id": call_id,
            "call_date": call_date,
            **fields,
        }
