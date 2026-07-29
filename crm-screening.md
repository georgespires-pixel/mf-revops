# BD CRM Screening — Run Playbook

> This file is the **prompt** a Claude Code (web) session runs to screen
> pre-qualified leads (PQLs) in HubSpot. It automates the daily **Business
> Development CRM Screening** workflow that Yijia runs by hand (~3 hrs/day,
> ~66 hrs/month). It mirrors the BPMN process `Process_1` (Review → enrich →
> qualify/skip → write back to HubSpot).
>
> **Phase 1 (this version): screening copilot — human-approved.** Claude enriches
> each lead, scores it against the rubric, and posts a Qualify/Skip proposal to
> Slack. A human approves; Claude then executes the HubSpot updates. Phase 2
> (auto-qualify high-confidence leads) is documented at the end and is gated OFF
> until the rubric is trusted.

## Goal

Replace the manual, tool-jumping screening loop (HubSpot ↔ LinkedIn ↔ Google ↔
HubSpot, 4 separate field updates per lead) with:
1. **Consistent** qualification against a written rubric (removes the "no rubric,
   varies by energy/time pressure" pain point).
2. **One** qualify action instead of four manual field edits.
3. **Faster** time-to-contact — runs the queue on a schedule (or per-PQL event),
   not gated on one person's morning.
4. A **human approval gate** so judgement calls stay supervised in Phase 1.

## Pipeline at a glance (maps to the BPMN)

| BPMN step | Playbook handling |
| --- | --- |
| `StartEvent_1` PQL in HubSpot | Pull the PQL queue (Step 2) |
| `Task_1` Review contact (prioritise high BD score + questionnaire) | Sort the queue (Step 3) |
| `Task_2` LinkedIn Sales Nav | **Enrichment provider** (Step 4) — pluggable; see Enrichment |
| `Gateway_1/2` Good info to qualify? | Rubric score + confidence (Step 5) |
| `Task_3` Google search (fallback) | Web-search fallback inside enrichment (Step 4) |
| `Task_4–7` MQL / owner / BD=Yes / Lead Type | **One** qualify action (Step 7), human-approved |
| `Task_5` Assign owner by country | Left to the existing native HubSpot workflow — do NOT set owner here |
| `Task_8` Skip / Do not qualify | Recorded with reason (Step 7) |
| `EndEvent_1` Next contact | Loop |

## Config (edit these)

| Setting | Value |
| --- | --- |
| Slack channel (approval queue) | `test-claude` (interim test channel; move to a dedicated BD channel for production) |
| Run cadence | Daily, weekday mornings (Phase 1). Upgrade path: per-PQL event trigger. |
| Queue size cap per run | `25` leads (tune to volume) |
| Auto-qualify (Phase 2) | **OFF** in Phase 1 |
| Auto-qualify rule (Phase 2) | `qualification = MQL` AND `confidence = high` AND `score ≥ 85` (not used until Phase 2 is enabled) |
| HubSpot timezone | `Europe/Berlin` (account default) |

## HubSpot property mapping

**Verified** (from the funnel report, same HubSpot account):

| Concept | Property / value |
| --- | --- |
| Lifecycle: Pre-Qualified (PQL) | `lifecyclestage = lead` |
| Lifecycle: MQL (qualify target) | `lifecyclestage = marketingqualifiedlead` |
| Country of residence | `country` |
| Questionnaire signals | `your_goals_with_moonfare`, `d2i_estimated_financial_portfolio_size` |

**BD score (prioritisation) — CONFIRMED:** use the native **`hubspotscore`**
("HubSpot Score" — sales-readiness). Sort the queue by it, descending.

**Qualify-action write targets — the fields span TWO objects, and the current
HubSpot MCP connector is READ-ONLY for the CRM (no create/update tool):**

| Field to set | Object | Read via MCP? | Write via MCP? |
| --- | --- | --- | --- |
| Lead stage → MQL (`lifecyclestage = marketingqualifiedlead`) | **Contact** | ✅ yes | ❌ no (connector is read-only) |
| Contact Owner (by country) | **Contact** | ✅ yes | n/a — native HubSpot workflow assigns it; do NOT set here |
| Business Development → `Yes` | **Lead** (HubSpot Leads object, `0-136`) | ❌ no (object unsupported) | ❌ no |
| Lead type → `New Business` | **Lead** (HubSpot Leads object, `0-136`) | ❌ no (object unsupported) | ❌ no |

> **CONSTRAINT (verified 2026-06-29).** Two stacked limits on the connected
> HubSpot MCP:
> 1. **Read-only CRM** — the connector exposes only read tools (`search_crm_objects`,
>    `get_crm_objects`, `query_crm_data`, `get_properties`); there is **no
>    create/update CRM tool**. So even the **contact** `lifecyclestage` cannot be
>    written through the MCP.
> 2. **Leads object unsupported** — `business_development`, `lead_type`,
>    `lead_label`, `is_target_account` are not on `contacts` (returned not-found);
>    they live on the **Leads object**, which the MCP cannot even read (`leads`
>    and `0-136` both return "object type not supported").
>
> Net: **Pass B cannot write any field through this MCP.** A write-capable path is
> required regardless of object.
>
> **Resolution (pick one — see "Pass B write path" below):**
> 1. **Private-app token + REST (recommended).** Admin creates a HubSpot private
>    app with contacts + `crm.objects.leads` read/write scopes; the screening
>    session writes all fields directly via REST (mirrors `apps-script/Code.gs`).
>    Self-contained, covers both objects. Claude holds a scoped token.
> 2. **n8n owns the write-back.** Claude enriches/scores/gets approval; n8n's
>    HubSpot node writes both objects. Two platforms to maintain.
> 3. **(Optional complement) HubSpot workflow fan-out.** A native workflow can set
>    the Lead-object fields + owner once a single contact trigger is set — but
>    setting that trigger still needs a write, so this only *reduces* what path 1/2
>    must write; it is not a standalone solution.
>
> Until a write path is set up, Pass A (enrich + score + Slack proposal) runs
> fully, but Pass B performs **no** HubSpot writes — it reports proposed changes in
> the Slack thread only.

### Pass B write path — private-app token + REST (chosen)

One-time admin setup (HubSpot → Settings → Integrations → **Private Apps** →
Create), then store the token as `HUBSPOT_BD_WRITE_TOKEN` in the session env
(never commit it). **Scopes:**
- `crm.objects.contacts.read`, `crm.objects.contacts.write` — set `lifecyclestage`.
- `crm.objects.leads.read`, `crm.objects.leads.write` — set Business Development +
  Lead type on the associated Lead.
- `crm.schemas.contacts.read` — confirm the contact lifecycle enum. (The Lead
  property list is readable with `crm.objects.leads.read`; there is no separate
  "leads schema" scope. Only add `crm.schemas.custom.read` if `GET
  /crm/v3/properties/leads` returns 403.)

**Confirmed Lead-object mapping (HubSpot SANDBOX portal 50160270, verified
2026-07-21 via `GET /crm/v3/properties/leads`):** the API values differ from the
display labels — confirm again before pointing at prod.

| Concept | Internal name | Type | Value to write (label) |
| --- | --- | --- | --- |
| Business Development | `business_development` | boolean checkbox | `"true"` ("Yes") |
| Lead type | `hs_lead_type` | enum select | `"NEW_BUSINESS"` ("New business") |

REST calls per approved lead (base `https://api.hubapi.com`, bearer token):
1. **Discover Lead-object property names once** (done — see table above):
   `GET /crm/v3/properties/leads`. Note "Business Development" is a *boolean
   checkbox* (`true`/`false`, not the string "Yes") and "Lead type" is the
   standard `hs_lead_type` property (enum value `NEW_BUSINESS`, not a custom
   `lead_type`).
2. **Set contact lifecycle stage:**
   `PATCH /crm/v3/objects/contacts/{contactId}`
   body `{"properties":{"lifecyclestage":"marketingqualifiedlead"}}`.
3. **Find the associated Lead, then set its fields:**
   `GET /crm/v4/objects/contacts/{contactId}/associations/leads` → take the Lead
   id → `PATCH /crm/v3/objects/leads/{leadId}` body
   `{"properties":{"business_development":"true","hs_lead_type":"NEW_BUSINESS"}}`.
4. **Do NOT set owner** — the native by-country workflow fires on the stage change.

Mirror the token handling in `apps-script/Code.gs` (script property, scoped read
there; this app additionally needs write). Verify on **one** lead before batching.

**Implemented in [`scripts/passb_hubspot.py`](scripts/passb_hubspot.py)** (stdlib
REST client, token from env `HUBSPOT_BD_WRITE_TOKEN`). It carries the sandbox-setup
steps (`whoami` to confirm the portal is a sandbox, `props leads` to discover the
internal names/enums, `seed-test` to create a throwaway contact+lead) and the
qualify action itself (`qualify --contact-id <ID>` dry-run; `--apply` writes and
re-reads to verify). Confirmed Lead-object names live in `scripts/lead_props.json`
(template `lead_props.json.example`). Setup + safety rails:
[`scripts/README.md`](scripts/README.md). Writes refuse on non-sandbox portals and
`qualify` is dry-run unless `--apply`.

## Enrichment (pluggable — this is the swappable LinkedIn replacement)

Run providers in order until the rubric has enough signal; record which provider
satisfied each lead.

1. **HubSpot record itself** — questionnaire answers, country, source, existing
   notes. Often already enough; check before spending external calls.
2. **Primary enrichment API (preferred, ToS-clean):** Apollo / People Data Labs /
   Clearbit by email or name+company. **TODO: wire credentials** (MCP or REST).
   Until then this step is skipped and we fall through to web search.
3. **Web search fallback** (`WebSearch` / `linkup.so`) — the BPMN "Google Search"
   step. Search name + company + role; capture role, seniority, firm, and any
   wealth/suitability signal.

> **Not used:** cookie-based LinkedIn automation (e.g. `linkupapi.com`). It
> drives a real Sales Navigator seat, violates LinkedIn ToS, and risks an account
> ban + GDPR exposure for a regulated firm. Keep LinkedIn as an optional *manual*
> check the approver does in Slack, not an automated step.

## Qualification rubric (the decision logic)

> The agent's **role:** evaluate enriched HubSpot contact data (augmented with web
> search) and classify whether the lead should be promoted to MQL. This is the
> explicit, written version of the two "Good info to qualify?" BPMN gateways — the
> point is consistency: every lead judged the same way.
>
> **Context.** BD targets High-Net-Worth and Ultra-High-Net-Worth individuals for
> a wealth/asset-management offering. The ideal client profile is **NOT** limited
> to finance — successful business owners and senior operators across **any**
> industry can qualify, provided there are credible signals of wealth, seniority,
> and decision-making authority.

