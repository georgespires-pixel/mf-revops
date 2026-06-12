# Weekly Funnel & MQL Report — Run Playbook

> This file is the **prompt** a scheduled Claude Code (web) session runs every
> Sunday at **20:00 Europe/Berlin (CET/CEST)**. It rebuilds the funnel/MQL
> figures live from HubSpot and delivers a digest. It mirrors the methodology
> documented in the source workbook **"Funnel and MQLs"**
> (`docs.google.com/spreadsheets/d/1wkIIX66eDL5h24820dVgyZSIL8TWc-KuwGdH1bQWcQM`).

## Goal

Produce a weekly snapshot of the marketing funnel from the HubSpot CRM and
send it as a digest (Slack and/or email). Replace the manual "HubSpot CRM
export, pulled <date>" step that the workbook relies on today.

## Delivery

- **Format:** digest (not a full workbook rebuild).
- **Destinations:** see `## Config` below.
- **Subject / title:** `Weekly Funnel & MQL — w/c <Monday of the reporting week> (pulled <run date>)`
- Always link back to the live workbook so detail tabs remain available.

## Config (edit these)

| Setting | Value |
| --- | --- |
| Email recipient(s) | `georges.pires@moonfare.com` |
| Slack channel | _(unset — fill in a channel name/ID to enable, e.g. `#revops`)_ |
| Source workbook | `1wkIIX66eDL5h24820dVgyZSIL8TWc-KuwGdH1bQWcQM` |
| HubSpot timezone | `Europe/Berlin` (account default — confirmed) |
| Lookback window | Current + previous 2 full months, plus current partial month/week |

## Definitions (must match the workbook Methodology tab)

### Markets (Territory)
`US`, `UK`, `DACH`, `BeNeLux`, `APAC`, `ROW`, `Israel`. These come from the
contact's **Territory** property. At runtime, discover the exact property:
search contact properties for `territory` / `market` and confirm the enum
labels match the seven markets above before grouping. `country` (Country of
Residence) is the fallback and is also needed for the D2I rule below.

### Original Source
Group by contact property **`hs_analytics_source`** (label "Original Source").
Map HubSpot enum values to the workbook's labels: Direct Traffic, Offline
Sources, Organic Search, Paid Search, AI Referrals, Email Marketing, Organic
Social, Other Campaigns, Referrals, Paid Social.

### Lifecycle stages (`lifecyclestage`) — verified enum values
| Workbook stage | HubSpot value |
| --- | --- |
| Registration | any contact (all registered contacts) |
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
Snapshot of contacts whose **current** lifecycle stage = `marketingqualifiedlead`.
(Contacts who progressed to SQL/Investor are counted in those later stages.)

### Calculated fields
- `Δ (M-A)` = May minus April (full months only — never the partial month).
- `RVF%` = RVF ÷ Registrations for that month/week (blank when registrations = 0).
- `MQL%` (weekly) = MQL ÷ Registrations.
- The newest month and the first/last weeks are **partial** — label with `*` and
  read directionally, not as final.

## Steps

1. **Resolve dates.** Determine the run date (Europe/Berlin). Reporting periods:
   the two most recent *complete* calendar months, plus the current *partial*
   month, plus the trailing ~11 weeks for the weekly trend (by registration week,
   weeks commencing Monday). Mark partial periods with `*`.
2. **Discover/confirm properties.** Confirm the Territory property name and the
   `hs_analytics_source` enum labels (use `search_properties` / `get_properties`).
   Confirm the Suitability-status and Investor-Type property names the same way
   (search keywords like `suitability`, `investor_type`).
3. **Pull contacts** with `search_crm_objects` on `contacts`, paginating fully
   (check the `total` count — do not stop at one page). Pull the properties:
   `lifecyclestage`, `hs_analytics_source`, `country`, Territory, registration
   date, suitability status, investor type, `your_goals_with_moonfare`,
   `d2i_estimated_financial_portfolio_size`. Use the contact's registration date
   to bucket into month/week.
4. **Compute** the tables, applying the definitions above:
   - Funnel by Market (Reg / RVF / RVF% / MQL, per month + Δ M-A + partial month).
   - Funnel by Original Source (same columns).
   - Weekly trend: Reg / RVF / MQL / RVF% / MQL% by registration week.
   - Funnel cascade totals (Registration → Pre-Qualified → MQL → SQL → Investor).
   - Reconcile: market subtotals must sum to the grand total.
5. **Sanity-check** against last week if a prior run's numbers are available
   (e.g. previous digest). Flag any week-over-week swing that looks like a data
   issue rather than a real movement.
6. **Build the digest** (see format below).
7. **Deliver** to the configured destinations. If a Slack channel is set, post
   there; always email the recipient(s). Include the workbook link.
8. **Do not** publish anything outside the configured destinations.

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
