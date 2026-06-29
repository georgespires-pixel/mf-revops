# mf-revops — Weekly RevOps Automations

This repo hosts the scheduled **RevOps weekly reporting routines**. Each is a
self-contained playbook a scheduled Claude Code session runs against live tools
(HubSpot / Jira) and delivers to Slack.

| Routine | Source | Delivers to | Skill |
|---|---|---|---|
| **Funnel & MQL** | HubSpot | `#funnel-and-mql-weekly-update` | [`weekly-funnel-report.md`](./weekly-funnel-report.md) |
| **HelpCenter (COHC) tickets** | Jira (COHC board) | `#team-rev-ops` | [`.claude/skills/revops-helpcenter-weekly/SKILL.md`](./.claude/skills/revops-helpcenter-weekly/SKILL.md) |

See [HelpCenter setup](#helpcenter-revops-ticket-report) below for the second routine.

---

## Funnel & MQL report

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

---

## HelpCenter RevOps ticket report

Automates the weekly **Rev Ops HelpCenter (COHC)** open-ticket report — total
open tickets, department breakdown, ticket-type split, a Sales drill-down,
top-priority Sales tickets with their latest status, and the open Sales bugs
listed individually — each with week-over-week deltas.

- **What runs:** [`.claude/skills/revops-helpcenter-weekly/SKILL.md`](./.claude/skills/revops-helpcenter-weekly/SKILL.md)
  — a self-contained playbook a scheduled Claude Code session executes against the
  Jira **COHC** board.
- **Delivery:** text report to Slack `#team-rev-ops`, with two thread replies — a
  machine-readable `SNAPSHOT:` line (the hidden state next week's deltas read back)
  and a latest-status update on top-priority tickets. The full visual report
  (real pie chart) renders inline in Claude.
- **Schedule:** weekly. Suggested **Monday 09:00 Europe/Berlin** (start-of-week
  backlog review) — adjust to taste when creating the trigger.

### How it works

1. A **scheduled trigger** in Claude Code on the web starts a session weekly,
   pointed at this repo, with the prompt
   `Run the revops-helpcenter-weekly skill and post the report.`
2. The session reads the COHC board via the **Atlassian (Jira)** MCP, computes the
   metrics, reads last week's `SNAPSHOT:` reply from Slack for deltas, renders the
   visual inline, and posts the report to `#team-rev-ops` via the **Slack** MCP.
3. The skill carries its own hardcoded constants (cloudId, project key, field IDs,
   channel id) so it does not rediscover them each run.

### Setting up the schedule (one-time, in the web UI)

1. Open this repo's environment in Claude Code on the web.
2. Create a **scheduled trigger**:
   - **Cadence:** weekly (suggested Monday 09:00, timezone **Europe/Berlin**).
   - **Prompt:** `Run the revops-helpcenter-weekly skill and post the report.`
3. Ensure the environment has the **Atlassian** and **Slack** MCP connectors
   enabled (read access to the COHC Jira board; send access to post to
   `#team-rev-ops`, and the Claude Slack app must be a member of the channel).

### Verified Jira mapping

| Concept | Jira value |
| --- | --- |
| Atlassian cloudId | `7dbeed77-addb-4cd2-8177-120c310c1db9` |
| Project | `COHC` ("Rev Ops Helpcenter") |
| Slack channel | `#team-rev-ops` (`C0877V4P09L`) |
| "Open" definition | `status NOT IN (Declined, Done)` |
| Department | `customfield_10354` (null → "Unassigned") |
| Sales option | value `Sales`, option id `10689` |
| Bug-topic field | `customfield_12297` — **ignored** (constant `"Bug"`, doesn't segment) |

Validated against the live board (52 open tickets, single page) when the skill was
added — the JQL query and all constants resolve correctly.