### Evaluate four dimensions (weigh holistically — no single one disqualifies)

**1. Seniority (weight: HIGH)**
- *Strong:* C-suite (CEO/CFO/COO/CIO/Founder/Co-Founder/Owner/Partner/Managing
  Director/Managing Partner); Head of / Global Head of / President / Vice Chair /
  Chair; 15+ yrs relevant experience; board seats / multiple directorships.
- *Weak:* Associate, Analyst, Coordinator, Assistant, Junior, Intern; <5 yrs
  experience; individual contributor with no leadership scope.

**2. Industry relevance (weight: MEDIUM — do NOT over-index)**
- *Preferred:* PE, VC, Hedge Funds; Investment Banking, Corporate Finance, M&A;
  Law firms (esp. partners at top-tier); Technology (funded/scaled founders &
  senior execs); Family Offices, Wealth Management.
- *Also acceptable (do not penalise):* industrial, manufacturing, real estate,
  energy, healthcare, consumer goods — when the contact is an owner, founder, or
  very senior operator; any sector with signals of significant personal wealth or
  business scale.
- **Rule:** being outside finance is NOT a reason to disqualify. An MD at an
  investment bank and the owner of a mid-market industrial business can both be
  excellent leads.

**3. Company quality (weight: MEDIUM)**
- *Strong:* well-known / tier-1 firm (bulge-bracket bank, top-tier PE/VC, magic
  circle law firm); scaled business (revenue, headcount, funding, press);
  established track record.
