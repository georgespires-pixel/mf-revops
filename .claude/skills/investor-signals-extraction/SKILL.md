---
name: investor-signals-extraction
description: >
  Extract structured investor-interest signals (fund mentioned, industry/asset
  class, sentiment, pain points, ticket size, urgency) from HubSpot call
  summaries and emails, normalize fund names against a canonical list, and
  persist them to a local store for an internal app to query — read-only against
  HubSpot, no CRM writes. Use this whenever the user asks to analyze investor
  calls, tag investor interest, build a fund-interest view for the sales team,
  run the CRM enrichment/analysis pipeline, or process a batch of call/email
  records for signal extraction — even if they just say "run the extraction" or
  "sync investor signals." Always use this before writing ad-hoc extraction
  prompts by hand.
---

# Investor Signals Extraction

Read investor conversations from HubSpot (calls, emails, meetings, tasks),
extract one structured **investor-interest signal** per engagement, normalize
the funds mentioned against Moonfare's canonical fund list, and append the
results to a local store that powers the **Investor Signals** query app
(`investor-signals/app/index.html`).

> **READ-ONLY against HubSpot. Never create, update, or delete any HubSpot
> record.** This pipeline only *reads* engagements and *writes to the local repo*
> (the JSONL store + the app data bundle). It does not post to Slack.

## What this produces

- `investor-signals/store/signals.jsonl` — the append-only store, one JSON
  record per engagement, keyed by `signal_id` (`sig_<type>_<engagement_id>`),
  conforming to `investor-signals/store/schema.json`.
- `investor-signals/app/data.js` — the regenerated bundle the app reads.
- A short run summary (counts by interest level, top funds, unmatched mentions).

---

## Hardcoded constants — DO NOT rediscover these each run

| Thing | Value |
|---|---|
| HubSpot account id | `3846368` (EU data center, `app-eu1.hubspot.com`, EUR, tz Europe/Berlin) |
| Call summary property | `hs_call_summary` (AI-generated HTML) — primary source for calls |
| Call fallback body | `hs_call_body` (often just `[Inbound]`/`[Outbound]` + recording URL — low value) |
| Call fields | `hs_timestamp`, `hs_call_title`, `hs_call_summary`, `hs_call_direction`, `hs_call_duration`, `hs_call_disposition` |
| Email fields | `hs_timestamp`, `hs_email_subject`, `hs_email_text`, `hs_email_direction`, `hs_email_from_email`, `hs_email_to_email` |
| Canonical fund source | Notion **Fund Launch Pipeline Tracker**, data source `collection://362bf38b-4866-4cde-9843-2992424d38df`, title column `Target Fund Name` |
| Canonical fund file | `investor-signals/funds.json` (funds + aliases + competitors + brand fixups) |
| Controlled vocab | `investor-signals/taxonomy.json` |
| Engagement deep link | `https://app-eu1.hubspot.com/calls/3846368/review/<engagement_id>` (calls) |

> **Brand transcription caveat.** HubSpot's AI call summaries systematically
> mis-transcribe the brand — **"Moonfair"**, **"Moonsphere"**, "Moon Fair" all mean
> **Moonfare**, and the "Moonfair Tech Fund" is the **Moonfare Tech Fund**. The
> normalizer handles this (`_brand_aliases` in `funds.json`); don't treat these as
> different entities.

---

## Procedure

