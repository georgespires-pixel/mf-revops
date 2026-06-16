# Apps Script — weekly in-place refresh of the Funnel & MQLs workbook

`Code.gs` pulls the registration cohort from HubSpot and refreshes data tabs in
the workbook **on a weekly schedule, independent of Claude**. It writes to tabs
prefixed **`Live `** (`Live Funnel by Market`, `Live Funnel by Source`,
`Live Funnel Cascade`, `Live Weekly Trend`, `Live Methodology`) so it never
overwrites the curated/formatted source tabs.

It applies the same logic as the playbook (`../weekly-funnel-report.md`): cohort =
`registration_date` in a rolling 3-month window AND `partner_name` in
{Moonfare, Moonfare US, Moonfare Private Office}; market = `territory`; the RVF
19-May D2I split; weekly MQL = cumulative "reached MQL".

## One-time setup

1. **HubSpot private app token**
   - HubSpot → Settings → Integrations → **Private Apps** → Create a private app.
   - Scope: **`crm.objects.contacts.read`**.
   - Copy the access token.

2. **Add the script to the workbook**
   - Open the **Funnel and MQLs** Google Sheet → **Extensions → Apps Script**.
   - Paste the contents of `Code.gs` into the editor and save.
   - **Project Settings → Time zone:** set to **Europe/Berlin**.

3. **Store the token**
   - Apps Script → **Project Settings → Script properties → Add**:
     - `HUBSPOT_TOKEN` = the private-app token.
     - (Optional) `SPREADSHEET_ID` = the workbook ID — only needed if you run the
       script **standalone** rather than bound to the sheet.

4. **Authorize + test**
   - In the editor, select `runWeeklyFunnelReport` → **Run**. Approve the scopes
     (external requests + spreadsheet access) on first run.
   - Check the new `Live …` tabs populate and `Live Methodology` shows the count.

5. **Schedule it**
   - Run `createWeeklyTrigger` once → installs a weekly trigger for **Sunday 19:45**
     (project timezone). Verify under **Triggers** (clock icon).

## Notes
- Reconciliation: the most recent **full** month should tie to the workbook basis
  (e.g. May 2026 = 451). The current month and the latest week are partial.
- To write into the **existing** formatted tabs (exact cell ranges) instead of the
  `Live ` tabs, tell the maintainer the target tab name + start cell per table and
  `writeTab_` can be pointed at a range.
- Slack delivery is handled separately by the Claude routine / `/weekly-funnel-report`
  skill. This script only refreshes the spreadsheet. (A Slack webhook post could be
  added here later if you want the script to own both.)
