#!/usr/bin/env node
/**
 * BD CRM Screening — Node.js implementation
 * ==========================================
 * A faithful port of the Moonfare "BD CRM Screening" automation described in
 * mf-revops/crm-screening.md. It screens pre-qualified leads (PQLs) in HubSpot:
 *
 *   Pass A (propose): pull the PQL queue -> prioritise -> enrich -> score
 *     against the rubric -> post a Qualify/Skip proposal to Slack for human
 *     approval.
 *   Pass B (apply): read approvals -> apply each approved qualify as ONE action
 *     (contact lifecyclestage -> MQL; Lead object Business Development=Yes,
 *     Lead type=New Business). Owner is left to the native HubSpot workflow.
 *
 * Phase 1 = human-approved copilot. Phase 2 (auto-qualify) is gated OFF.
 *
 * Design notes:
 *  - The connected HubSpot MCP is READ-ONLY and can't see the Leads object, so
 *    all writes go through the HubSpot REST API with a private-app token.
 *  - The rubric decision is genuine judgement — in production it's an LLM call.
 *    `scoreLead()` ships a transparent heuristic as a stand-in and exposes a
 *    hook (LLM_SCORER) to swap in a real model.
 *  - No cookie-based LinkedIn automation (ToS/GDPR). Enrichment is the HubSpot
 *    record + a pluggable web-search fallback.
 *
 * Runtime: Node 18+ (uses global fetch). No dependencies.
 *
 * Env:
 *   HUBSPOT_BD_WRITE_TOKEN   HubSpot private-app access token (required)
 *   SLACK_BOT_TOKEN          Slack bot token (optional; dry-run prints if unset)
 *   SLACK_CHANNEL            Slack channel id (default the test channel)
 *   QUEUE_CAP                max leads per run (default 25)
 *   ALLOW_PROD=1             permit writes against a non-sandbox portal
 */

import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const HUBSPOT_BASE = 'https://api.hubapi.com';
const TOKEN = process.env.HUBSPOT_BD_WRITE_TOKEN;
const SLACK_TOKEN = process.env.SLACK_BOT_TOKEN;
const SLACK_CHANNEL = process.env.SLACK_CHANNEL || 'C0BA557N4UA'; // #test-claude
const QUEUE_CAP = Number(process.env.QUEUE_CAP || 25);
const ALLOW_PROD = process.env.ALLOW_PROD === '1';

// HubSpot returns these accountType values for non-production portals.
const SANDBOX_ACCOUNT_TYPES = new Set(['SANDBOX', 'DEVELOPER_TEST', 'APP_DEVELOPER']);

// Phase 2 auto-qualify rule — DO NOT ENABLE until the rubric is ratified.
const PHASE2 = { enabled: false, minScore: 85, confidence: 'high' };

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function requireToken() {
  if (!TOKEN) {
    fail('env HUBSPOT_BD_WRITE_TOKEN is not set. Create the sandbox private app '
      + '(see crm-screening.md) and export the token before running.');
  }
}

