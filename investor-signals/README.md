# Investor Signals

Internal tool that turns unstructured Moonfare investor conversations (HubSpot
call summaries and emails) into structured, queryable signals in a local app — so
the sales team can filter "who's interested in Fund X" and the investment team
can check how a deck fits existing demand.

**Read-only against HubSpot. No CRM writes, ever.** All extracted signal lives in
a local SQLite store; live name/email/lifecycle are joined from HubSpot only at
read time. It governs extraction + local persistence per the
`investor-signal-extraction` skill.

> ⚠️ **Compliance:** this dataset will be used to target outreach for private-fund
> placements even though it never touches HubSpot. Before going live for the
> sales team, run a compliance/legal sanity check given the regulatory context
> around investor solicitation. Don't assume it's already been cleared.

## Pipeline

```
HubSpot (read-only)                 Claude API              Local app
  Calls / Emails  ──search──▶  extract (fixed schema)
  Contacts/Owners             normalize funds (fuzzy)  ──▶  SQLite store
                                                             │
                              ┌──────────────────────────────┤
                       Sales dashboard              Deck-fit report
                  (filter by fund/industry/       (PDF/PPTX → Low/Medium/High
                   sentiment/rep; live-joined       + named investor evidence,
                   name/email)                      never a bare number)
```

## Components

| File | Role |
|---|---|
| `investor_signals/hubspot_client.py` | Read-only pull of Calls, Emails, Contacts, Owners — paginated, owner/date filters |
| `investor_signals/extract.py` | Sends each qualifying body to the Claude API for structured extraction (fixed schema) |
| `investor_signals/normalize.py` + `canonical_funds.json` | Fuzzy-match extracted fund mentions against the canonical fund list |
| `investor_signals/store.py` | SQLite store of aggregated per-contact signals; incremental sync state |
| `investor_signals/sync.py` | Orchestration: pull → extract → normalize → persist |
| `investor_signals/deck_fit.py` | Deck-fit report generator |
| `investor_signals/app.py` + `static/index.html` | FastAPI app (sales dashboard + deck upload) |
| `investor_signals/cli.py` | CLI: `sync`, `serve` |

## Setup

```bash
cd investor-signals
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml   # edit scope (rep owner id + month)
cp .env.example .env                  # add HUBSPOT_TOKEN (read-only); ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)   # or use your own env loader
```

The HubSpot token must be a **read-only** private-app token (contacts/calls/emails/
owners read scopes only — no write scopes).

## Pilot first

Start with **one rep for one month** to validate extraction quality before syncing
the whole team. In `config.yaml`:

```yaml
sync:
  mode: pilot
  owner_ids: ["<one rep's HubSpot owner id>"]
  date_range: { start: "2026-06-01", end: "2026-06-30" }
```

Then:

```bash
python -m investor_signals sync     # pull + extract + persist (incremental)
python -m investor_signals serve    # http://127.0.0.1:8000
```

Re-running `sync` only processes engagements newer than the last run (tracked per
object type in the store), so API usage and runtime stay bounded as data grows.

Once the pilot looks good, switch `mode: team` (empty `owner_ids` resolves all
active owners) and re-run `sync`.

## Design notes (from the skill)

- **Fixed extraction schema** — kept stable across runs so historical data stays
  comparable. Every tag carries an `evidence_quote` so it's auditable.
- **Servicing ≠ buy signal** — tax questions, capital-call confirmations, etc.
  yield empty funds / neutral sentiment even if a fund is mentioned in passing.
- **Owner resolution** — signals are written to the *contact's* owner (the
  relationship owner), not the call's owner. The call owner is kept as audit-only
  metadata.
- **Aggregate, don't overwrite** — new extractions merge into the existing
  contact row (funds, industries, evidence accumulate).
- **Fund normalization** — unmatched fund strings are kept and flagged
  `unmatched` (shown with a `?` in the dashboard) for periodic review, never
  silently dropped or force-matched.
- **No numeric interest score** — the dashboard shows categorical sentiment, and
  the deck-fit report is Low/Medium/High with named evidence, never a bare number.
- **Stale data** — deck-fit flags any contact whose last qualifying call is older
  than ~6 months rather than presenting it as current interest.
