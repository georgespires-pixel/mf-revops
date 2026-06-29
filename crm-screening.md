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
| Slack channel (approval queue) | `#bd-crm-screening` — **TODO confirm / create** (private → invite the Claude Slack app) |
| Run cadence | Daily, weekday mornings (Phase 1). Upgrade path: per-PQL event trigger. |
| Queue size cap per run | `25` leads (tune to volume) |
| Auto-qualify (Phase 2) | **OFF** in Phase 1 |
| Auto-qualify confidence threshold (Phase 2) | `0.85` (not used until Phase 2 is enabled) |
| HubSpot timezone | `Europe/Berlin` (account default) |

## HubSpot property mapping

**Verified** (from the funnel report, same HubSpot account):

| Concept | Property / value |
| --- | --- |
| Lifecycle: Pre-Qualified (PQL) | `lifecyclestage = lead` |
| Lifecycle: MQL (qualify target) | `lifecyclestage = marketingqualifiedlead` |
| Country of residence | `country` |
| Questionnaire signals | `your_goals_with_moonfare`, `d2i_estimated_financial_portfolio_size` |

**CONFIRM AT RUNTIME** (internal names not yet verified — resolve before writing,
mirroring how the funnel playbook confirms `suitability`/`investor_type`). Use
`search_properties` / `get_properties` on `contacts` with these keywords:

| Concept | Search keyword | Fill in once confirmed |
| --- | --- | --- |
| BD threshold / lead score (prioritisation) | `bd`, `score`, `hubspotscore`, `threshold` | `__________` |
| Business Development toggle → set "Yes" | `business_development` | `__________` |
| Lead Type → set "New Business" | `lead_type` | `__________` (value for "New Business": `__________`) |

> Do **not** guess these. If a name can't be confirmed, stop and report it in the
> Slack post rather than writing to the wrong field.

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

## Qualification rubric (the decision logic — EDIT WITH BD)

> **TODO: Yijia/BD to ratify.** This is a first-draft, explicit version of the
> two "Good info to qualify?" gateways. Output a score 0–1 and a Qualify/Skip
> call. The point is consistency — every lead judged the same way.

Score = weighted signals (tune weights with BD):

| Signal | Weight | Qualifies when… |
| --- | --- | --- |
| Investable wealth / seniority (role, firm, title) | high | Senior/decision-maker, or wealth indicators present |
| Country in a served market | medium | `country` maps to an active Moonfare market |
| Questionnaire intent | medium | `your_goals_with_moonfare` / portfolio size indicate real intent |
| BD threshold score | medium | At/above the agreed BD threshold |
| Disqualifiers | veto | Competitor, sanctioned/restricted jurisdiction, junk/test contact, clearly not investor |

Decision:
- **score ≥ qualify-threshold AND no veto → Qualify** (confidence = score).
- **veto present → Skip** (reason = the disqualifier).
- **otherwise → Skip with "insufficient info"** (so it can be re-queued if
  enrichment improves — addresses the "enrichment gaps = lost lead" pain).

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

7. **Read approvals** from the Slack thread/reactions. For each ✅ Qualify, perform
   the qualify action as **one logical update** on the contact:
   - `lifecyclestage` → `marketingqualifiedlead`
   - `<business_development prop>` → `Yes`
   - `<lead_type prop>` → `New Business`
   - **Do NOT set Contact Owner** — the native HubSpot workflow assigns it by
     `country` once the above fields change. (BPMN `Task_5` stays automated.)
   For each ❌ / deferred-as-Skip, record the skip reason (note or property) but do
   not change lifecycle.
8. **Confirm** back in the Slack thread: per-lead ✅ applied / ❌ skipped / ⚠️
   errored, plus a one-line batch summary. Never write outside HubSpot + the
   configured Slack channel.

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
