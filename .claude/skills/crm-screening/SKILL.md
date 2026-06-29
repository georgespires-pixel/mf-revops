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
- [ ] Confirm + fill the HubSpot property names in the playbook's mapping table.
- [ ] Confirm/create the Slack channel and invite the Claude app.
- [ ] Ratify the qualification rubric (weights + threshold) with Yijia/BD.
- [ ] (Optional) Wire a compliant enrichment API (Apollo/PDL/Clearbit).