function fail(msg) {
  console.error(`ERROR: ${msg}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// HubSpot REST client
// ---------------------------------------------------------------------------
async function hubspot(method, endpoint, { body, params } = {}) {
  requireToken();
  let url = HUBSPOT_BASE + endpoint;
  if (params) url += '?' + new URLSearchParams(params).toString();
  const res = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = text; }
  return { status: res.status, ok: res.ok, data };
}

async function getAccount() {
  const { status, ok, data } = await hubspot('GET', '/account-info/v3/details');
  if (!ok) fail(`/account-info/v3/details returned ${status}: ${JSON.stringify(data)}`);
  return data;
}

/** Confirm the portal is a sandbox before allowing any write. */
async function guardSandbox() {
  const acct = await getAccount();
  const type = acct.accountType || 'UNKNOWN';
  const isSandbox = SANDBOX_ACCOUNT_TYPES.has(type);
  console.log(`Portal ${acct.portalId} — accountType=${type} `
    + `(${isSandbox ? 'SANDBOX' : 'PRODUCTION-LIKE'})`);
  if (!isSandbox && !ALLOW_PROD) {
    fail('REFUSING to write: portal does not look like a sandbox. Re-run against '
      + 'the sandbox token, or set ALLOW_PROD=1 to override.');
  }
  return acct;
}

// ---------------------------------------------------------------------------
// Lead-object property mapping (confirmed in the sandbox via `props leads`)
// ---------------------------------------------------------------------------
async function loadLeadProps() {
  try {
    const raw = await readFile(path.join(__dirname, 'lead_props.json'), 'utf8');
    return JSON.parse(raw);
  } catch {
    return null; // not yet confirmed
  }
}

// ---------------------------------------------------------------------------
// Qualification rubric (heuristic stand-in for the LLM judgement)
// ---------------------------------------------------------------------------
// Swap in a real model by setting LLM_SCORER to an async (lead, enrichment) fn
// that returns the same output shape. The heuristic below is deterministic and
// exists so the pipeline runs end-to-end without a model wired up.
let LLM_SCORER = null;

const SENIOR_STRONG = /\b(ceo|cfo|coo|cio|cto|founder|co-?founder|owner|partner|managing director|managing partner|global head|head of|president|vice chair|chair(man)?|board)\b/i;
const SENIOR_WEAK = /\b(associate|analyst|coordinator|assistant|junior|intern|trainee)\b/i;
const INDUSTRY_PREFERRED = /\b(private equity|venture capital|hedge fund|investment bank|corporate finance|m&a|law firm|family office|wealth management|asset management)\b/i;

function pick(strong, weak) {
  if (strong) return 'strong';
  if (weak) return 'weak';
  return 'unclear';
}

/** Transparent heuristic implementing the four-dimension rubric. */
function heuristicScore(lead, enrichment) {
  const text = [
    lead.jobtitle, lead.company, enrichment?.role, enrichment?.firm,
    enrichment?.summary,
  ].filter(Boolean).join(' ');
  const missing = [];
  if (!text.trim()) missing.push('no role/company/enrichment text available');

  const seniority = pick(SENIOR_STRONG.test(text), SENIOR_WEAK.test(text));
  const industry = INDUSTRY_PREFERRED.test(text) ? 'preferred'
    : (text ? 'acceptable' : 'unclear');
  const company = enrichment?.companyKnown ? 'strong' : (lead.company ? 'moderate' : 'unclear');
  const wealth = /\b(exit|acquired|acquisition|fundrais|ipo|founder|owner|investor|philanthrop)\b/i.test(text)
    ? 'strong' : 'unclear';

  const strongCount = [seniority, industry, company, wealth]
    .filter((s) => s === 'strong' || s === 'preferred').length;
  // Weighted score: seniority + wealth are HIGH; industry + company MEDIUM.
  let score = 0;
  score += ({ strong: 30, moderate: 15, weak: 5, unclear: 10 })[seniority] ?? 10;
  score += ({ strong: 30, unclear: 10 })[wealth] ?? 10;
  score += ({ preferred: 20, acceptable: 12, weak: 4, unclear: 8 })[industry] ?? 8;
  score += ({ strong: 20, moderate: 12, weak: 4, unclear: 8 })[company] ?? 8;

  let qualification, confidence;
  const thin = missing.length > 0;
  if (thin) {
    // Guardrail: thin data -> NEEDS_REVIEW, never auto-reject.
    qualification = 'NEEDS_REVIEW';
    confidence = 'low';
    score = Math.min(score, 55);
  } else if (strongCount >= 2 && seniority !== 'weak' && score >= 65) {
    qualification = 'MQL';
    confidence = strongCount >= 3 ? 'high' : 'medium';
  } else if (score >= 40) {
    qualification = 'NEEDS_REVIEW';
    confidence = 'medium';
  } else {
    qualification = 'NOT_MQL';
    confidence = seniority === 'weak' ? 'high' : 'medium';
  }

  return {
    qualification,
    confidence,
    score,
    reasoning: `Heuristic: seniority=${seniority}, industry=${industry}, `
      + `company=${company}, wealth=${wealth}. ${strongCount} strong signal(s).`,
    signals: { seniority, industry, company_quality: company, wealth_signals: wealth },
    key_evidence: [lead.jobtitle, lead.company].filter(Boolean),
    missing_information: missing,
  };
}

async function scoreLead(lead, enrichment) {
  if (LLM_SCORER) return LLM_SCORER(lead, enrichment);
  return heuristicScore(lead, enrichment);
}

// ---------------------------------------------------------------------------
// Enrichment (pluggable — the compliant LinkedIn replacement)
// ---------------------------------------------------------------------------
// 1) HubSpot record itself (already pulled). 2) A web-search fallback hook.
// NO cookie-based LinkedIn automation.
let WEB_SEARCH = null; // async (query) => { role, firm, summary, companyKnown }

async function enrich(lead) {
  // Prefer the HubSpot record — often enough.
  const base = {
    role: lead.jobtitle || null,
    firm: lead.company || null,
    summary: [lead.your_goals_with_moonfare, lead.d2i_estimated_financial_portfolio_size]
      .filter(Boolean).join('; ') || null,
    companyKnown: false,
    source: 'hubspot-record',
  };
  if ((base.role && base.firm) || !WEB_SEARCH) return base;
  // Fall through to web search when the record is thin.
  const q = [lead.firstname, lead.lastname, lead.company].filter(Boolean).join(' ');
  try {
    const web = await WEB_SEARCH(q);
    return { ...base, ...web, source: 'web-search' };
  } catch (e) {
    return { ...base, source: 'hubspot-record (web-search failed)' };
  }
}

// ---------------------------------------------------------------------------
// Pass A — propose
// ---------------------------------------------------------------------------
const PQL_PROPS = [
  'firstname', 'lastname', 'email', 'jobtitle', 'company', 'country',
  'hubspotscore', 'your_goals_with_moonfare', 'd2i_estimated_financial_portfolio_size',
  'lifecyclestage',
];

async function pullPqlQueue(cap = QUEUE_CAP) {
  const all = [];
  let after;
  do {
    const body = {
      filterGroups: [{ filters: [
        { propertyName: 'lifecyclestage', operator: 'EQ', value: 'lead' },
      ] }],
      sorts: [{ propertyName: 'hubspotscore', direction: 'DESCENDING' }],
      properties: PQL_PROPS,
      limit: 100,
    };
    if (after) body.after = after;
    const { status, ok, data } = await hubspot('POST', '/crm/v3/objects/contacts/search', { body });
    if (!ok) fail(`PQL search failed ${status}: ${JSON.stringify(data)}`);
    for (const r of data.results || []) all.push({ id: r.id, ...r.properties });
    after = data.paging?.next?.after;
  } while (after && all.length < cap);
  return all.slice(0, cap);
}

function buildProposalText(lead, result) {
  const action = { MQL: 'Qualify ✅', NEEDS_REVIEW: 'Review 🔎', NOT_MQL: 'Skip ❌' }[result.qualification];
  const name = [lead.firstname, lead.lastname].filter(Boolean).join(' ') || `(contact ${lead.id})`;
  const link = `https://app.hubspot.com/contacts/_/contact/${lead.id}`;
  return [
    `*${name}* — proposed: *${action}*  (score ${result.score}, ${result.confidence} confidence)`,
    `• ${lead.jobtitle || 'role unknown'} @ ${lead.company || 'company unknown'} — ${lead.country || 'country unknown'}`,
    `• ${result.reasoning}`,
    result.missing_information.length ? `• missing: ${result.missing_information.join(', ')}` : null,
    `• <${link}|Open in HubSpot>  ·  react ✅ to qualify, ❌ to skip`,
  ].filter(Boolean).join('\n');
}

async function postSlack(text) {
  if (!SLACK_TOKEN) {
    console.log('\n--- [DRY-RUN Slack message] ---\n' + text + '\n');
    return { dryRun: true };
  }
  const res = await fetch('https://slack.com/api/chat.postMessage', {
    method: 'POST',
    headers: { Authorization: `Bearer ${SLACK_TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ channel: SLACK_CHANNEL, text, unfurl_links: false }),
  });
  const data = await res.json();
  if (!data.ok) console.error(`Slack post failed: ${data.error}`);
  return data;
}

async function passA({ cap = QUEUE_CAP } = {}) {
  console.log(`=== Pass A — propose (queue cap ${cap}) ===`);
  const queue = await pullPqlQueue(cap);
  console.log(`Pulled ${queue.length} PQL(s) (lifecyclestage=lead), sorted by hubspotscore desc.`);
  const counts = { MQL: 0, NEEDS_REVIEW: 0, NOT_MQL: 0 };
  const scored = [];
  for (const lead of queue) {
    const enrichment = await enrich(lead);
    const result = await scoreLead(lead, enrichment);
    counts[result.qualification] = (counts[result.qualification] || 0) + 1;
    scored.push({ lead, enrichment, result });
  }
  // Header, then one message per lead so reactions map cleanly.
  await postSlack(`*BD CRM Screening* — ${queue.length} leads: `
    + `${counts.MQL} MQL · ${counts.NEEDS_REVIEW} review · ${counts.NOT_MQL} skip. `
    + `React ✅/❌ on each; Pass B applies approvals.`);
  for (const s of scored) await postSlack(buildProposalText(s.lead, s.result));
  console.log(`Proposals posted. Counts: ${JSON.stringify(counts)}`);
  return scored;
}

// ---------------------------------------------------------------------------
// Pass B — apply (the qualify action on ONE contact)
// ---------------------------------------------------------------------------
async function qualify(contactId, { apply = false } = {}) {
  const mode = apply ? 'APPLY (writing)' : 'DRY-RUN (no writes)';
  console.log(`=== Pass B qualify — contact ${contactId} — ${mode} ===`);
  if (apply) await guardSandbox();

  const leadProps = await loadLeadProps();
  if (!leadProps) {
    console.log('\nNOTE: lead_props.json not found — Lead-object internal names are '
      + 'UNCONFIRMED. Run `props leads` in the sandbox first and create it.');
    if (apply) fail('Refusing to write lead fields with unconfirmed names.');
  }

  // 1) contact lifecyclestage -> MQL
  console.log('\n[1] Contact lifecyclestage -> marketingqualifiedlead');
  if (apply) {
    const { status, ok, data } = await hubspot('PATCH', `/crm/v3/objects/contacts/${contactId}`,
      { body: { properties: { lifecyclestage: 'marketingqualifiedlead' } } });
    console.log(`    PATCH contact -> ${status}`);
    if (!ok) fail(JSON.stringify(data));
  } else {
    console.log(`    would PATCH /crm/v3/objects/contacts/${contactId} `
      + `{lifecyclestage: marketingqualifiedlead}`);
  }

  // 2) find the associated Lead
  console.log('\n[2] Find associated Lead');
  const assoc = await hubspot('GET', `/crm/v4/objects/contacts/${contactId}/associations/leads`);
  if (!assoc.ok) fail(`fetching associations: ${assoc.status}: ${JSON.stringify(assoc.data)}`);
  const leadIds = (assoc.data.results || []).map((r) => r.toObjectId);
  if (!leadIds.length) {
    fail('No associated Lead found. Seed one, or check the contact.');
  }
  const leadId = leadIds[0];
  console.log(`    associated lead id = ${leadId}`
    + (leadIds.length > 1 ? `  (WARNING: ${leadIds.length} leads, using first)` : ''));

  // 3) set the Lead fields
  console.log('\n[3] Lead: Business Development -> Yes, Lead type -> New Business');
  const props = leadProps ? {
    [leadProps.business_development.name]: leadProps.business_development.value,
    [leadProps.lead_type.name]: leadProps.lead_type.value,
  } : { '<business_development>': 'Yes', '<lead_type>': 'New Business' };
  if (apply && leadProps) {
    const { status, ok, data } = await hubspot('PATCH', `/crm/v3/objects/leads/${leadId}`,
      { body: { properties: props } });
    console.log(`    PATCH lead ${leadId} ${JSON.stringify(props)} -> ${status}`);
    if (!ok) fail(JSON.stringify(data));
  } else {
    console.log(`    would PATCH /crm/v3/objects/leads/${leadId} ${JSON.stringify(props)}`);
  }

  // 4) owner is NOT set — native by-country workflow handles it
  console.log('\n[4] Owner: left to native HubSpot by-country workflow (not set here).');

  if (apply) {
    console.log('\n=== Verify ===');
    const c = await hubspot('GET', `/crm/v3/objects/contacts/${contactId}`,
      { params: { properties: 'lifecyclestage' } });
    console.log(`    contact.lifecyclestage = ${c.data.properties?.lifecyclestage}`);
    if (leadProps) {
      const names = [leadProps.business_development.name, leadProps.lead_type.name];
      const l = await hubspot('GET', `/crm/v3/objects/leads/${leadId}`,
        { params: { properties: names.join(',') } });
      console.log(`    lead props = ${JSON.stringify(l.data.properties)}`);
    }
  }
  console.log('\nDone.');
}

// ---------------------------------------------------------------------------
// Discovery helpers (sandbox setup)
// ---------------------------------------------------------------------------
async function whoami() {
  const acct = await getAccount();
  console.log(JSON.stringify({
    portalId: acct.portalId, accountType: acct.accountType,
    timeZone: acct.timeZone, uiDomain: acct.uiDomain,
  }, null, 2));
  console.log(SANDBOX_ACCOUNT_TYPES.has(acct.accountType)
    ? '\n=> SANDBOX portal. Safe to test writes.'
    : '\n=> NOT a sandbox. Writes blocked unless ALLOW_PROD=1.');
}

async function props(object, grep) {
  const { status, ok, data } = await hubspot('GET', `/crm/v3/properties/${object}`);
  if (!ok) fail(`GET /crm/v3/properties/${object} -> ${status}: ${JSON.stringify(data)}`);
  const term = (grep || '').toLowerCase();
  let shown = 0;
  for (const p of (data.results || []).sort((a, b) => (a.label || '').localeCompare(b.label || ''))) {
    if (term && !p.name.toLowerCase().includes(term) && !(p.label || '').toLowerCase().includes(term)) continue;
    shown++;
    console.log(`  ${JSON.stringify(p.label)}  internal=${JSON.stringify(p.name)}  ${p.type}/${p.fieldType}`);
    for (const o of p.options || []) console.log(`       option: label=${JSON.stringify(o.label)} value=${JSON.stringify(o.value)}`);
  }
  console.log(`\n${shown} propert${shown === 1 ? 'y' : 'ies'} shown`
    + `${term ? ` matching ${JSON.stringify(grep)}` : ''} (of ${(data.results || []).length} on ${object}).`);
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------
function usage() {
  console.log(`BD CRM Screening (Node)

Usage:
  node crm-screening.mjs whoami
  node crm-screening.mjs props <object> [--grep TERM]
  node crm-screening.mjs pass-a [--cap N]
  node crm-screening.mjs qualify --contact-id ID [--apply]

Phase 2 auto-qualify is ${PHASE2.enabled ? 'ON' : 'OFF (gated)'}.`);
}

function argVal(flag) {
  const i = process.argv.indexOf(flag);
  return i >= 0 ? process.argv[i + 1] : undefined;
}
const hasFlag = (f) => process.argv.includes(f);

async function main() {
  const cmd = process.argv[2];
  switch (cmd) {
    case 'whoami': return whoami();
    case 'props': return props(process.argv[3], argVal('--grep'));
    case 'pass-a': return void await passA({ cap: Number(argVal('--cap') || QUEUE_CAP) });
    case 'qualify': {
      const id = argVal('--contact-id');
      if (!id) fail('qualify requires --contact-id ID');
      return qualify(id, { apply: hasFlag('--apply') });
    }
    default: usage();
  }
}

main().catch((e) => fail(e?.stack || String(e)));

export { scoreLead, heuristicScore, enrich, qualify, passA, pullPqlQueue };