### Step 1 — Resolve the run window
Default to engagements with `hs_timestamp` in the **last 14 days**. If the store
already has records, you may instead pull everything newer than the max
`timestamp` already stored. If the user names a window ("last month", "this
week"), use that. Record the window in the run summary.

### Step 2 — (Optional) Refresh the canonical fund list
Pull current fund names from Notion so new launches are matchable:
`notion-query-data-sources` (SQL mode) on `collection://362bf38b-4866-4cde-9843-2992424d38df`:
`SELECT "Target Fund Name", "Status on MF Platform" FROM "collection://362bf38b-4866-4cde-9843-2992424d38df"`.
Merge any genuinely new fund into `funds.json` (new `fund_id`, `name`,
`asset_class`, `status`, `aliases`). **Preserve existing hand-curated aliases and
the `_brand_aliases` block** — only add, don't overwrite. Skip this step if the
user just wants a quick extraction.

### Step 3 — Pull the engagements (read-only)
Use `HubSpot:search_crm_objects`, paginating on `total`:
- **Calls:** `objectType: "calls"`, `filterGroups: [{filters:[{propertyName:"hs_call_summary", operator:"HAS_PROPERTY"}]}]`,
  sorted by `hs_timestamp` DESC, with the call fields above. (Filtering on
  `HAS_PROPERTY` skips the huge tail of contentless `[Inbound]` call logs.)
- **Emails:** `objectType: "emails"` with the email fields above; keep those with
  a substantive `hs_email_text`.
- **Tasks/notes** (optional): include if the user asks; same shape.
Strip HTML from `hs_call_summary`/`hs_email_text` to plain text before reading.

### Step 4 — Classify and filter
For each engagement decide `interest_level` (taxonomy):
`hot` / `warm` / `cold` / `existing_investor` / `not_investor`. Set
`not_investor` for device/connection tests, internal Zoom/logistics chatter,
recruitment/candidate calls, vendor calls, and "Voice of the Investor" research
logistics. Keep `not_investor` records in the store (the app hides them by
default) but do **not** mine them for funds/tickets.

### Step 5 — Extract the signal
For each engagement, produce one record matching `store/schema.json`. Fill:
- `sentiment` (+ optional `sentiment_score`), `urgency`, `asset_classes` (from
  the taxonomy enum — use `Multi-Strategy / Evergreen` for the generic
  Evergreen/semi-liquid pitch, `Secondaries` for the Secondary Fund, etc.),
  `industries` (short free-text: Technology, Healthcare, AI, Energy…).
- `ticket_size`: capture the **investor's own** stated/implied ticket. If only
  platform *minimums* were discussed (e.g. "€25k evergreen / $125k third-party"),
  set `basis: "threshold_discussed"` and leave `amount_eur` null. Normalize a
  point estimate to EUR in `amount_eur` only when currency is EUR and it's a
  single number; use `min`/`max`/`currency` for ranges and non-EUR.
- `pain_points` / `objections` (prefer the `common_pain_points` phrasings),
  `next_step` (+ `next_step_date` if a deadline/capital-call/closing was named →
  usually implies `urgency: high`), 2–4 short `quotes` as evidence, a 1–2 sentence
  `summary`, `contact.name`/`owner` (parse from the call title, e.g.
  `"A <> B"`, `"Call with Moonfare: <name>"`, `"<contact> / <rep>"`), and
  `hubspot_url`.
- Leave `contact.id`/`email`/`company.id` null unless you enrich (Step 5b).

**Association enrichment (optional, improves the sales view).** To attach real
contact/company ids + emails, look up the engagement's associations and pull the
contact (`firstname`, `lastname`, `email`) and company (`name`). Skip when doing a
fast batch; the app works without it.

### Step 6 — Normalize fund mentions
For every fund/product named, run it through the normalizer rather than guessing:
```
python3 investor-signals/scripts/normalize_funds.py "Moonfair Tech Fund" "EQT" "Horovich fund"
```
It returns `{raw, canonical, fund_id, asset_class, match, confidence}` per input
(`match` ∈ exact/alias/fuzzy/unmatched). Put the results in the record's `funds`
array; keep `match: "unmatched"` entries (with `canonical: null`) so the app can
surface them for review — do **not** silently drop an unrecognized fund. Also
collect rival platforms/managers (Hamilton Lane, StepStone, iCapital…) into
`competitors_mentioned` via the normalizer's competitor index. Generic structure
words ("evergreen", "a secondary fund") are asset classes, not named funds — put
them in `asset_classes`, not `funds`.

### Step 7 — Upsert into the store
Compute `signal_id = "sig_" + engagement_type + "_" + engagement_id`. Append new
records to `store/signals.jsonl`; if a `signal_id` already exists, **replace** that
line (re-extraction wins) rather than duplicating. One JSON object per line.

### Step 8 — Validate + rebuild the app bundle
```
python3 investor-signals/scripts/build_store.py
```
This validates every record (required fields, enum + taxonomy conformance, dedup,
`signal_id` convention), prints the summary, and regenerates
`investor-signals/app/data.js`. **It must exit 0** — fix any reported error before
finishing. Run `python3 investor-signals/scripts/normalize_funds.py --test` if you
touched `funds.json`.

### Step 9 — Report (and commit if asked)
Return the run summary: window, engagements processed, counts by interest level,
top funds by interested investors, and any unmatched fund mentions to review.
Commit the changed files (`store/signals.jsonl`, `app/data.js`, `funds.json`) when
the user wants the store persisted. **Never** touch HubSpot and **never** post to
Slack from this skill.

---

## Notes & failure modes
- **Read-only.** No `create_*`/`update_*`/`manage_*` HubSpot calls. Ever.
- **Don't invent tickets.** Platform minimums are not the investor's ticket.
- **Keep the vocab closed.** `asset_classes`, `sentiment`, `interest_level`,
  `urgency` must come from `taxonomy.json`. If a genuinely new category is needed,
  add it to `taxonomy.json` first, then use it.
- **Unmatched funds are signal, not noise** — they usually mean a transcription
  error or a brand-new fund; leave them in for review and consider adding an alias.
- **Large payloads.** If a HubSpot search returns via a stored tool-results file,
  read it with python (`json.loads`) rather than assuming inline JSON.
- **The app is static.** It reads `app/data.js` (works via `file://` on a
  double-click) and also has a "Load file…" fallback to open `store/signals.jsonl`
  directly. No server required.
