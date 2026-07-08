# Apps Script — weekly in-place refresh of the Funnel & MQLs workbook

`Code.gs` pulls the registration cohort from HubSpot and rebuilds the funnel /
MQL data tabs in the workbook **on a weekly schedule, independent of Claude**.

**Target workbook:** _Automated Funnel and MQLs report_
`1H8knKk8RnXTT22CC_tragza__IoRjkcxEEGmBxJbhXw`

It writes to tabs prefixed **`Live `** so it never overwrites the curated
source tabs, and it re-applies the workbook's own colour scheme on every run:

| Tab written | Mirrors curated tab |
|---|---|
| `Live Funnel by Market` | 1. Funnel by Market |
| `Live Funnel by Source` | 2. Funnel by Source |
| `Live Market x Source` | 3. Market x Source |
| `Live Funnel - Key Paid+Owned` | 4. Funnel - Key Paid+Owned |
| `Live Weekly Trend` | 5. Weekly Trend |
| `Live Lifecycle by Month` | A. Lifecycle by Month |
| `Live Why PQLs are stuck` | B. Why PQLs are stuck |
| `Live MQL statistics` | C. MQL statistics |
| `Live Methodology` | 6 / D. Methodology |

## Colour scheme (matches the curated tabs)
- Title `#1F3864` bold · source line `#C0504D` · caveats `#595959` (grey italic)
- Header row: navy `#1F3864` fill, white bold text
- **Partial period** (current month / first & last week): peach `#FCE4D6`
- **Total / subtotal** rows: light blue `#D9E1F2` bold · group headers: grey `#F2F2F2`

## History grows automatically
Each run recomputes **every month from the anchor (`HISTORY_START`, default
`2026-04-01`) to the current month**, and **every ISO week** in that range, so a
new month column (and weekly row) appears on its own as time moves forward — no
manual column adds. The current month and the first/last weeks are partial and
highlighted. In the wide monthly tabs, `Δ` compares the latest full month to the
prior full month and sits just before the partial current month.

Registration cohorts are stable; RVF / MQL / lifecycle are point-in-time and
mature as contacts progress (this matches how the workbook has always been
rebuilt from the latest export).

## Logic (mirrors `../weekly-funnel-report.md` + the Methodology tabs)
Cohort = `registration_date` in the window **AND** `partner_name` in
{Moonfare, Moonfare US, Moonfare Private Office}. Market = `territory`; source =
`hs_analytics_source`. RVF uses the 19-May D2I split. Weekly MQL = cumulative
"reached MQL". Cascade = cumulative reached-at-least (off-path excluded).

**HubSpot properties pulled** (all verified against the live account):
`registration_date`, `partner_name`, `territory`, `lifecyclestage`,
`hs_analytics_source`, `country`, `suitability_status`, `investor_type`,
`your_goals_with_moonfare`, `d2i_estimated_financial_portfolio_size`,
`completed_suitability_questionnaire_date`, `id_verified`.

The last two power the new analysis tabs: `completed_suitability_questionnaire_date`
→ suitability lag / questionnaire-completion stats (tabs B, C); `id_verified`
→ the ID-verification line on tab B.

## One-time setup

1. **HubSpot private app token**
   - HubSpot → Settings → Integrations → **Private Apps** → Create a private app.
   - Scope: **`crm.objects.contacts.read`**. Copy the access token.

2. **Add the script to the workbook**
   - Open _Automated Funnel and MQLs report_ → **Extensions → Apps Script**.
   - Paste the contents of `Code.gs` into the editor and save.
   - **Project Settings → Time zone:** set to **Europe/Berlin**.

3. **Script properties** (**Project Settings → Script properties → Add**)
   - `HUBSPOT_TOKEN` = the private-app token. *(required)*
   - `SPREADSHEET_ID` = the workbook ID. *(optional — only needed if you run the
     script standalone rather than bound to the sheet. When bound it uses the
     active spreadsheet; otherwise it falls back to the hardcoded target above.)*
   - `HISTORY_START` = `YYYY-MM-01`. *(optional — move the history anchor. Default
     `2026-04-01`.)*

4. **Authorize + test**
   - In the editor, select `runWeeklyFunnelReport` → **Run**. Approve the scopes
     (external requests + spreadsheet access) on first run.
   - Check the `Live …` tabs populate and styling matches the curated tabs.

5. **Schedule it**
   - Run `createWeeklyTrigger` once → installs a weekly trigger for **Sunday 19:45**
     (project timezone). Verify under **Triggers** (clock icon).

## Notes
- **Reconciliation:** the most recent **full** month should tie to the curated
  workbook (e.g. May 2026 = 451 registrations). The current month and the latest
  week are partial. If a full month drifts, check property values in HubSpot
  before trusting the delta.
- To write into the **curated** tabs (exact cell ranges) instead of `Live ` tabs,
  tell the maintainer the target tab + start cell per table and `buildTab_` can be
  pointed at a range.
- Slack delivery is handled separately by the Claude routine / `weekly-funnel-report`
  skill. This script only refreshes the spreadsheet.