- *Weak:* unverifiable company, no digital footprint, dormant; very early-stage
  with no traction and no founder wealth signals.

**4. Wealth / decision-making signals (weight: HIGH)**
- *Strong:* founder/owner equity in a successful business; public mentions of
  exits, acquisitions, fundraising; board seats, investor profiles, philanthropy;
  senior titles at firms where partner/MD-level comp is typical.

### Decision rules
- **MQL** → at least **2 of 4** signals are *strong* AND nothing clearly
  disqualifying. Score typically **≥ 65**.
- **NEEDS_REVIEW** → mixed signals, ambiguous seniority, or thin web-search
  results. Score typically **40–64**. Use this when a human should make the call
  rather than auto-rejecting a potentially good lead.
- **NOT_MQL** → clearly junior with no offsetting wealth/ownership signals, or a
  fabricated/unverifiable profile. Score typically **< 40**.

### Guardrails
- Judge **only** on the input data — do not invent facts.
- If web-search snippets are empty/irrelevant, say so in `missing_information` and
  lean **NEEDS_REVIEW**, not NOT_MQL (protects the "enrichment gaps = lost lead"
  pain point — a thin profile is re-queueable, not a hard reject).
- Do **not** disqualify solely for a non-finance industry — check ownership/wealth
  first.
