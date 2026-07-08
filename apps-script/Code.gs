/**
 * Moonfare — Weekly Funnel & MQL refresh (Google Apps Script)
 * -----------------------------------------------------------
 * Pulls the registration cohort from HubSpot and rebuilds the funnel/MQL data
 * tabs in THIS workbook on a weekly schedule. Runs independently of Claude.
 *
 * Target workbook: "Automated Funnel and MQLs report"
 *   1H8knKk8RnXTT22CC_tragza__IoRjkcxEEGmBxJbhXw
 *
 * Cohort (verified): contacts where registration_date is in the rolling window
 * (from HISTORY_START to today) AND partner_name in
 * {Moonfare, Moonfare US, Moonfare Private Office}. Market = territory.
 * RVF / MQL / cascade logic mirrors weekly-funnel-report.md and the workbook
 * Methodology tabs.
 *
 * History GROWS: each run recomputes every month (from HISTORY_START to the
 * current month) and every ISO week in that range, so a new month/week column
 * appears automatically as time moves forward. The current month and the
 * first/last weeks are partial and highlighted.
 *
 * To avoid clobbering the curated/formatted tabs, this writes to tabs prefixed
 * "Live " and re-applies the workbook's colour scheme on every run.
 *
 * Setup: see apps-script/README.md. Requires Script Property HUBSPOT_TOKEN.
 */

// ---------- Config ----------
// Default target workbook (used when the script is standalone, i.e. not bound
// to a sheet and no SPREADSHEET_ID script property is set).
var DEFAULT_SPREADSHEET_ID = '1H8knKk8RnXTT22CC_tragza__IoRjkcxEEGmBxJbhXw';
// First month of history to render (append & grow from here). YYYY-MM-01.
// Override with a script property HISTORY_START if you want to move the anchor.
var DEFAULT_HISTORY_START = '2026-04-01';

var PARTNER_NAMES = ['Moonfare', 'Moonfare US', 'Moonfare Private Office'];
var PROPS = ['registration_date', 'partner_name', 'territory', 'lifecyclestage',
  'hs_analytics_source', 'country', 'suitability_status', 'investor_type',
  'your_goals_with_moonfare', 'd2i_estimated_financial_portfolio_size',
  'completed_suitability_questionnaire_date', 'id_verified'];
var MARKETS = ['US', 'UK', 'DACH', 'BeNeLux', 'APAC', 'ROW', 'Israel'];
var D2I_COUNTRIES = ['Spain', 'Finland', 'Norway', 'Liechtenstein', 'Czech Republic',
  'Denmark', 'Sweden', 'Ireland', 'Portugal', 'Luxembourg', 'Greece'];
var UK_INVESTOR_TYPES = ['gb-certified-high-net-worth', 'gb-self-certified-sophisticated',
  'gb-invest-on-behalf-entity', 'uk-hnw-company-or-association', 'uk - self-certified sophisticated'];
var D2I_CUTOFF = Date.UTC(2026, 4, 19); // 19 May 2026 (month is 0-based)
// Cumulative "reached at least" ranks. Off-path stages are absent => excluded.
var STAGE_RANK = { 'lead': 1, 'marketingqualifiedlead': 2, 'salesqualifiedlead': 3,
  'customer': 4, '161472561': 4, '161472562': 4 };
var SOURCE_LABELS = {
  'DIRECT_TRAFFIC': 'Direct Traffic', 'OFFLINE': 'Offline Sources', 'ORGANIC_SEARCH': 'Organic Search',
  'PAID_SEARCH': 'Paid Search', 'OTHER_CAMPAIGNS': 'Other Campaigns', 'REFERRALS': 'Referrals',
  'SOCIAL_MEDIA': 'Organic Social', 'PAID_SOCIAL': 'Paid Social', 'EMAIL_MARKETING': 'Email Marketing',
  'AI_REFERRAL': 'AI Referrals', 'AI_REFERRALS': 'AI Referrals'
};
var SOURCE_ORDER = ['Direct Traffic', 'Offline Sources', 'Organic Search', 'Paid Search',
  'AI Referrals', 'Email Marketing', 'Organic Social', 'Other Campaigns', 'Referrals', 'Paid Social'];
// Tab 4 "Key Paid+Owned" only counts these four sources.
var KEY_SOURCES = ['Paid Search', 'Paid Social', 'Organic Social', 'Email Marketing'];
var SUIT_LABELS = { 'NOT_SUBMITTED': 'Not submitted', 'INSUFFICIENT_INFO': 'Insufficient info',
  'BLOCKED': 'Blocked', 'PENDING': 'Pending', 'VERIFIED': 'Verified' };
var SUIT_ORDER = ['NOT_SUBMITTED', 'INSUFFICIENT_INFO', 'BLOCKED', 'PENDING', 'VERIFIED'];
var TZ = 'Europe/Berlin';

