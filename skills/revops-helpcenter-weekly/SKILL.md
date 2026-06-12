---
name: revops-helpcenter-weekly
description: >
  Generate the weekly Rev Ops HelpCenter (COHC) ticket report and post it to the
  #team-rev-ops Slack channel. Use this skill when the user asks for the "weekly
  helpcenter report", "COHC weekly report", "rev ops ticket report", or any
  recurring summary of open HelpCenter tickets. Produces: total open tickets, a
  department breakdown (text pie), ticket-type breakdown, a Sales-department
  drill-down, and an individually-listed set of open Sales bugs — each with
  week-over-week deltas versus the previous report. Has two modes: POST mode
  (default) renders inline in Claude AND posts a text version to Slack
  #team-rev-ops; REVIEW mode renders inline in Claude ONLY and posts nothing,
  for the reviewer to check before deciding to share.
---

# Weekly Rev Ops HelpCenter Report

## What this produces

A point-in-time snapshot of open tickets on the COHC "Rev Ops Helpcenter" board, with
week-over-week deltas, containing in order:

1. **Total open tickets** (headline number + delta)
2. **Department breakdown** — share of open tickets per department (text pie in Slack, real pie chart inline in Claude)
3. **Ticket-type breakdown** — Bug / Support / New Feature / etc.
4. **Sales drill-down** — count and % of open tickets from the Sales department, split by type and status
5. **Top-priority Sales tickets** — open Sales tickets at High or Highest priority, listed most-urgent-first (key, title, type, status, priority)
6. **Open Sales bugs** — listed individually (ticket key + title) for the reviewer to assess; no thematic grouping

Delivery: rendered inline in Claude (full charts) AND posted as a text/table message to
Slack `#team-rev-ops`.

---

## Modes

This skill runs in one of two modes. Determine the mode from how it was invoked:

