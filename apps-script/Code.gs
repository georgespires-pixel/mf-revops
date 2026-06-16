/**
 * Moonfare — Weekly Funnel & MQL refresh (Google Apps Script)
 * -----------------------------------------------------------
 * Pulls the registration cohort from HubSpot and refreshes data tabs in THIS
 * workbook on a weekly schedule. Runs independently of Claude.
 *
 * Cohort (verified): contacts where registration_date is in the rolling window
 * AND partner_name in {Moonfare, Moonfare US, Moonfare Private Office}.
 * Market = territory. RVF / MQL / cascade logic mirrors weekly-funnel-report.md.
 *
 * Setup: see apps-script/README.md. Requires Script Property HUBSPOT_TOKEN.
 * To avoid clobbering the curated tabs, this writes to tabs prefixed "Live ".
 */

// ---------- Config ----------
var PARTNER_NAMES = ['Moonfare', 'Moonfare US', 'Moonfare Private Office'];
var PROPS = ['registration_date','partner_name','territory','lifecyclestage',
  'hs_analytics_source','country','suitability_status','investor_type',
  'your_goals_with_moonfare','d2i_estimated_financial_portfolio_size'];
var MARKETS = ['US','UK','DACH','BeNeLux','APAC','ROW','Israel'];
var D2I_COUNTRIES = ['Spain','Finland','Norway','Liechtenstein','Czech Republic',
  'Denmark','Sweden','Ireland','Portugal','Luxembourg','Greece'];
var UK_INVESTOR_TYPES = ['gb-certified-high-net-worth','gb-self-certified-sophisticated',
  'gb-invest-on-behalf-entity','uk-hnw-company-or-association','uk - self-certified sophisticated'];
var D2I_CUTOFF = Date.UTC(2026, 4, 19); // 19 May 2026 (month is 0-based)
var STAGE_RANK = {'lead':1,'marketingqualifiedlead':2,'salesqualifiedlead':3,
  'customer':4,'161472561':4,'161472562':4}; // off-path stages absent => excluded from "reached"
var SOURCE_LABELS = {
  'DIRECT_TRAFFIC':'Direct Traffic','OFFLINE':'Offline Sources','ORGANIC_SEARCH':'Organic Search',
  'PAID_SEARCH':'Paid Search','OTHER_CAMPAIGNS':'Other Campaigns','REFERRALS':'Referrals',
  'SOCIAL_MEDIA':'Organic Social','PAID_SOCIAL':'Paid Social','EMAIL_MARKETING':'Email Marketing',
  'AI_REFERRAL':'AI Referrals','AI_REFERRALS':'AI Referrals'
};
var SOURCE_ORDER = ['Direct Traffic','Offline Sources','Organic Search','Paid Search',
  'AI Referrals','Email Marketing','Organic Social','Other Campaigns','Referrals','Paid Social'];
var TZ = 'Europe/Berlin';

// ---------- Entry points ----------
function runWeeklyFunnelReport() {
  var now = new Date();
  var startMs = Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 2, 1); // first day, 2 months back
  var contacts = fetchCohort_(startMs);
  var agg = aggregate_(contacts);
  writeReport_(agg);
}

/** One-time: schedule a weekly Sunday 19:45 run (project timezone = Europe/Berlin).
 *  19:45 so the sheet is refreshed ~15 min before the Claude Slack digest (20:00). */
function createWeeklyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'runWeeklyFunnelReport') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('runWeeklyFunnelReport')
    .timeBased().onWeekDay(ScriptApp.WeekDay.SUNDAY).atHour(19).nearMinute(45).create();
}

// ---------- HubSpot ----------
function getToken_() {
  var t = PropertiesService.getScriptProperties().getProperty('HUBSPOT_TOKEN');
  if (!t) throw new Error('Set Script Property HUBSPOT_TOKEN (HubSpot private app token, scope crm.objects.contacts.read).');
  return t;
}
function getSpreadsheet_() {
  var id = PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID');
  return id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActive();
}
function fetchCohort_(startMs) {
  var token = getToken_(), url = 'https://api.hubapi.com/crm/v3/objects/contacts/search';
  var after = null, all = [], seen = {};
  do {
    var body = {
      filterGroups: [{ filters: [
        { propertyName: 'registration_date', operator: 'GTE', value: String(startMs) },
        { propertyName: 'partner_name', operator: 'IN', values: PARTNER_NAMES }
      ]}],
      properties: PROPS, limit: 100
    };
    if (after) body.after = after;
    var res = UrlFetchApp.fetch(url, {
      method: 'post', contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token },
      payload: JSON.stringify(body), muteHttpExceptions: true
    });
    if (res.getResponseCode() !== 200) throw new Error('HubSpot search failed ' + res.getResponseCode() + ': ' + res.getContentText());
    var data = JSON.parse(res.getContentText());
    (data.results || []).forEach(function (r) { if (!seen[r.id]) { seen[r.id] = 1; all.push(r.properties || {}); } });
    after = (data.paging && data.paging.next) ? data.paging.next.after : null;
    Utilities.sleep(120); // be gentle on rate limits
  } while (after);
  return all;
}