- Do **not** over-qualify on a prestigious company name alone if the contact's own
  role is junior.

### Per-lead output (the agent returns this object, used to build the Slack proposal)
```json
{
  "qualification": "MQL | NEEDS_REVIEW | NOT_MQL",
  "confidence": "high | medium | low",
  "score": 0,
  "reasoning": "2–4 sentences citing specific evidence",
  "signals": {
    "seniority": "strong | moderate | weak | unclear",
    "industry": "preferred | acceptable | weak | unclear",
    "company_quality": "strong | moderate | weak | unclear",
    "wealth_signals": "strong | moderate | weak | unclear"
  },
  "key_evidence": ["specific fact 1", "specific fact 2"],
  "missing_information": ["what would raise confidence"]
}
```

### How the three classes map to the Slack approval queue (Phase 1)
- **MQL** → proposed action **Qualify** (✅ to confirm).
- **NEEDS_REVIEW** → proposed action **Review** — surfaced prominently for a human
  call (✅ qualifies, ❌ skips).
- **NOT_MQL** → proposed action **Skip** (❌; ✅ overrides to qualify).

In Phase 1 **every** class is human-approved before any HubSpot write. Phase 2
auto-qualifies only `MQL + high confidence + score ≥ 85` (see Config / Phase 2).

## Steps

### Pass A — Propose (build the approval queue)

1. **Confirm properties.** Resolve the CONFIRM-AT-RUNTIME names above. Abort with
   a Slack note if any required write-target can't be confirmed.
2. **Pull the PQL queue.** `search_crm_objects` on `contacts` where
   `lifecyclestage = lead`. Pull the prioritisation + decision fields (BD score,
   questionnaire props, `country`, source, email, name, company). Paginate fully.
3. **Prioritise** (BPMN `Task_1`): sort by BD threshold score desc, then "has
   questionnaire answers". Take the top `N` (queue cap in Config).
4. **Enrich** each lead via the Enrichment ladder above; stop at the first
   provider that gives the rubric enough signal. Record provider + key findings.
5. **Score** each lead against the rubric → Qualify/Skip, confidence, 1–2 line
   reason citing the evidence.
6. **Post the proposal** to the Slack channel. One message per lead (so reactions
   map cleanly), each containing: contact name + HubSpot record link, proposed
   action (Qualify/Skip), confidence, reason, enrichment source. Ask approvers to
   react ✅ to confirm Qualify, ❌ to force Skip, and leave neutral to defer.
   Post a header message summarising the batch (counts, queue size, run time).

### Pass B — Apply (execute approved decisions)

