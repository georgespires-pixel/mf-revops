# revops-os — BD CRM Screening (Node.js)

Node.js implementation of Moonfare's BD CRM Screening automation. The canonical
playbook is [`../crm-screening.md`](../crm-screening.md) (single source of truth
for the rubric, property mapping, and write path); this is a self-contained Node
port of it, parallel to the Python tool in [`../scripts/`](../scripts/). Screens
pre-qualified leads (PQLs) in HubSpot: **Pass A** enriches + scores each lead
against the rubric and posts Qualify/Skip proposals to Slack for human approval;
**Pass B** applies approved decisions to HubSpot. Phase 1 = human-approved
copilot. Phase 2 (auto-qualify) is gated OFF.

## Requirements
- Node 18+ (uses global `fetch`). No dependencies.
- Env: `HUBSPOT_BD_WRITE_TOKEN` (HubSpot private-app token). Optional:
  `SLACK_BOT_TOKEN`, `SLACK_CHANNEL`, `QUEUE_CAP`, `ALLOW_PROD=1`.

## Commands
```bash
node crm-screening.mjs whoami                       # confirm sandbox vs prod
node crm-screening.mjs props leads --grep business  # discover Lead property names
node crm-screening.mjs pass-a --cap 25              # propose (dry-run Slack if no token)
node crm-screening.mjs qualify --contact-id ID           # Pass B dry-run
node crm-screening.mjs qualify --contact-id ID --apply   # Pass B write + verify
```

After `props leads`, copy `lead_props.json.example` -> `lead_props.json` and fill
in the confirmed internal names + enum values.

## Safety rails
- Writes refuse on non-sandbox portals unless `ALLOW_PROD=1`.
- `qualify` is dry-run unless `--apply`; refuses to write Lead fields with
  unconfirmed names (`lead_props.json` missing).
- Owner is never set — the native HubSpot by-country workflow assigns it.
- The token is read from env only; never commit it.

## The rubric scorer
`scoreLead()` ships a transparent **heuristic** stand-in for the real LLM
judgement so the pipeline runs end-to-end offline. Wire a model by assigning
`LLM_SCORER` (async `(lead, enrichment) => <same output shape>`). Enrichment is
the HubSpot record + an optional `WEB_SEARCH` hook — **no LinkedIn scraping**.

## IMPORTANT — network egress
Direct calls to `api.hubapi.com` require outbound network access. In a Claude
Code **web** session the environment's network policy must include
`api.hubapi.com` in its **allowed domains**, or every HubSpot REST call returns a
`403 CONNECT policy denial`. Running locally (your Mac) has no such restriction.

The script is **proxy-aware**: Node's built-in `fetch` ignores `HTTPS_PROXY`, so
inside a Claude cloud session it would be blocked even with the domain allowed.
This script routes HTTPS through `HTTPS_PROXY` via a manual CONNECT tunnel
(dependency-free) when the var is set, and connects directly otherwise. No
configuration needed either way.

## The qualify action moves BOTH objects
The Contact lifecycle and the Lead pipeline stage are independent in HubSpot
(neither cascades to the other). So `qualify` sets **both**: Contact
`lifecyclestage → marketingqualifiedlead` (funnel/MQL reporting) **and** Lead
`hs_pipeline_stage →` the "Marketing Qualified Lead" stage (so Sales sees it in
the Lead pipeline). The MQL stage id lives in `lead_props.json` — re-confirm it
per portal.