// ---------- Logic ----------
function parseDate_(s) {
  if (!s) return null;
  var p = String(s).substring(0, 10).split('-');
  return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
}
function monthKey_(d) { return d.getUTCFullYear() + '-' + ('0' + (d.getUTCMonth() + 1)).slice(-2); }
function monthLabel_(d) {
  var n = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return n[d.getUTCMonth()] + ' ' + d.getUTCFullYear();
}
function weekStart_(d) { // Monday
  var day = (d.getUTCDay() + 6) % 7;
  return new Date(d.getTime() - day * 86400000);
}
function fmtDate_(d) { return Utilities.formatDate(d, 'UTC', 'yyyy-MM-dd'); }
function notEmpty_(v) { return v !== undefined && v !== null && String(v).trim() !== ''; }
function pct_(num, den) { return den > 0 ? Math.round(num / den * 100) + '%' : ''; }

function isRVF_(c) {
  var suit = (c.suitability_status || '').toUpperCase();
  if (c.territory === 'UK') {
    var it = (c.investor_type || '').toLowerCase();
    return suit === 'VERIFIED' && UK_INVESTOR_TYPES.indexOf(it) >= 0;
  }
  var reg = parseDate_(c.registration_date);
  if (reg && reg.getTime() >= D2I_CUTOFF && D2I_COUNTRIES.indexOf(c.country) >= 0) {
    return notEmpty_(c.your_goals_with_moonfare) || notEmpty_(c.d2i_estimated_financial_portfolio_size);
  }
  return suit === 'PENDING' || suit === 'VERIFIED';
}
function sourceLabel_(s) { if (!s) return 'Offline Sources'; return SOURCE_LABELS[s] || s; }
function marketOf_(c) { return MARKETS.indexOf(c.territory) >= 0 ? c.territory : 'Other'; }

function monthCols_() {
  var now = new Date(), cols = [];
  for (var i = 2; i >= 0; i--) {
    var d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - i, 1));
    cols.push({ key: monthKey_(d), label: monthLabel_(d) + (i === 0 ? '*' : ''), partial: i === 0 });
  }
  return cols;
}

function aggregate_(contacts) {
  var cols = monthCols_();
  var monthKeys = cols.map(function (c) { return c.key; });
  var blankMonth = function () { var o = {}; monthKeys.forEach(function (k) { o[k] = { reg: 0, rvf: 0, mql: 0 }; }); return o; };
  var market = {}, source = {}, totals = blankMonth();
  var cascade = {}; monthKeys.forEach(function (k) { cascade[k] = { reg: 0, pql: 0, mql: 0, sql: 0, inv: 0 }; });
  var weekly = {};

  contacts.forEach(function (c) {
    var d = parseDate_(c.registration_date); if (!d) return;
    var mk = monthKey_(c.registration_date ? d : d);
    var rank = STAGE_RANK[c.lifecyclestage] || 0;
    var rvf = isRVF_(c);
    var curMql = c.lifecyclestage === 'marketingqualifiedlead';

    // monthly market/source/totals (only the 3 reporting months)
    if (monthKeys.indexOf(mk) >= 0) {
      var mName = marketOf_(c);
      if (!market[mName]) market[mName] = blankMonth();
      market[mName][mk].reg++; if (rvf) market[mName][mk].rvf++; if (curMql) market[mName][mk].mql++;
      var sName = sourceLabel_(c.hs_analytics_source);
      if (!source[sName]) source[sName] = blankMonth();
      source[sName][mk].reg++; if (rvf) source[sName][mk].rvf++; if (curMql) source[sName][mk].mql++;
      totals[mk].reg++; if (rvf) totals[mk].rvf++; if (curMql) totals[mk].mql++;
      var cc = cascade[mk];
      cc.reg++; if (rank >= 1) cc.pql++; if (rank >= 2) cc.mql++; if (rank >= 3) cc.sql++; if (rank >= 4) cc.inv++;
    }
    // weekly (reached-MQL = rank>=2)
    var wk = fmtDate_(weekStart_(d));
    if (!weekly[wk]) weekly[wk] = { reg: 0, rvf: 0, mql: 0 };
    weekly[wk].reg++; if (rvf) weekly[wk].rvf++; if (rank >= 2) weekly[wk].mql++;
  });

  return { cols: cols, market: market, source: source, totals: totals, cascade: cascade, weekly: weekly, n: contacts.length };
}

