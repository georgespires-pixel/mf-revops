# Weekly Funnel & MQL Report — Run Playbook

> This file is the **prompt** a scheduled Claude Code (web) session runs every
> Sunday at **20:00 Europe/Berlin (CET/CEST)**. It rebuilds the funnel/MQL
> figures live from HubSpot and delivers a digest. It mirrors the methodology
> documented in the source workbook **"Funnel and MQLs"**
> (`docs.google.com/spreadsheets/d/1wkIIX66eDL5h24820dVgyZSIL8TWc-KuwGdH1bQWcQM`).

## Goal

Produce a weekly snapshot of the marketing funnel from the HubSpot CRM and
post it as a Slack digest. Replace the manual "HubSpot CRM export, pulled
<date>" step that the workbook relies on today.

## Delivery

- **Format:** a Slack digest (headline + key tables) **plus** a workbook-style
  Google Sheet with the full detail, linked from the digest.
- **Destination:** Slack channel (see `## Config` below).
- **Spreadsheet:** build a multi-tab sheet mirroring the source workbook — tabs:
  `Funnel by Market`, `Funnel by Source`, `Funnel cascade`, `Weekly Trend`,
  `Methodology`. Upload to Drive (or update the same file each week) and put the
  link in the Slack post.
- **Subject / title:** `Weekly Funnel & MQL — w/c <Monday of the reporting week> (pulled <run date>)`
- Always link back to the live workbook so detail tabs remain available.

## Config (edit these)

| Setting | Value |
| --- | --- |
| Slack channel | `#test-claude` (testing — switch to the production channel when validated) |
| Source workbook | `1wkIIX66eDL5h24820dVgyZSIL8TWc-KuwGdH1bQWcQM` |
| HubSpot timezone | `Europe/Berlin` (account default — confirmed) |
| Lookback window | Current + previous 2 full months, plus current partial month/week |

## Definitions (must match the workbook Methodology tab)

### Registration cohort (VERIFIED — this defines the universe)
A "registration" = a contact where **both**:
- `registration_date` falls within the reporting period (this is the cohort key,
  **not** `createdate`), AND
- `partner_name` is one of **`Moonfare`**, **`Moonfare US`**, **`Moonfare Private
  Office`** (Moonfare-direct only; excludes partner/offline/imported contacts).

Verified against HubSpot: this reproduces the workbook exactly — May 2026 = 451
(workbook 451). (Apr = 435 vs 436 and Jun 1–8 = 144 vs 123 differ only because
live data has moved since the 08-Jun manual snapshot.) Bucket each contact into
month/week by `registration_date` (weeks commence Monday).

### Markets (Territory)
`US`, `UK`, `DACH`, `BeNeLux`, `APAC`, `ROW`, `Israel`, from the contact's
**`territory`** property (verified internal name). `country` (Country of
Residence) is still needed for the D2I RVF rule below.

### Original Source
Group by contact property **`hs_analytics_source`** (label "Original Source").
Map HubSpot enum values to the workbook's labels: Direct Traffic, Offline
Sources, Organic Search, Paid Search, AI Referrals, Email Marketing, Organic
Social, Other Campaigns, Referrals, Paid Social.

### Lifecycle stages (`lifecyclestage`) — verified enum values
| Workbook stage | HubSpot value |
| --- | --- |
| Registration | any contact in the verified cohort above (any lifecycle stage, incl. off-path) |
| Pre-Qualified (PQL) | `lead` |
| Marketing Qualified Lead (MQL) | `marketingqualifiedlead` |
| Sales Qualified Lead (SQL) | `salesqualifiedlead` |
| Investor | `customer` (also `161472561` Repeat, `161472562` Churned for "ever reached") |
| Off-path (exclude from "reached") | `947030451` Disqualified, `1048775831` Unresponsive, `51503126` Prospect |

**Funnel cascade** uses cumulative "reached at least" logic: each stage counts
contacts whose current lifecycle stage is that stage **or further along** (order:
Registration → Pre-Qualified → MQL → SQL → Investor). Disqualified, Prospect and
Unresponsive are off-path and excluded; do **not** back-fill prior stages for them.

### RVF — Ready to View Funds (two date regimes, split at D2I rollout 19 May 2026)
- **UK Territory (any registration date):** Suitability = "Verified" AND Investor
  Type in {gb-certified-high-net-worth, gb-self-certified-sophisticated,
  gb-invest-on-behalf-entity, uk-hnw-company-or-association,
  UK - Self-Certified Sophisticated} (case-insensitive).
