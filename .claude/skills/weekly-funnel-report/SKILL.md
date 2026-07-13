---
name: weekly-funnel-report
description: Generate Moonfare's weekly Funnel & MQL report from live HubSpot and post the digest to Slack. Use when asked to run, refresh, or send the weekly funnel report, the RevOps funnel digest, or the "Funnel and MQLs" report — on demand or on the Sunday schedule.
---

# Weekly Funnel & MQL report

Run the report exactly as defined in the playbook at the repo root:
**`weekly-funnel-report.md`**. That file is the single source of truth for the
cohort definition, RVF/MQL logic, market/source breakdowns, the spreadsheet
tabs, and the Slack delivery target. Do not improvise or re-derive the logic —
follow the playbook.

## How to run

1. Read `weekly-funnel-report.md` and follow its Steps end to end.
2. Pull the cohort from HubSpot using the **verified** filter:
   `registration_date` in the reporting period **AND** `partner_name` IN
   (`Moonfare`, `Moonfare US`, `Moonfare Private Office`). Market = `territory`.
3. Compute the tables (weekly MQL = cumulative "reached MQL"; market/source MQL =
   current-stage) and post the Slack digest to the channel in the playbook's
   Config table. **Link the source workbook in the post** — the Apps Script
   (`apps-script/Code.gs`) refreshes its `Live …` tabs weekly, so the sheet is
   current. **Claude does not create or write to the Google Sheet itself** — the
   Apps Script owns the refresh.
4. Before posting, sanity-check the anchor: the most recent **full** month's
   total should reconcile to the workbook basis (e.g. May 2026 = 451). Flag
   material differences rather than posting silently.

## Notes
- Delivery is **Slack-only** (no email connector). Channel is set in the playbook
  Config table (`#funnel-and-mql-weekly-update`). It's a **private** channel, so the
  Claude Slack app must be a member or posting will fail.
- Heavy data pulls: it's fine to use a sub-agent to pull/compute, but you post the
  final digest yourself after the anchor check.
- This is also what the scheduled Sunday 20:00 CET routine runs — keep the
  playbook and this skill in sync.