// Workbook colour scheme (extracted from the curated tabs).
var C = {
  titleFont: '#1F3864',   // dark navy — titles
  subtitleFont: '#C0504D',// muted red — source line
  captionFont: '#595959', // grey — caveats
  headerBg: '#1F3864',    // navy header fill
  headerFont: '#FFFFFF',  // white header text
  partialBg: '#FCE4D6',   // peach — partial period
  totalBg: '#D9E1F2',     // light blue — total/subtotal rows
  groupBg: '#F2F2F2'      // light grey — group header rows
};

// ---------- Entry points ----------
function runWeeklyFunnelReport() {
  var startMs = historyStartMs_();
  var contacts = fetchCohort_(startMs);
  var now = new Date();
  var cols = monthCols_(startMs, now);
  var weeks = weekCols_(startMs, now);
  var agg = aggregate_(contacts, cols, weeks);
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
  if (id) return SpreadsheetApp.openById(id);
  var active = SpreadsheetApp.getActive();
  if (active) return active;
  return SpreadsheetApp.openById(DEFAULT_SPREADSHEET_ID);
}
function historyStartMs_() {
  var s = PropertiesService.getScriptProperties().getProperty('HISTORY_START') || DEFAULT_HISTORY_START;
  var p = s.substring(0, 10).split('-');
  return Date.UTC(+p[0], +p[1] - 1, +p[2]);
}
function fetchCohort_(startMs) {
  var token = getToken_(), url = 'https://api.hubapi.com/crm/v3/objects/contacts/search';
  var after = null, all = [], seen = {};
  do {
    var body = {
      filterGroups: [{ filters: [
        { propertyName: 'registration_date', operator: 'GTE', value: String(startMs) },
        { propertyName: 'partner_name', operator: 'IN', values: PARTNER_NAMES }
      ] }],
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

// ---------- Date / util helpers ----------
function parseDate_(s) {
  if (!s) return null;
  var p = String(s).substring(0, 10).split('-');
  if (p.length < 3) return null;
  return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
}
function monthKey_(d) { return d.getUTCFullYear() + '-' + ('0' + (d.getUTCMonth() + 1)).slice(-2); }
var MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function monthAbbr_(d) { return MONTH_ABBR[d.getUTCMonth()]; }
function monthLabel_(d) { return MONTH_ABBR[d.getUTCMonth()] + ' ' + d.getUTCFullYear(); }
function weekStart_(d) { var day = (d.getUTCDay() + 6) % 7; return new Date(d.getTime() - day * 86400000); }
function fmtWeek_(d) { return d.getUTCDate() + ' ' + MONTH_ABBR[d.getUTCMonth()]; }
function fmtDate_(d) { return d.getUTCFullYear() + '-' + ('0' + (d.getUTCMonth() + 1)).slice(-2) + '-' + ('0' + d.getUTCDate()).slice(-2); }
function notEmpty_(v) { return v !== undefined && v !== null && String(v).trim() !== ''; }
function dash_(n) { return n === 0 ? '-' : n; }           // funnel cells: 0 shown as dash (matches workbook)
function pctVal_(num, den) { return den > 0 ? num / den : ''; } // fraction; '' when denominator 0
function median_(arr) {
  if (!arr.length) return null;
  var a = arr.slice().sort(function (x, y) { return x - y; });
  var m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}

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

// ---------- Period columns (grow from HISTORY_START to now) ----------
function monthCols_(startMs, now) {
  var s = new Date(startMs), cols = [];
  var y = s.getUTCFullYear(), m = s.getUTCMonth();
  var endY = now.getUTCFullYear(), endM = now.getUTCMonth();
  while (y < endY || (y === endY && m <= endM)) {
    var d = new Date(Date.UTC(y, m, 1));
    var partial = (y === endY && m === endM);
    cols.push({ key: monthKey_(d), abbr: monthAbbr_(d), label: monthLabel_(d), partial: partial });
    m++; if (m > 11) { m = 0; y++; }
  }
  return cols;
}
function weekCols_(startMs, now) {
  var first = weekStart_(new Date(startMs));
  var last = weekStart_(now);
  var cols = [], t = first.getTime(), endT = last.getTime(), i = 0;
  while (t <= endT) {
    var d = new Date(t);
    // first and last weeks are partial (cohort starts mid-week / current week incomplete)
    cols.push({ key: fmtDate_(d), label: fmtWeek_(d), partial: (t === first.getTime() || t === endT) });
    t += 7 * 86400000; i++;
    if (i > 520) break; // safety
  }
  return cols;
}

// ---------- Aggregation ----------
function blankCell_() { return { reg: 0, rvf: 0, mql: 0 }; }
function aggregate_(contacts, cols, weeks) {
  var monthKeys = cols.map(function (c) { return c.key; });
  var weekKeys = weeks.map(function (w) { return w.key; });
  var mIdx = {}; monthKeys.forEach(function (k, i) { mIdx[k] = i; });
  var wIdx = {}; weekKeys.forEach(function (k, i) { wIdx[k] = i; });

  function blankMonths() { var o = {}; monthKeys.forEach(function (k) { o[k] = blankCell_(); }); return o; }
  var market = {}, source = {}, keyMarket = {}, marketSource = {}, totals = blankMonths(), keyTotals = blankMonths();
  var cascade = {}; monthKeys.forEach(function (k) { cascade[k] = { reg: 0, pql: 0, mql: 0, sql: 0, inv: 0 }; });
  var weekly = {}; weekKeys.forEach(function (k) { weekly[k] = blankCell_(); });

  // Point-in-time populations (current lifecycle stage), by registration in-window.
  var pql = { total: 0, suit: {}, market: {}, idVerified: 0, noQuestionnaire: 0, verifiedStuck: 0 };
  var mql = { still: 0, everReached: 0, month: {}, market: {}, source: {}, suit: {},
    questionnaireDone: 0, lags: [], sameDay: 0 };

  contacts.forEach(function (c) {
    var d = parseDate_(c.registration_date); if (!d) return;
    var mk = monthKey_(d);
    var wk = fmtDate_(weekStart_(d));
    var rank = STAGE_RANK[c.lifecyclestage] || 0;
    var rvf = isRVF_(c);
    var curStage = c.lifecyclestage;
    var curMql = curStage === 'marketingqualifiedlead';
    var inMonth = (mk in mIdx);
    var mName = marketOf_(c);
    var sName = sourceLabel_(c.hs_analytics_source);

    // ----- monthly funnel breakdowns (tabs 1-4, A) -----
    if (inMonth) {
      if (!market[mName]) market[mName] = blankMonths();
      market[mName][mk].reg++; if (rvf) market[mName][mk].rvf++; if (curMql) market[mName][mk].mql++;

      if (!source[sName]) source[sName] = blankMonths();
      source[sName][mk].reg++; if (rvf) source[sName][mk].rvf++; if (curMql) source[sName][mk].mql++;

      if (!marketSource[mName]) marketSource[mName] = {};
      if (!marketSource[mName][sName]) marketSource[mName][sName] = blankMonths();
      marketSource[mName][sName][mk].reg++; if (rvf) marketSource[mName][sName][mk].rvf++; if (curMql) marketSource[mName][sName][mk].mql++;

      totals[mk].reg++; if (rvf) totals[mk].rvf++; if (curMql) totals[mk].mql++;

      if (KEY_SOURCES.indexOf(sName) >= 0) {
        if (!keyMarket[mName]) keyMarket[mName] = blankMonths();
        keyMarket[mName][mk].reg++; if (rvf) keyMarket[mName][mk].rvf++; if (curMql) keyMarket[mName][mk].mql++;
        keyTotals[mk].reg++; if (rvf) keyTotals[mk].rvf++; if (curMql) keyTotals[mk].mql++;
      }

      var cc = cascade[mk];
      cc.reg++;
      if (rank >= 1) cc.pql++; if (rank >= 2) cc.mql++; if (rank >= 3) cc.sql++; if (rank >= 4) cc.inv++;
    }

    // ----- weekly trend (tab 5): MQL = cumulative reached (rank>=2) -----
    if (wk in wIdx) {
      weekly[wk].reg++; if (rvf) weekly[wk].rvf++; if (rank >= 2) weekly[wk].mql++;
    }

    // ----- PQL analysis (tab B): currently at Pre-Qualified -----
    if (curStage === 'lead' && inMonth) {
      pql.total++;
      var suitB = c.suitability_status || 'NOT_SUBMITTED';
      pql.suit[suitB] = (pql.suit[suitB] || 0) + 1;
      pql.market[mName] = (pql.market[mName] || 0) + 1;
      if ((c.id_verified || '') === 'Yes') pql.idVerified++;
      if (!notEmpty_(c.completed_suitability_questionnaire_date)) pql.noQuestionnaire++;
      if (suitB === 'VERIFIED') pql.verifiedStuck++;
    }

    // ----- MQL statistics (tab C) -----
    if (rank >= 2 && inMonth) mql.everReached++;
    if (curMql && inMonth) {
      mql.still++;
      mql.month[mk] = (mql.month[mk] || 0) + 1;
      mql.market[mName] = (mql.market[mName] || 0) + 1;
      mql.source[sName] = (mql.source[sName] || 0) + 1;
      var suitC = c.suitability_status || 'NOT_SUBMITTED';
      mql.suit[suitC] = (mql.suit[suitC] || 0) + 1;
      var qd = parseDate_(c.completed_suitability_questionnaire_date);
      if (qd) {
        mql.questionnaireDone++;
        var lag = Math.round((qd.getTime() - d.getTime()) / 86400000);
        mql.lags.push(lag);
        if (lag <= 0) mql.sameDay++;
      }
    }
  });

  return {
    cols: cols, weeks: weeks, market: market, source: source, keyMarket: keyMarket,
    marketSource: marketSource, totals: totals, keyTotals: keyTotals, cascade: cascade,
    weekly: weekly, pql: pql, mql: mql, n: contacts.length
  };
}

// ---------- Generic styled renderer ----------
/**
 * elements: array of
 *   { type:'title'|'subtitle'|'caption', text }
 *   { type:'blank' }
 *   { type:'table', headers:[...], rows:[[...]], opts:{
 *        partialCols:[i], pctCols:[i], signCols:[i], totalRows:[r], groupRows:[r],
 *        subtotalRows:[r], freeze:true } }   (row/col indices are 0-based within the table)
 */
function buildTab_(ss, name, elements) {
  var sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name); else { sh.clear(); sh.setFrozenRows(0); sh.setFrozenColumns(0); }
  var r = 1, maxCols = 1, freezeAt = 0;

  elements.forEach(function (el) {
    if (el.type === 'blank') { r++; return; }
    if (el.type === 'title' || el.type === 'subtitle' || el.type === 'caption') {
      var cell = sh.getRange(r, 1).setValue(el.text);
      if (el.type === 'title') cell.setFontWeight('bold').setFontColor(C.titleFont).setFontSize(12);
      else if (el.type === 'subtitle') cell.setFontColor(C.subtitleFont);
      else cell.setFontColor(C.captionFont).setFontStyle('italic');
      r++; return;
    }
    if (el.type === 'table') {
      var o = el.opts || {}, headers = el.headers, rows = el.rows || [], w = headers.length;
      maxCols = Math.max(maxCols, w);
      var hRange = sh.getRange(r, 1, 1, w).setValues([headers]);
      hRange.setBackground(C.headerBg).setFontColor(C.headerFont).setFontWeight('bold')
        .setHorizontalAlignment('center').setVerticalAlignment('middle').setWrap(true);
      if (o.freeze) freezeAt = r;
      r++;
      if (rows.length) {
        var norm = rows.map(function (row) { var a = row.slice(); while (a.length < w) a.push(''); return a; });
        sh.getRange(r, 1, rows.length, w).setValues(norm);
        (o.pctCols || []).forEach(function (ci) { sh.getRange(r, ci + 1, rows.length, 1).setNumberFormat('0%'); });
        (o.signCols || []).forEach(function (ci) { sh.getRange(r, ci + 1, rows.length, 1).setNumberFormat('+0;-0;0'); });
        (o.partialCols || []).forEach(function (ci) { sh.getRange(r, ci + 1, rows.length, 1).setBackground(C.partialBg); });
        (o.partialRows || []).forEach(function (ri) { sh.getRange(r + ri, 1, 1, w).setBackground(C.partialBg); });
        (o.groupRows || []).forEach(function (ri) { sh.getRange(r + ri, 1, 1, w).setBackground(C.groupBg).setFontWeight('bold'); });
        (o.subtotalRows || []).forEach(function (ri) { sh.getRange(r + ri, 1, 1, w).setFontWeight('bold'); });
        // total rows last so their fill wins over any partial-column peach
        (o.totalRows || []).forEach(function (ri) { sh.getRange(r + ri, 1, 1, w).setBackground(C.totalBg).setFontWeight('bold'); });
        r += rows.length;
      }
    }
  });

  if (freezeAt) { sh.setFrozenRows(freezeAt); sh.setFrozenColumns(1); }
  sh.setColumnWidth(1, 170);
  if (maxCols > 1) sh.setColumnWidths(2, maxCols - 1, 66);
  return sh;
}

// Build the column plan for a wide funnel table (metric blocks with a Δ per metric).
// metrics: [{key:'reg',label:'Reg',delta:true}, ...]. Returns {headers, cols:[{metric,col,partial,delta}]}
function wideHeaders_(cols, metrics) {
  var fulls = cols.filter(function (c) { return !c.partial; });
  var partials = cols.filter(function (c) { return c.partial; });
  var lastFull = fulls.length ? fulls[fulls.length - 1] : null;
  var prevFull = fulls.length > 1 ? fulls[fulls.length - 2] : null;
  var headers = ['Market'], plan = [];
  metrics.forEach(function (mt) {
    fulls.forEach(function (c) { headers.push(mt.label + '\n' + c.abbr); plan.push({ metric: mt, key: c.key, kind: 'val' }); });
    if (mt.delta && lastFull && prevFull) {
      headers.push('Δ\n' + lastFull.abbr + '-' + prevFull.abbr);
      plan.push({ metric: mt, kind: 'delta', a: lastFull.key, b: prevFull.key });
    }
    partials.forEach(function (c) { headers.push(mt.label + '\n' + c.abbr + '*'); plan.push({ metric: mt, key: c.key, kind: 'val', partial: true }); });
  });
  return { headers: headers, plan: plan };
}
// Given a per-month cell map {mk:{reg,rvf,mql}}, emit the values for a plan.
function wideRow_(label, cellsByMonth, plan) {
  var row = [label];
  plan.forEach(function (p) {
    var mt = p.metric;
    if (p.kind === 'delta') {
      var va = metricVal_(cellsByMonth[p.a], mt.key), vb = metricVal_(cellsByMonth[p.b], mt.key);
      var diff = (typeof va === 'number' ? va : 0) - (typeof vb === 'number' ? vb : 0);
      row.push(dash_(diff));
    } else {
      row.push(metricVal_(cellsByMonth[p.key], mt.key, true));
    }
  });
  return row;
}
function metricVal_(cell, key, forDisplay) {
  cell = cell || blankCell_();
  if (key === 'rvfpct') return pctVal_(cell.rvf, cell.reg);
  var v = cell[key] || 0;
  return forDisplay ? dash_(v) : v;
}
function planPartialCols_(plan) { // 0-based column indices (offset by 1 for label col)
  var out = [];
  plan.forEach(function (p, i) { if (p.partial) out.push(i + 1); });
  return out;
}
function planPctSignCols_(plan) {
  var pct = [], sign = [];
  plan.forEach(function (p, i) {
    if (p.metric.key === 'rvfpct' && p.kind === 'val') pct.push(i + 1);
    if (p.kind === 'delta') sign.push(i + 1);
  });
  return { pct: pct, sign: sign };
}

// ---------- Report writer ----------
var FUNNEL_METRICS = [
  { key: 'reg', label: 'Reg', delta: true },
  { key: 'rvf', label: 'RVF', delta: true },
  { key: 'rvfpct', label: 'RVF%', delta: false },
  { key: 'mql', label: 'MQL', delta: true }
];

function writeReport_(a) {
  var ss = getSpreadsheet_();
  var cols = a.cols;
  var stamp = Utilities.formatDate(new Date(), TZ, 'dd MMM yyyy');
  var srcLine = 'Registrations / Ready to View Funds / MQL. Source: HubSpot (live), refreshed ' + stamp + '.';
  var partialMonth = cols.filter(function (c) { return c.partial; }).map(function (c) { return c.label; }).join(', ');
  var caption = partialMonth + ' is partial (current month, highlighted) — read directionally. Δ = latest full month vs the prior full month. See Live Weekly Trend for momentum.';

  var wh = wideHeaders_(cols, FUNNEL_METRICS);
  var pc = planPctSignCols_(wh.plan);
  var partialCols = planPartialCols_(wh.plan);

  // ---- Tab 1: Funnel by Market ----
  var mNames = MARKETS.filter(function (m) { return a.market[m]; }).concat(a.market['Other'] ? ['Other'] : []);
  var m1rows = mNames.map(function (m) { return wideRow_(m, a.market[m], wh.plan); });
  m1rows.push(wideRow_('TOTAL', a.totals, wh.plan));
  buildTab_(ss, 'Live Funnel by Market', [
    { type: 'title', text: 'Funnel by Market — ' + cols[0].label + ' – ' + cols[cols.length - 1].label },
    { type: 'subtitle', text: srcLine }, { type: 'caption', text: caption }, { type: 'blank' },
    { type: 'table', headers: wh.headers, rows: m1rows,
      opts: { partialCols: partialCols, pctCols: pc.pct, signCols: pc.sign, totalRows: [m1rows.length - 1], freeze: true } }
  ]);

  // ---- Tab 2: Funnel by Source ----
  var sNames = SOURCE_ORDER.filter(function (s) { return a.source[s]; })
    .concat(Object.keys(a.source).filter(function (s) { return SOURCE_ORDER.indexOf(s) < 0; }));
  var s2rows = sNames.map(function (s) { return wideRow_(s, a.source[s], wh.plan); });
  s2rows.push(wideRow_('TOTAL', a.totals, wh.plan));
  var sh2 = wideHeaders_(cols, FUNNEL_METRICS); sh2.headers[0] = 'Original Source';
  buildTab_(ss, 'Live Funnel by Source', [
    { type: 'title', text: 'Funnel by Original Source — ' + cols[0].label + ' – ' + cols[cols.length - 1].label },
    { type: 'subtitle', text: srcLine }, { type: 'caption', text: caption }, { type: 'blank' },
    { type: 'table', headers: sh2.headers, rows: s2rows,
      opts: { partialCols: partialCols, pctCols: pc.pct, signCols: pc.sign, totalRows: [s2rows.length - 1], freeze: true } }
  ]);

  // ---- Tab 3: Market x Source ----
  var msHeaders = wideHeaders_(cols, FUNNEL_METRICS); msHeaders.headers[0] = 'Market / Source';
  var msRows = [], groupRows = [], subtotalRows = [];
  mNames.forEach(function (m) {
    var srcMap = a.marketSource[m] || {};
    var order = SOURCE_ORDER.filter(function (s) { return srcMap[s]; })
      .concat(Object.keys(srcMap).filter(function (s) { return SOURCE_ORDER.indexOf(s) < 0; }));
    groupRows.push(msRows.length);
    var head = [m]; for (var i = 1; i < msHeaders.headers.length; i++) head.push('');
    msRows.push(head);
    order.forEach(function (s) { msRows.push(wideRow_(s, srcMap[s], wh.plan)); });
    subtotalRows.push(msRows.length);
    var sub = wideRow_(m + ' — Total', a.market[m], wh.plan);
    msRows.push(sub);
  });
  buildTab_(ss, 'Live Market x Source', [
    { type: 'title', text: 'Funnel by Market, split by Source — ' + cols[0].label + ' – ' + cols[cols.length - 1].label },
    { type: 'subtitle', text: srcLine },
    { type: 'caption', text: caption + ' Market subtotals reconcile to Live Funnel by Market.' }, { type: 'blank' },
    { type: 'table', headers: msHeaders.headers, rows: msRows,
      opts: { partialCols: partialCols, pctCols: pc.pct, signCols: pc.sign, groupRows: groupRows, subtotalRows: subtotalRows, freeze: true } }
  ]);

  // ---- Tab 4: Key Paid+Owned ----
  var kNames = MARKETS.filter(function (m) { return a.keyMarket[m]; }).concat(a.keyMarket['Other'] ? ['Other'] : []);
  var k4rows = kNames.map(function (m) { return wideRow_(m, a.keyMarket[m], wh.plan); });
  k4rows.push(wideRow_('TOTAL', a.keyTotals, wh.plan));
  buildTab_(ss, 'Live Funnel - Key Paid+Owned', [
    { type: 'title', text: 'Funnel by Market — Paid Search / Paid Social / Organic Social / Email Marketing only' },
    { type: 'subtitle', text: srcLine },
    { type: 'caption', text: caption + ' Low volume — small/zero cells expected.' }, { type: 'blank' },
    { type: 'table', headers: wh.headers, rows: k4rows,
      opts: { partialCols: partialCols, pctCols: pc.pct, signCols: pc.sign, totalRows: [k4rows.length - 1], freeze: true } }
  ]);

  // ---- Tab 5: Weekly Trend ----
  var wRows = [], partialRows = [], totReg = 0, totRvf = 0, totMql = 0;
  a.weeks.forEach(function (w, i) {
    var x = a.weekly[w.key] || blankCell_();
    totReg += x.reg; totRvf += x.rvf; totMql += x.mql;
    if (w.partial) partialRows.push(i);
    wRows.push([w.label + (w.partial ? ' *' : ''), dash_(x.reg), dash_(x.rvf), dash_(x.mql), pctVal_(x.rvf, x.reg), pctVal_(x.mql, x.reg)]);
  });
  wRows.push(['TOTAL', totReg, totRvf, totMql, pctVal_(totRvf, totReg), pctVal_(totMql, totReg)]);
  buildTab_(ss, 'Live Weekly Trend', [
    { type: 'title', text: 'Weekly Funnel Trend — w/c Mondays (' + a.weeks[0].label + ' – ' + a.weeks[a.weeks.length - 1].label + ')' },
    { type: 'subtitle', text: 'Total across all markets, by registration week. Source: HubSpot (live), refreshed ' + stamp + '.' },
    { type: 'caption', text: 'MQL = cumulative "reached MQL" (MQL or beyond). First and last weeks are partial, marked *.' }, { type: 'blank' },
    { type: 'table', headers: ['Week (w/c)', 'Reg', 'RVF', 'MQL', 'RVF%', 'MQL%'], rows: wRows,
      opts: { pctCols: [4, 5], partialRows: partialRows, totalRows: [wRows.length - 1], freeze: true } }
  ]);

  // ---- Tab A: Lifecycle by Month ----
  writeLifecycleTab_(ss, a, cols, stamp);
  // ---- Tab B: Why PQLs are stuck ----
  writePqlTab_(ss, a, stamp);
  // ---- Tab C: MQL statistics ----
  writeMqlTab_(ss, a, cols, stamp);
  // ---- Methodology stamp ----
  writeMethodologyTab_(ss, a, stamp);
}

function writeLifecycleTab_(ss, a, cols, stamp) {
  var headers = ['Stage'].concat(cols.map(function (c) { return c.label + (c.partial ? '*' : ''); }))
    .concat(['Total', '% of Reg', 'Step conv.']);
  var stages = [['Registrations', 'reg'], ['Reached Pre-Qualified', 'pql'], ['Reached MQL', 'mql'], ['Reached SQL', 'sql'], ['Reached Investor', 'inv']];
  var totalReg = 0; cols.forEach(function (c) { totalReg += a.cascade[c.key].reg; });
  var rows = [], prevTotal = null;
  stages.forEach(function (st) {
    var row = [st[0]], sum = 0;
    cols.forEach(function (c) { var v = a.cascade[c.key][st[1]]; sum += v; row.push(dash_(v)); });
    row.push(sum);
    row.push(pctVal_(sum, totalReg));
    row.push(prevTotal === null ? '' : pctVal_(sum, prevTotal));
    rows.push(row); prevTotal = sum;
  });
  var partialCols = []; cols.forEach(function (c, i) { if (c.partial) partialCols.push(i + 1); });
  var pctIdx = headers.length - 2, stepIdx = headers.length - 1;
  buildTab_(ss, 'Live Lifecycle by Month', [
    { type: 'title', text: 'Lifecycle Progression by Registration Month' },
    { type: 'subtitle', text: 'How ' + cols[0].label + '–' + cols[cols.length - 1].label + ' registrations have progressed. Source: HubSpot (live), refreshed ' + stamp + ' (' + a.n + ' contacts).' },
    { type: 'caption', text: 'Cumulative basis: each row counts contacts who reached that stage or beyond. Current month is partial. Disqualified, Prospect and Unresponsive are off-path and excluded.' }, { type: 'blank' },
    { type: 'table', headers: headers, rows: rows, opts: { partialCols: partialCols, pctCols: [pctIdx, stepIdx], freeze: true } }
  ]);
}

function writePqlTab_(ss, a, stamp) {
  var p = a.pql, total = p.total || 0;
  var suitRows = SUIT_ORDER.filter(function (k) { return p.suit[k]; }).map(function (k) {
    return [SUIT_LABELS[k], p.suit[k], pctVal_(p.suit[k], total)];
  });
  suitRows.push(['Total', total, '']);
  var mktRows = Object.keys(p.market).sort(function (x, y) { return p.market[y] - p.market[x]; })
    .map(function (m) { return [m, p.market[m], pctVal_(p.market[m], total)]; });
  mktRows.push(['Total', total, '']);
  var notSub = p.suit['NOT_SUBMITTED'] || 0, blocked = p.suit['BLOCKED'] || 0;
  var beforeSuit = notSub + blocked;
  var headline1 = 'Suitability is the wall: ' + notSub + ' (' + pctInt_(notSub, total) + ') have not submitted the questionnaire and ' + blocked + ' (' + pctInt_(blocked, total) + ') are Blocked — roughly ' + pctInt_(beforeSuit, total) + ' are stuck at or before suitability.';
  var headline2 = p.noQuestionnaire + ' of ' + total + ' never completed the questionnaire; ' + p.idVerified + ' are ID-verified.';
  var headline3 = (p.verifiedStuck || 0) + ' (' + pctInt_(p.verifiedStuck || 0, total) + ') are fully Verified yet still Pre-Qualified — the warmest re-engagement targets.';
  buildTab_(ss, 'Live Why PQLs are stuck', [
    { type: 'title', text: 'Why Pre-Qualified leads are still Pre-Qualified' },
    { type: 'subtitle', text: total + ' contacts are currently Pre-Qualified and have not progressed to MQL. Source: HubSpot (live), refreshed ' + stamp + '.' },
    { type: 'caption', text: 'Headline' },
    { type: 'caption', text: headline1 }, { type: 'caption', text: headline2 }, { type: 'caption', text: headline3 }, { type: 'blank' },
    { type: 'table', headers: ['Suitability status', 'Contacts', '% of PQL'], rows: suitRows, opts: { pctCols: [2], totalRows: [suitRows.length - 1], freeze: true } },
    { type: 'blank' },
    { type: 'table', headers: ['By market (Territory)', 'Contacts', '% of PQL'], rows: mktRows, opts: { pctCols: [2], totalRows: [mktRows.length - 1] } }
  ]);
}

function writeMqlTab_(ss, a, cols, stamp) {
  var m = a.mql, still = m.still || 0;
  var monthRows = cols.map(function (c) {
    var v = m.month[c.key] || 0;
    return [c.label + (c.partial ? ' (partial)' : ''), v, pctVal_(v, still)];
  }).filter(function (r) { return r[1] > 0; });
  monthRows.push(['Total', still, '']);
  var mktRows = Object.keys(m.market).sort(function (x, y) { return m.market[y] - m.market[x]; })
    .map(function (k) { return [k, m.market[k], pctVal_(m.market[k], still)]; });
  mktRows.push(['Total', still, '']);
  var srcRows = Object.keys(m.source).sort(function (x, y) { return m.source[y] - m.source[x]; })
    .map(function (k) { return [k, m.source[k], pctVal_(m.source[k], still)]; });
  var suitRows = SUIT_ORDER.filter(function (k) { return m.suit[k]; }).map(function (k) {
    return [SUIT_LABELS[k], m.suit[k], pctVal_(m.suit[k], still)];
  });
  suitRows.push(['Total', still, '']);
  var onward = m.everReached > 0 ? (m.everReached - still) / m.everReached : 0;
  var med = median_(m.lags);
  var headline1 = m.everReached + ' contacts have ever reached MQL; ' + still + ' are still at MQL and ' + (m.everReached - still) + ' progressed to SQL or beyond, an onward conversion of ' + Math.round(onward * 100) + '%.';
  var qDone = m.questionnaireDone || 0;
  var verified = m.suit['VERIFIED'] || 0;
  var headline2 = 'MQLs are well-qualified: ' + verified + ' (' + pctInt_(verified, still) + ') are suitability-Verified and ' + qDone + ' (' + pctInt_(qDone, still) + ') completed the questionnaire.';
  var sameDayPct = qDone > 0 ? Math.round(m.sameDay / qDone * 100) : 0;
  var headline3 = 'Speed: ' + sameDayPct + '% of MQLs completed suitability the same day they registered (median lag ' + (med === null ? 'n/a' : med + ' day' + (med === 1 ? '' : 's')) + ').';
  buildTab_(ss, 'Live MQL statistics', [
    { type: 'title', text: 'MQL statistics' },
    { type: 'subtitle', text: still + ' contacts are currently Marketing Qualified Leads (' + cols[0].label + '–' + cols[cols.length - 1].label + ' registrations). Source: HubSpot (live), refreshed ' + stamp + '.' },
    { type: 'caption', text: 'Headline' },
    { type: 'caption', text: headline1 }, { type: 'caption', text: headline2 }, { type: 'caption', text: headline3 }, { type: 'blank' },
    { type: 'table', headers: ['By registration month', 'Contacts', '% of MQL'], rows: monthRows, opts: { pctCols: [2], totalRows: [monthRows.length - 1], freeze: true } },
    { type: 'blank' },
    { type: 'table', headers: ['By market (Territory)', 'Contacts', '% of MQL'], rows: mktRows, opts: { pctCols: [2], totalRows: [mktRows.length - 1] } },
    { type: 'blank' },
    { type: 'table', headers: ['By Original Source', 'Contacts', '% of MQL'], rows: srcRows, opts: { pctCols: [2] } },
    { type: 'blank' },
    { type: 'table', headers: ['Suitability status', 'Contacts', '% of MQL'], rows: suitRows, opts: { pctCols: [2], totalRows: [suitRows.length - 1] } }
  ]);
}

function pctInt_(num, den) { return den > 0 ? Math.round(num / den * 100) + '%' : '0%'; }

function writeMethodologyTab_(ss, a, stamp) {
  buildTab_(ss, 'Live Methodology', [
    { type: 'title', text: 'Methodology & Definitions (live refresh)' },
    { type: 'subtitle', text: 'Last updated ' + Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd HH:mm') + ' ' + TZ + ' — ' + a.n + ' contacts pulled.' }, { type: 'blank' },
    { type: 'table', headers: ['Item', 'Definition'], rows: [
      ['Cohort', 'registration_date from ' + Utilities.formatDate(new Date(historyStartMs_()), TZ, 'MMM yyyy') + ' to now AND partner_name in {Moonfare, Moonfare US, Moonfare Private Office}.'],
      ['Market', 'territory property (US, UK, DACH, BeNeLux, APAC, ROW, Israel; others → Other).'],
      ['Source', 'hs_analytics_source (Original Source, HubSpot first-touch).'],
      ['RVF', 'UK (any date): suitability VERIFIED + UK investor_type. Before 19 May, non-UK: suitability Pending/Verified. On/after 19 May, D2I country: your_goals_with_moonfare OR d2i_estimated_financial_portfolio_size known. On/after 19 May, other: Pending/Verified.'],
      ['MQL (funnel/market/source)', 'current lifecyclestage = marketingqualifiedlead (point-in-time snapshot).'],
      ['MQL (weekly trend)', 'cumulative "reached MQL" — current stage MQL or beyond.'],
      ['Lifecycle cascade (Tab A)', 'cumulative reached-at-least; Disqualified / Prospect / Unresponsive off-path, excluded from reached counts.'],
      ['PQL analysis (Tab B)', 'current lifecyclestage = lead (Pre-Qualified). Suitability status, questionnaire completion and id_verified read directly.'],
      ['MQL statistics (Tab C)', 'current lifecyclestage = marketingqualifiedlead. Suitability lag = days from registration_date to completed_suitability_questionnaire_date.'],
      ['History', 'Every month from the anchor to now, and every ISO week, is recomputed each run from current HubSpot state, so new period columns appear automatically. Registration cohorts are stable; RVF/MQL are point-in-time and mature as contacts progress.'],
      ['Caveat', 'The current month and the first/last weeks are partial (highlighted / marked *). Lifecycle stage is a point-in-time snapshot.']
    ], opts: { freeze: true } }
  ]);
  var sh = ss.getSheetByName('Live Methodology');
  if (sh) { sh.setColumnWidth(1, 220); sh.setColumnWidth(2, 760); sh.getRange(1, 2, sh.getMaxRows(), 1).setWrap(true); }
}

// ---------- Node test hook (ignored by Apps Script) ----------
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    parseDate_: parseDate_, weekStart_: weekStart_, monthCols_: monthCols_, weekCols_: weekCols_,
    isRVF_: isRVF_, sourceLabel_: sourceLabel_, marketOf_: marketOf_, aggregate_: aggregate_,
    wideHeaders_: wideHeaders_, wideRow_: wideRow_, median_: median_, pctVal_: pctVal_
  };
}