7. **Read approvals** from the Slack reactions. For each ✅ Qualify, perform the
   qualify action via the **Pass B write path** (private-app REST — `scripts/passb_hubspot.py`
   / `node/crm-screening.mjs`; the read-only MCP cannot write either object):
   - **Contact:** `lifecyclestage` → `marketingqualifiedlead`.
   - **Lead object:** `hs_pipeline_stage` → the **"Marketing Qualified Lead"**
     stage id (sandbox `159139484`) so the Lead moves into the MQL column Sales
     works; `business_development` → `"true"` (Business Development = Yes);
     `hs_lead_type` → `"NEW_BUSINESS"` (Lead type = New business).
     *(Confirmed in sandbox; re-confirm the stage id against prod — it can differ.)*
   - **Do NOT set Contact Owner** — the native HubSpot workflow assigns it by
     `country` once the stage changes. (BPMN `Task_5` stays automated.)
   For each ❌ / deferred-as-Skip, record the skip reason but do not change lifecycle.
8. **Confirm** back in the Slack thread: per-lead ✅ applied / ❌ skipped / ⚠️
   errored, plus a one-line batch summary. Never write outside HubSpot + the
   configured Slack channel.

> **Lead pipeline stage — now set directly by Pass B.** Sales works the **Lead
> pipeline board** (`hs_pipeline_stage`), not the Contact list. Verified in the
> sandbox: the two objects are **independent** — setting the Contact to MQL does
> NOT move `hs_pipeline_stage`, and moving the Lead stage does NOT change the
> Contact `lifecyclestage`. So Pass B now sets **both**: Contact
> `lifecyclestage = marketingqualifiedlead` (for funnel/MQL reporting, which
> counts contacts) **and** Lead `hs_pipeline_stage` = the "Marketing Qualified
> Lead" stage (so Sales sees it). Verified end-to-end 2026-07-29: both land at
> MQL. **Prod note:** re-confirm the MQL stage id (sandbox `159139484`) via
> `GET /crm/v3/pipelines/leads` before the first prod run — stage ids can differ
> per portal — and update `lead_pipeline_stage` in `lead_props.json`.

> **Slack approval loop mechanics (verified end-to-end 2026-07-22 against the
> sandbox).** In Pass A, post one message per lead and **keep the returned
> message `ts` mapped to that lead's `contactId`** (the mapping is how Pass B
> knows which reaction applies to which contact). Embed the `contactId` in the
> message body too, so the mapping survives across two separate sessions/runs. In
> Pass B, read each message's reactions (Slack `slack_read_thread` detailed, or
> `reactions.get`): `white_check_mark` → qualify, `x` → skip, none → defer/re-queue.
> Apply via REST, then reply in the message's thread with the per-lead result.
> Proven flow: propose → human ✅ → read reaction → REST write (contact + lead,
> HTTP 200, verified) → thread confirmation.

> **Two-pass timing.** Pass A and Pass B can be the same session with a wait, or
> two scheduled runs (propose AM, apply after approvals). Keep them separate so a
> human is always between enrichment and the HubSpot write in Phase 1.

## Phase 2 — Auto-qualify (DO NOT ENABLE until rubric is trusted)

Once the rubric's proposals match Yijia's decisions over a trial period:
- Leads with **confidence ≥ auto-qualify threshold** (Config) and **no veto**
  skip the approval gate — Claude runs the qualify action directly in Pass A.
- Mid-confidence leads still go to the Slack approval queue.
- Vetoed / low-confidence leads are skipped (with reason) as today.
- Keep a daily Slack summary of auto-qualified leads for audit.
This lifts the single-owner ~15 hrs/week ceiling while keeping humans on the
ambiguous middle.

## Notes / caveats
- **Owner assignment is HubSpot's job**, not this playbook's — only set the three
  fields that trigger it.
- **No LinkedIn automation** — compliant enrichment APIs or web search only.
- Skips are recoverable: an "insufficient info" skip can be re-queued if a later
  enrichment provider is added — don't hard-delete or disqualify.
- Phase 1 writes to HubSpot **only after human approval**.