- **POST mode (default).** Use when the request is a plain run ("run the weekly helpcenter
  report", "execute the weekly report") or explicitly says to post/send/publish. Does the full
  procedure including Step 6 (post to Slack).
- **REVIEW mode.** Use when the request asks for a draft, preview, or review — e.g. contains
  "review", "draft", "preview", "for me to check", "don't post", "dry run", or "before posting".
  Identical to POST mode EXCEPT it STOPS after Step 5: it renders the full report inline in
  Claude and does NOT call Slack at all (no post, and the snapshot is not written anywhere).

When ambiguous, prefer REVIEW mode and ask the user whether to post — it is always safe to show
the report without sending it, but a wrongful post to the team channel cannot be unsent.

Note on deltas in REVIEW mode: Step 4 still reads the last posted report from Slack as the
baseline, so deltas are shown normally. Because REVIEW mode does not post, it does NOT create a
new baseline — running REVIEW any number of times does not affect next week's deltas. Only a
POST-mode run advances the baseline.

---

## Hardcoded constants — DO NOT rediscover these each run

| Thing | Value |
|---|---|
| Atlassian cloudId | `7dbeed77-addb-4cd2-8177-120c310c1db9` |
| Jira project key | `COHC` (name: "Rev Ops Helpcenter") |
| Slack channel | `#team-rev-ops` → channel_id `C0877V4P09L` |
| "Open" definition | `status NOT IN (Declined, Done)` |
| Department field | `customfield_10354` (the "Department[Dropdown]" field) |
| Sales option | value `"Sales"`, option id `10689` |
| Bug-topic field | `customfield_12297` — **UNRELIABLE**, see note below |

> **Bug-topic field caveat.** `customfield_12297` is set to the literal string `"Bug"`
> on every bug ticket, so it does NOT segment topics. IGNORE it. The report lists open Sales
> bugs individually (key + title) for the reviewer; it does not attempt to categorize them.

---

## Procedure

### Step 1 — Query open tickets

Call `Atlassian:searchJiraIssuesUsingJql` with:
- `cloudId`: the hardcoded cloudId above
- `jql`: `project = COHC AND status NOT IN (Declined, Done) ORDER BY issuetype, created DESC`
- `maxResults`: `100`
- `fields`: `["summary", "status", "issuetype", "created", "priority", "customfield_10354"]`

This returns every open ticket with its department. Note `customfield_10354` may be `null`
(no department set) — bucket those as "Unassigned" in the department breakdown.

If the result is returned via a stored tool-results file (large payload), read it with
`bash`/python (`json.loads` the inner `text` field) rather than assuming inline JSON.

### Step 2 — Identify the open Sales bugs

The report lists open Sales bugs individually. The Step 1 query already returns `summary`
(title) for every ticket, which is all that's needed for the list. Filter to
`customfield_10354.value == "Sales"` AND `issuetype.name == "Bug"` and keep each ticket's
key + title. Descriptions are NOT required for the report and need not be fetched.

### Step 3 — Compute the metrics

- Total open count.
- Count by department (group on `customfield_10354.value`; null → "Unassigned").
- Count by issue type (`issuetype.name`).
- Sales subset: filter to `customfield_10354.value == "Sales"`. Within it, break down by
  type and by status. Compute Sales as a % of total open (`round(100 * sales / total)`).
- Top-priority Sales tickets: from the Sales subset, keep tickets whose `priority.name` is
  `Highest` or `High`. Sort by priority rank (Highest before High), then by created date
  (oldest first, so the most-aged urgent items surface). Keep key, title, type, status,
  priority for each. If none qualify, the section says "no High/Highest priority Sales
  tickets open" — do not omit it.
- Open Sales bugs: the list of `key — title` for each (from Step 2). No grouping.

### Step 4 — Read the previous snapshot (for deltas)

Read the most recent prior report from Slack to recover last week's numbers:
- Call `Slack:slack_search_public_and_private` with
  `query: "HelpCenter weekly report in:#team-rev-ops"`, `sort: "timestamp"`, `sort_dir: "desc"`, `limit: 3`.
- In the newest matching message, find the hidden snapshot line (see format in Step 6).
  Parse the JSON after the `SNAPSHOT:` marker.
- If no prior snapshot is found, proceed WITHOUT deltas and note "no prior week on record".

Delta = current − prior, shown per metric as `▲N` (up), `▼N` (down), or `▬` (no change).
Remember for ticket BACKLOG, ▲ (more open tickets) is generally bad and ▼ is good — do not
attach value judgments, just show the direction.

### Step 5 — Render inline in Claude

Use the visualizer (`visualize:read_me` with `["data_viz","chart"]`, then `visualize:show_widget`)
to render the full visual report: metric cards (with deltas), a real department **pie chart**,
a ticket-type bar, and the Sales drill-down. Put the written tables, the top-priority Sales
ticket list, and the open-Sales-bug list in the response prose (not inside the widget). Follow
the house visual rules in the read_me.

**If in REVIEW mode: STOP here.** Do not proceed to Step 6 and do not call Slack. After the
inline render, tell the user this is a draft that has not been posted, and that you can post it
to `#team-rev-ops` if they confirm. If they then confirm, run Step 6 to post it.

### Step 6 — Post to Slack (POST mode only)

Skip this entire step in REVIEW mode. In POST mode, build a markdown message (charts become
text). Use `Slack:slack_send_message` with `channel_id: "C0877V4P09L"`. Template:

```
*Rev Ops HelpCenter — Weekly Report (<DATE>)*

*Open tickets:* <N>  (<DELTA vs last week>)

*By department*
```​`
Sales        ████████░░  <pct>%  (<n>)   <delta>
Marketing    ███░░░░░░░  <pct>%  (<n>)   <delta>
...
Unassigned   ██░░░░░░░░  <pct>%  (<n>)   <delta>
```​`

*By type*
• Bug — <n> (<delta>)
• Support — <n> (<delta>)
• New Feature — <n> (<delta>)

*Sales drill-down*  (<n> tickets, <pct>% of all open, <delta>)
By type: Bug <n>, Support <n>, New Feature <n>
By status: <status> <n>, ...

*Top-priority Sales tickets*  (High / Highest)
• <KEY> — <title>  (<type>, <status>, <priority>)
• ...
[or: _none open at High/Highest_]

*Open Sales bugs*
• <KEY> — <title>
• <KEY> — <title>
...

_Numbers are point-in-time._
SNAPSHOT: {"date":"<ISO date>","total":<N>,"by_dept":{...},"by_type":{...},"sales":<n>}
```

Build the text bar with 10 block cells: `filled = round(pct/10)`, then
`"█"*filled + "░"*(10-filled)`. Round every displayed number.

The final `SNAPSHOT:` line is the hidden machine-readable state that next week's run reads in
Step 4. Keep it as the LAST line, valid compact JSON, prefixed exactly with `SNAPSHOT: `.

After posting, return the Slack message permalink to the user.

---

## Notes & failure modes

- **Never silently skip a metric.** If a query returns nothing for a section, show it as 0, not absent.
- **Department field null** → "Unassigned" bucket; don't drop those tickets from the total.
- **No file upload to Slack.** The current Slack toolset posts text only; the graphical pie lives in the Claude-inline render. The Slack message uses the text bar instead. If a future run has a Slack file-upload tool available, the chart image MAY be attached, but do not assume it.
- **More than ~100 open tickets** → paginate the JQL search; the board has not approached this, but don't assume the first page is complete without checking `isLast`.
- **First ever run** → no prior snapshot; produce the report with deltas omitted and say so.
- **Mode safety.** REVIEW mode must never call any Slack write tool. If unsure which mode was
  intended, default to REVIEW and ask before posting. A scheduled/automated invocation intended
  for unattended review should pass through REVIEW mode so nothing reaches the channel without a
  human confirming.