// ---------- Write ----------
function writeReport_(a) {
  var ss = getSpreadsheet_(), cols = a.cols;

  // Funnel by Market
  var mh = ['Market'];
  cols.forEach(function (c) { mh.push('Reg ' + c.label, 'RVF ' + c.label, 'RVF% ' + c.label, 'MQL ' + c.label); });
  var mrows = [mh];
  var marketNames = MARKETS.concat(a.market['Other'] ? ['Other'] : []);
  marketNames.forEach(function (m) {
    var row = [m]; var md = a.market[m] || {};
    cols.forEach(function (c) { var x = md[c.key] || { reg: 0, rvf: 0, mql: 0 }; row.push(x.reg, x.rvf, pct_(x.rvf, x.reg), x.mql); });
    mrows.push(row);
  });
  var trow = ['TOTAL'];
  cols.forEach(function (c) { var t = a.totals[c.key]; trow.push(t.reg, t.rvf, pct_(t.rvf, t.reg), t.mql); });
  mrows.push(trow);
  writeTab_(ss, 'Live Funnel by Market', mrows);

  // Funnel by Source
  var sh = ['Source'];
  cols.forEach(function (c) { sh.push('Reg ' + c.label, 'RVF ' + c.label, 'MQL ' + c.label); });
  var srows = [sh];
  var srcNames = SOURCE_ORDER.filter(function (s) { return a.source[s]; })
    .concat(Object.keys(a.source).filter(function (s) { return SOURCE_ORDER.indexOf(s) < 0; }));
  srcNames.forEach(function (s) {
    var row = [s]; var sd = a.source[s];
    cols.forEach(function (c) { var x = sd[c.key] || { reg: 0, rvf: 0, mql: 0 }; row.push(x.reg, x.rvf, x.mql); });
    srows.push(row);
  });
  var st = ['TOTAL'];
  cols.forEach(function (c) { var t = a.totals[c.key]; st.push(t.reg, t.rvf, t.mql); });
  srows.push(st);
  writeTab_(ss, 'Live Funnel by Source', srows);

  // Funnel cascade
  var ch = ['Stage'].concat(cols.map(function (c) { return c.label; }));
  var stages = [['Registrations', 'reg'], ['Reached Pre-Qualified', 'pql'], ['Reached MQL', 'mql'], ['Reached SQL', 'sql'], ['Reached Investor', 'inv']];
  var crows = [ch];
  stages.forEach(function (s) { var row = [s[0]]; cols.forEach(function (c) { row.push(a.cascade[c.key][s[1]]); }); crows.push(row); });
  writeTab_(ss, 'Live Funnel Cascade', crows);

  // Weekly trend (last 10 weeks; MQL = cumulative reached)
  var wks = Object.keys(a.weekly).sort();
  wks = wks.slice(Math.max(0, wks.length - 10));
  var wrows = [['Week (w/c)', 'Reg', 'RVF', 'MQL (cumulative reached)', 'RVF%', 'MQL%']];
  var todayWk = fmtDate_(weekStart_(new Date()));
  wks.forEach(function (wk) {
    var x = a.weekly[wk];
    wrows.push([wk + (wk === todayWk ? '*' : ''), x.reg, x.rvf, x.mql, pct_(x.rvf, x.reg), pct_(x.mql, x.reg)]);
  });
  writeTab_(ss, 'Live Weekly Trend', wrows);

  // Methodology / stamp
  writeTab_(ss, 'Live Methodology', [
    ['Last updated', Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd HH:mm') + ' ' + TZ],
    ['Cohort', 'registration_date in last 3 months AND partner_name in {Moonfare, Moonfare US, Moonfare Private Office}; ' + a.n + ' contacts pulled'],
    ['Market', 'territory property'],
    ['RVF', 'UK(any date): suitability VERIFIED + UK investor_type. Pre-19May non-UK: suitability Pending/Verified. On/after 19May D2I country: goals OR portfolio known. On/after 19May other: Pending/Verified.'],
    ['MQL', 'Weekly = cumulative reached MQL (>= MQL). By-market/by-source = current-stage MQL.'],
    ['Cascade', 'cumulative reached-at-least; off-path (Disqualified/Prospect/Unresponsive) excluded from reached counts.'],
    ['Caveat', 'Current (3rd) month and the latest week (*) are partial. Stages reflect current lifecycle at run time.']
  ]);
}

function writeTab_(ss, name, rows) {
  var sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name); else sh.clear();
  if (!rows.length) return;
  var w = rows.reduce(function (m, r) { return Math.max(m, r.length); }, 0);
  rows = rows.map(function (r) { while (r.length < w) r.push(''); return r; });
  sh.getRange(1, 1, rows.length, w).setValues(rows);
  sh.getRange(1, 1, 1, w).setFontWeight('bold');
  sh.setFrozenRows(1);
}
