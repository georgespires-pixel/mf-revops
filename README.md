# mf-revops — Weekly Funnel & MQL Automation

Automates the **"Funnel and MQLs"** report so it lands every **Sunday evening**
instead of being hand-built from a manual HubSpot export.

- **Report (source workbook):** [Funnel and MQLs](https://docs.google.com/spreadsheets/d/1wkIIX66eDL5h24820dVgyZSIL8TWc-KuwGdH1bQWcQM/edit)
- **What runs:** [`weekly-funnel-report.md`](./weekly-funnel-report.md) — the playbook a
  scheduled Claude Code session executes against HubSpot.
- **Delivery:** Slack digest to `#funnel-and-mql-weekly-update` (no workbook link — the source sheet isn't auto-updated).
- **Schedule:** Sunday **20:00 Europe/Berlin** (the HubSpot account timezone).

## How it works

1. A **scheduled trigger** in Claude Code on the web starts a session every
   Sunday at 20:00 CET, pointed at this repo.
2. The session runs the `weekly-funnel-report.md` playbook: it pulls fresh
   contact data from HubSpot via the HubSpot MCP, recomputes the funnel / RVF /
   MQL tables using the same definitions as the workbook's Methodology tab, and
   sends the digest.
3. The detailed multi-tab workbook stays as the system of record; the digest
   links to it.

We chose a scheduled Claude session (over a HubSpot native report or a Google
Apps Script) because the report's logic is bespoke — the 19 May D2I RVF regime
split, the "reached at least" lifecycle cascade, the market/source breakdowns —
and native tools can't reproduce it faithfully.

## Setting up the schedule (one-time, in the web UI)

The trigger itself is configured in **Claude Code on the web**, not in code:

1. Open this repo's environment in Claude Code on the web.
2. Create a **scheduled trigger**:
   - **Cadence:** weekly, Sunday, 20:00, timezone **Europe/Berlin**.
   - **Prompt:** `Run the playbook in weekly-funnel-report.md and deliver the digest.`
3. Ensure the environment has the **HubSpot** and **Slack** MCP connectors
   enabled (read access to HubSpot contacts; send access to post the digest).

Docs: https://code.claude.com/docs/en/claude-code-on-the-web

## Configuration

The Slack channel and the lookback window live in the **Config** table in
[`weekly-funnel-report.md`](./weekly-funnel-report.md). Edit there:

- Slack channel — `#funnel-and-mql-weekly-update` (private; the Claude Slack app
  must be invited to the channel to post).

## Verified HubSpot mapping

| Concept | HubSpot property / value |
| --- | --- |
| Original Source | `hs_analytics_source` |
| Country (D2I rule) | `country` |
| Lifecycle: Pre-Qualified | `lifecyclestage = lead` |
| Lifecycle: MQL | `lifecyclestage = marketingqualifiedlead` |
| Lifecycle: SQL | `lifecyclestage = salesqualifiedlead` |
| Lifecycle: Investor | `lifecyclestage = customer` |
| Off-path (excluded) | Disqualified, Unresponsive, Prospect |
| D2I goals / portfolio | `your_goals_with_moonfare`, `d2i_estimated_financial_portfolio_size` |

Territory, Suitability status and Investor Type property names are confirmed at
runtime by the playbook (step 2) before grouping.
