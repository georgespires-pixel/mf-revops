"""Synthetic investor calls & emails for the MVP (no HubSpot / no Claude needed).

Generates realistic-looking HubSpot-style engagements (call summaries + emails)
together with a ground-truth signal for each. This lets the whole pipeline
(normalize -> aggregate -> app) run offline:

  * messy fund names are used on purpose so the fuzzy normalizer has real work
    ("Moon for Tech Fund", "Moonfair Tech Fund", "buyout iii", ...),
  * ~30% of engagements are servicing-only (tax/reporting questions) that must
    produce NO buy signal — exercising the "servicing != interest" rule,
  * a subset of engagements are deliberately stale (older than 6 months) to
    exercise the deck-fit stale flag.

The ground-truth signal mirrors what the Claude extractor would return, so the
offline seed path and the real-extraction path are interchangeable.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# Reps (contact owners).
OWNERS = [
    {"id": "owner-alex", "name": "Alex Rivera", "email": "alex.rivera@moonfare.com"},
    {"id": "owner-sam", "name": "Sam Chen", "email": "sam.chen@moonfare.com"},
    {"id": "owner-jordan", "name": "Jordan Blake", "email": "jordan.blake@moonfare.com"},
]

# Investor personas.
INVESTORS = [
    ("Priya Nair", "priya.nair@example.com"),
    ("Marcus Feld", "marcus.feld@example.com"),
    ("Elena Rossi", "elena.rossi@example.com"),
    ("Tom Okafor", "tom.okafor@example.com"),
    ("Yuki Tanaka", "yuki.tanaka@example.com"),
    ("Hassan Ali", "hassan.ali@example.com"),
    ("Clara Muller", "clara.muller@example.com"),
    ("David Kim", "david.kim@example.com"),
    ("Sofia Alvarez", "sofia.alvarez@example.com"),
    ("Nils Bergstrom", "nils.bergstrom@example.com"),
    ("Aisha Bello", "aisha.bello@example.com"),
    ("Leo Fontaine", "leo.fontaine@example.com"),
]

# Fund "families": each canonical fund plus messy variants seen in transcripts.
FUND_FAMILIES = {
    "Moonfare Technology Fund": [
        "Moonfare Technology Fund", "Moon for Tech Fund", "Moonfair Tech Fund",
        "the tech fund", "Moonfare tech fund",
    ],
    "Moonfare Buyout Fund III": [
        "Moonfare Buyout Fund III", "buyout iii", "MF Buyout III", "the buyout fund",
    ],
    "Moonfare Infrastructure Fund": [
        "Moonfare Infrastructure Fund", "infra fund", "Moon Infrastructure",
    ],
    "Moonfare Private Credit Fund": [
        "Moonfare Private Credit Fund", "private credit", "the credit fund",
    ],
    "Moonfare Secondaries Fund II": [
        "Moonfare Secondaries Fund II", "secondaries ii", "the secondaries fund",
    ],
}
FUND_INDUSTRY = {
    "Moonfare Technology Fund": "technology",
    "Moonfare Buyout Fund III": "buyout",
    "Moonfare Infrastructure Fund": "infrastructure",
    "Moonfare Private Credit Fund": "private credit",
    "Moonfare Secondaries Fund II": "secondaries",
}

TICKETS = ["€250k", "$500k", "€1M", "$2M", None, None]
PAIN_POINTS = [
    "high management fees", "liquidity concerns", "minimum ticket too high",
    "reporting frequency", "currency hedging", "tax complexity",
]

POSITIVE_QUOTES = [
    "This is exactly the kind of exposure we've been looking for.",
    "We'd like to move quickly on this one.",
    "Please send the subscription docs — we're in.",
    "The strategy really resonates with our allocation plan.",
]
NEUTRAL_QUOTES = [
    "Interesting — I'll need to discuss it with my advisor.",
    "Let's revisit after the next quarter.",
    "Can you share the fee structure and past performance?",
]
NEGATIVE_QUOTES = [
    "The minimum is higher than we're comfortable with right now.",
    "We're pausing new commitments this year.",
    "This doesn't fit our current mandate.",
]


@dataclass
class Engagement:
    object_type: str  # "calls" | "emails"
    call_id: str
    contact_id: str
    contact_owner_id: str
    call_owner_id: str
    call_date: str  # ISO 8601
    title: str
    body: str
    truth: dict[str, Any] = field(default_factory=dict)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _ticket_clause(ticket: str | None) -> str:
    return f"They indicated a likely ticket of around {ticket}. " if ticket else ""


def generate(
    n_contacts: int = 12,
    *,
    seed: int = 42,
    now: datetime | None = None,
) -> tuple[list[Engagement], list[dict[str, Any]]]:
    """Return (engagements, contacts). Deterministic for a given seed."""
    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc)
    contacts: list[dict[str, Any]] = []
    engagements: list[Engagement] = []

    people = INVESTORS[:n_contacts] if n_contacts <= len(INVESTORS) else (
        INVESTORS * ((n_contacts // len(INVESTORS)) + 1)
    )[:n_contacts]

    for idx, (name, email) in enumerate(people):
        contact_id = f"c{1000 + idx}"
        owner = rng.choice(OWNERS)
        contacts.append(
            {
                "contact_id": contact_id,
                "name": name,
                "email": email,
                "lifecycle_stage": rng.choice(["lead", "salesqualifiedlead", "customer"]),
                "owner_id": owner["id"],
            }
        )

        n_eng = rng.randint(1, 4)
        for j in range(n_eng):
            call_id = f"{contact_id}-e{j}"
            object_type = rng.choice(["calls", "calls", "emails"])
            # ~20% stale (7-14 months old), rest within the last ~6 months.
            if rng.random() < 0.2:
                days_ago = rng.randint(210, 430)
            else:
                days_ago = rng.randint(1, 175)
            date = _iso(now - timedelta(days=days_ago, hours=rng.randint(0, 20)))
            rep_first = owner["name"].split()[0]
            name_first = name.split()[0]

            # ~30% servicing-only: no buy signal.
            if rng.random() < 0.30:
                truth = {
                    "funds_mentioned": [],
                    "industry_or_asset_class": [],
                    "sentiment": "neutral",
                    "pain_points": [],
                    "ticket_size_hint": None,
                    "urgency": "not_applicable",
                    "next_steps": None,
                    "evidence_quote": "",
                }
                if object_type == "calls":
                    title = "Servicing call"
                    body = (
                        f"{name} called about a tax-reporting question on their existing "
                        f"commitment — needed clarity on K-1 timing. No new fund interest "
                        f"discussed; purely operational."
                    )
                else:
                    title = "Re: capital call confirmation"
                    body = (
                        f"Hi {rep_first},\n\nJust confirming receipt of the capital call "
                        f"notice — the wire will go out Friday. Thanks,\n{name_first}"
                    )
                engagements.append(
                    Engagement(object_type, call_id, contact_id, owner["id"],
                               rng.choice([o["id"] for o in OWNERS]), date, title, body, truth)
                )
                continue

            # Investment-interest engagement.
            n_funds = 1 if rng.random() < 0.7 else 2
            fund_keys = rng.sample(list(FUND_FAMILIES), n_funds)
            fund_variants = [rng.choice(FUND_FAMILIES[k]) for k in fund_keys]
            sentiment = rng.choices(
                ["positive", "neutral", "negative"], weights=[5, 3, 2]
            )[0]
            quote = {
                "positive": rng.choice(POSITIVE_QUOTES),
                "neutral": rng.choice(NEUTRAL_QUOTES),
                "negative": rng.choice(NEGATIVE_QUOTES),
            }[sentiment]
            ticket = rng.choice(TICKETS) if sentiment != "negative" else None
            pains = rng.sample(PAIN_POINTS, rng.randint(0, 2))
            urgency = {
                "positive": rng.choice(["high", "medium"]),
                "neutral": "low",
                "negative": "low",
            }[sentiment]
            next_steps = (
                "Send subscription documents." if sentiment == "positive"
                else "Follow up next quarter." if sentiment == "neutral"
                else None
            )
            industries = [FUND_INDUSTRY[k] for k in fund_keys]

            truth = {
                "funds_mentioned": fund_variants,
                "industry_or_asset_class": industries,
                "sentiment": sentiment,
                "pain_points": pains,
                "ticket_size_hint": ticket,
                "urgency": urgency,
                "next_steps": next_steps,
                "evidence_quote": quote,
            }

            fund_phrase = " and ".join(fund_variants)
            if object_type == "calls":
                title = f"Intro call — {fund_keys[0]}"
                pain_clause = (
                    f" They raised {', '.join(pains)}." if pains else ""
                )
                body = (
                    f"Call with {name}. We walked through {fund_phrase} and the broader "
                    f"{industries[0]} thesis. Investor was {sentiment}. "
                    f"\"{quote}\"{pain_clause} {_ticket_clause(ticket)}"
                    f"{('Next steps: ' + next_steps) if next_steps else ''}"
                ).strip()
            else:
                title = f"Re: {fund_variants[0]} materials"
                body = (
                    f"Hi {rep_first},\n\nThanks for the {fund_phrase} deck. {quote} "
                    f"{_ticket_clause(ticket)}\n\nBest,\n{name_first}"
                ).strip()

            engagements.append(
                Engagement(object_type, call_id, contact_id, owner["id"],
                           rng.choice([o["id"] for o in OWNERS]), date, title, body, truth)
            )

    return engagements, contacts
