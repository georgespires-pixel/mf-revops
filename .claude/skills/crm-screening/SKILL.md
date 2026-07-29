---
name: crm-screening
description: Screen Moonfare's pre-qualified BD leads in HubSpot — enrich each lead, score it against the qualification rubric, and post Qualify/Skip proposals to Slack for human approval, then apply approved decisions to HubSpot. Use when asked to run BD CRM screening, screen the PQL queue, qualify pre-qualified leads, or run the daily BD screening session.
---

# BD CRM Screening (Phase 1 — human-approved copilot)

Run the screening exactly as defined in the playbook at the repo root:
**`crm-screening.md`**. That file is the single source of truth for the
prioritisation, the enrichment ladder, the qualification rubric, the HubSpot
property mapping, and the Slack approval loop. Do not improvise or re-derive the
decision logic — follow the playbook.

## How to run

1. Read `crm-screening.md` and follow its Steps end to end.
2. **Confirm the write-target property names first** (BD score, Business
   Development toggle, Lead Type). If any required one can't be confirmed, stop
   and report it in Slack — do not write to a guessed field.
3. **Pass A (propose):** pull the `lifecyclestage = lead` queue, prioritise by BD
   score + questionnaire answers, enrich each lead (compliant API or web search —
   **never** cookie-based LinkedIn automation), score against the rubric, and post
   one Qualify/Skip proposal per lead to the configured Slack channel.
4. **Pass B (apply):** read approvals (✅ = qualify, ❌ = skip) and apply each
   approved Qualify as a **single** action: `lifecyclestage → marketingqualifiedlead`,
   Business Development → Yes, Lead Type → New Business. **Do not set Contact
   Owner** — the native HubSpot workflow assigns it by country. Confirm results in
   the thread.

## Guardrails
- **Phase 1 writes to HubSpot only after human approval.** Phase 2 (auto-qualify
  above the confidence threshold) stays OFF until the rubric is ratified — see the
  playbook's Phase 2 section.
- **Owner assignment is HubSpot's**, not this skill's — only set the three fields
  that trigger the workflow.
- **No LinkedIn scraping/automation.** Enrichment is compliant APIs or web search.
- Heavy pulls: a sub-agent may enrich/score the queue, but post the proposals and
  apply the writes yourself.
- Keep this skill and `crm-screening.md` in sync.

## Status / open items before first live run
- [x] BD score for prioritisation = native `hubspotscore` (confirmed).
- [x] Slack approval channel = `#test-claude` (confirmed, interim).
- [x] **Pass B write path chosen + implemented:** private-app token + REST in
  [`scripts/passb_hubspot.py`](../../../scripts/passb_hubspot.py) (setup +
  commands in [`scripts/README.md`](../../../scripts/README.md)). The connected
  HubSpot MCP is read-only and cannot reach the Leads object, so all Pass B
  writes go through this script with the env token `HUBSPOT_BD_WRITE_TOKEN`.
- [x] **Sandbox + private-app token created** (EU sandbox portal 50160270);
  `HUBSPOT_BD_WRITE_TOKEN` set in the env. NOTE: a web session also needs
  `api.hubapi.com` added to the environment's **Custom** network allowlist —
  without it REST calls get a `403 CONNECT` (see `scripts/README.md`).
- [x] **Verified the full Slack approval loop end-to-end** (2026-07-22): Pass A
  posted a proposal to `#test-claude` via the Slack MCP → human reacted ✅ →
  reaction read back → Pass B applied to the sandbox (contact + lead, HTTP 200) →
  confirmation posted in-thread. Loop mechanics documented in `crm-screening.md`.
- [x] **Confirmed the Leads-object internal names** in the sandbox (portal
  50160270, 2026-07-21): Business Development = `business_development` (boolean
  checkbox, value `"true"`), Lead type = `hs_lead_type` (enum `"NEW_BUSINESS"`).
  Recorded in `scripts/lead_props.json`. **Re-confirm before pointing at prod.**
- [x] **Verified Pass B on ONE lead** in the sandbox: contact →
  `marketingqualifiedlead`, lead `business_development=true` +
  `hs_lead_type=NEW_BUSINESS`, all HTTP 200 and read back correctly.
- [ ] **Re-confirm the mapping against PROD** and verify on one prod lead before
  any batch (prod internal names/enums may differ from the sandbox).
- [x] **Pass B now moves the Lead pipeline stage directly.** Sandbox proved the
  Contact lifecycle and the Lead `hs_pipeline_stage` are independent (neither
  cascades), so Pass B sets both: Contact → `marketingqualifiedlead` (reporting)
  and Lead `hs_pipeline_stage` → "Marketing Qualified Lead" (sandbox id
  `159139484`, so Sales sees it). Verified end-to-end 2026-07-29.
- [ ] **Re-confirm the MQL stage id against prod** (`GET /crm/v3/pipelines/leads`)
  and update `lead_pipeline_stage` in `lead_props.json` — stage ids can differ per
  portal.
- [ ] Ratify the qualification rubric (weights + threshold) with Yijia/BD.
- [ ] (Optional) Wire a compliant enrichment API (Apollo/PDL/Clearbit).