- **Registration BEFORE 19 May 2026, non-UK:** Suitability = "Pending" OR "Verified".
- **Registration ON/AFTER 19 May 2026, D2I markets** (Country in: Spain, Finland,
  Norway, Liechtenstein, Czech Republic, Denmark, Sweden, Ireland, Portugal,
  Luxembourg, Greece): `your_goals_with_moonfare` known OR
  `d2i_estimated_financial_portfolio_size` known.
- **Registration ON/AFTER 19 May 2026, all other territories:** Suitability =
  "Pending" OR "Verified".
- Note: D2I markets sit within ROW (Luxembourg within BeNeLux); none under UK.

### MQL
- **By-Market / By-Source tables:** MQL = contacts whose **current** lifecycle
  stage = `marketingqualifiedlead` (point-in-time snapshot; matches the workbook).
- **Weekly-trend table:** MQL = **cumulative "reached MQL"** — current stage is
  MQL **or beyond** (MQL + SQL + Investor). This avoids the snapshot understating
  recent weeks where fast movers have already progressed past MQL. (Contacts who
  progressed to SQL/Investor are still counted here as having reached MQL.)

### Calculated fields
- `Δ (M-A)` = May minus April (full months only — never the partial month).
- `RVF%` = RVF ÷ Registrations for that month/week (blank when registrations = 0).
- `MQL%` (weekly) = reached-MQL ÷ Registrations (uses the cumulative weekly MQL above).
- The newest month and the first/last weeks are **partial** — label with `*` and
  read directionally, not as final.

## Steps

1. **Resolve dates.** Determine the run date (Europe/Berlin). Reporting periods:
   the two most recent *complete* calendar months, plus the current *partial*
   month, plus the trailing ~11 weeks for the weekly trend (by registration week,
   weeks commencing Monday). Mark partial periods with `*`.
2. **Confirm properties.** Verified internal names: `registration_date`,
   `partner_name`, `territory`, `lifecyclestage`, `hs_analytics_source`,
   `country`, `your_goals_with_moonfare`, `d2i_estimated_financial_portfolio_size`.
   Still confirm the Suitability-status and Investor-Type property names at
   runtime (search keywords `suitability`, `investor_type`).
3. **Pull the cohort** with `search_crm_objects` on `contacts`, filtered to
   `registration_date` in the period **AND** `partner_name` IN
   (`Moonfare`, `Moonfare US`, `Moonfare Private Office`). Paginate fully (check
   `total` — do not stop at one page). Pull: `registration_date`, `partner_name`,
   `territory`, `lifecyclestage`, `hs_analytics_source`, `country`, suitability
   status, investor type, `your_goals_with_moonfare`,
   `d2i_estimated_financial_portfolio_size`. Bucket by `registration_date`.
4. **Compute** the tables, applying the definitions above:
   - Funnel by Market (Reg / RVF / RVF% / MQL, per month + Δ M-A + partial month).
   - Funnel by Original Source (same columns).
   - Weekly trend: Reg / RVF / MQL(cumulative reached ≥MQL) / RVF% / MQL% by registration week.
   - Funnel cascade totals (Registration → Pre-Qualified → MQL → SQL → Investor).
   - Reconcile: market subtotals must sum to the grand total.
5. **Sanity-check** against last week if a prior run's numbers are available
   (e.g. previous digest). Flag any week-over-week swing that looks like a data
   issue rather than a real movement.
6. **Build the digest** (see format below) **and the spreadsheet** (tabs listed
   under Delivery). Upload the sheet to Drive and get a shareable link.
7. **Deliver** by posting the digest to the configured Slack channel, including
   the link to this week's spreadsheet and to the source workbook.
8. **Do not** publish anything outside the configured Slack channel.

## Digest format

```
Weekly Funnel & MQL — w/c <Mon DD> (pulled <DD Mon YYYY>)

HEADLINE
<2–4 sentences: biggest WoW / MoM movements, partial-period caveat, one action.>

FUNNEL (last 2 full months + partial)
Stage           <M1>   <M2>   <M3*>   Δ M-A
Registrations    ...
Pre-Qualified    ...
MQL              ...
SQL              ...
Investor         ...

BY MARKET (Reg / RVF% / MQL, <M2> vs <M1>)
US     ...
UK     ...
... (seven markets) ...

WEEKLY TREND (Reg / RVF / MQL)
w/c <date> ...   (trailing ~8 weeks; mark partial weeks *)

Full detail: <workbook link>
```

## Notes / caveats to carry into the digest
- RVF and MQL are defined independently — not a strictly nested cascade.
- Lifecycle stage is a point-in-time snapshot.
- Newest month + boundary weeks are partial; never present them as final.
