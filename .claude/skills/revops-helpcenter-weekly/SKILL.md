---
name: revops-helpcenter-weekly
description: >
  Generate the weekly Rev Ops HelpCenter (COHC) ticket report and post it to the
  #team-rev-ops Slack channel. Use this skill when the user asks for the "weekly
  helpcenter report", "COHC weekly report", "rev ops ticket report", or any
  recurring summary of open HelpCenter tickets. Produces: total open tickets, a
  department breakdown (text pie), ticket-type breakdown, a Sales-department
  drill-down, and an individually-listed set of open Sales bugs — each with
  week-over-week deltas versus the previous report. Renders the full visual
  report inline in Claude AND posts a text version to Slack #team-rev-ops.
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
6. **Latest status on top-priority tickets** — for each top-priority ticket, its most recent *human* comment (date, author, gist), posted as a thread reply
7. **Open Sales bugs** — listed individually (ticket key + title); no thematic grouping

Delivery: rendered inline in Claude (full charts) AND posted as a text/table message to
Slack `#team-rev-ops`.

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
> bugs individually (key + title); it does not attempt to categorize them.

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

### Step 3b — Latest status on top-priority tickets

For each top-priority Sales ticket from Step 3 (High/Highest), fetch its comments and extract the
most recent **human** comment to summarize what's actually moving. One call per ticket:
`Atlassian:getJiraIssue` with `cloudId` (hardcoded), `issueIdOrKey` = the key, and
`fields: ["comment"]`.

Rules for picking the comment:
- Comments are in `fields.comment.comments`, oldest first — the latest is the LAST element.
- **IGNORE bot/automation comments.** Skip any whose `author.displayName` is `"Automation for Jira"`
  (these are long auto-generated "Based on the analysis of…" / "Similar tickets" write-ups, not real
  status). Walk backwards from the end and take the first NON-bot comment.
- If a ticket has zero human comments (e.g. only the original request, or only bot comments), say so
  plainly: "No comments logged since creation" — do not invent a status.
- For the chosen comment, capture its date, author display name, and a one-line gist (paraphrase —
  do NOT paste the full comment body, which can be very long; keep it under ~30 words).
- Note Jira comment bodies contain ADF/markdown markup (`<custom data-type="mention">`, image blobs,
  links). Strip these to plain text for the gist.

This data feeds a third thread reply in Step 6 (c). It does not change the main post.

### Step 4 — Read the previous snapshot (for deltas)

Read the most recent prior report from Slack to recover last week's numbers. The snapshot is
NOT in the main report message — it lives in a thread reply under it (see Step 6).
- Call `Slack:slack_search_public_and_private` with
  `query: "HelpCenter weekly report in:#team-rev-ops"`, `sort: "timestamp"`, `sort_dir: "desc"`, `limit: 3`.
- Take the newest matching report message and read its thread with `Slack:slack_read_thread`
  (`channel_id: "C0877V4P09L"`, `message_ts` = that message's ts). Find the reply whose text
  begins with `SNAPSHOT:` and parse the JSON after the marker.
- If no prior report, or no snapshot reply is found, proceed WITHOUT deltas and note "no prior
  week on record".

Delta = current − prior, shown per metric as `▲N` (up), `▼N` (down), or `▬` (no change).
Remember for ticket BACKLOG, ▲ (more open tickets) is generally bad and ▼ is good — do not
attach value judgments, just show the direction.

### Step 5 — Render inline in Claude

Use the visualizer (`visualize:read_me` with `["data_viz","chart"]`, then `visualize:show_widget`)
to render the full visual report: metric cards (with deltas), a real department **pie chart**,
a ticket-type bar, and the Sales drill-down. Put the written tables, the top-priority Sales
ticket list, and the open-Sales-bug list in the response prose (not inside the widget). Follow
the house visual rules in the read_me.

### Step 6 — Post to Slack

Three posts: (a) the clean report as the main message, then two thread replies under it — (b) the
machine-readable snapshot, and (c) the latest-status update on top-priority tickets.

**Quiet ticket links.** Every Jira ticket key in the message MUST be written as a Slack inline
link so it renders as a clickable key WITHOUT unfurling into a big preview card:
`<https://moonfare.atlassian.net/browse/COHC-XXXX|COHC-XXXX>`. Never paste a bare
`https://...browse/COHC-XXXX` URL — bare URLs trigger the Jira-Slack integration to expand each
ticket into a full card, which is the overwhelming wall the user wants gone. (If links still
unfurl after this, that is a workspace-level Jira app setting outside this skill's control —
tell the user it's an admin toggle.)

**(a) Main message** — `Slack:slack_send_message`, `channel_id: "C0877V4P09L"`. Template:

```
*Rev Ops HelpCenter — Weekly Report (<DATE>)*

*Open tickets:* <N>  (<DELTA vs last week>)

*By department*
` ` `
Sales        ████████░░  <pct>%  (<n>)   <delta>
Marketing    ███░░░░░░░  <pct>%  (<n>)   <delta>
...
Unassigned   ██░░░░░░░░  <pct>%  (<n>)   <delta>
` ` `

*By type*
• Bug — <n> (<delta>)
• Support — <n> (<delta>)
• New Feature — <n> (<delta>)

*Sales drill-down*  (<n> tickets, <pct>% of all open, <delta>)
By type: Bug <n>, Support <n>, New Feature <n>
By status: <status> <n>, ...

*Top-priority Sales tickets*  (High / Highest)
• <COHC-XXXX link> — <title>  (<type>, <status>, <priority>)
• ...
[or: _none open at High/Highest_]

*Open Sales bugs*
• <COHC-XXXX link> — <title>
• <COHC-XXXX link> — <title>
...
```

Note: the embedded department block uses a real triple-backtick fence in Slack (shown above with
spaces so it nests in this doc). NO trailing tagline and NO snapshot line in the main message — it
ends after the bug list. Build the text bar with 10 block cells: `filled = round(pct/10)`, then
`"█"*filled + "░"*(10-filled)`. Round every displayed number.

**(b) Snapshot thread reply** — capture the `message_ts` returned by the main post. Then call
`Slack:slack_send_message` again with the SAME `channel_id` and `thread_ts` set to that
`message_ts`, posting only:

```
SNAPSHOT: {"date":"<ISO date>","total":<N>,"by_dept":{...},"by_type":{...},"sales":<n>,"sales_by_type":{...}}
```

This thread reply is the hidden state next week's Step 4 reads back. It keeps the main channel
post clean while preserving deltas. Valid compact JSON, prefixed exactly with `SNAPSHOT: `.

**(c) Status thread reply** — post the top-priority status update (from Step 3b) as a SECOND thread
reply, using the SAME `thread_ts` as (b). Use quiet ticket links (`<url|KEY>`). Template:

```
*Latest status — top-priority Sales tickets*  (as of <DATE>)

• <COHC-XXXX link> — <title>  (_<status>_)
<date> (<author>): <one-line gist>.   [or: No comments logged since creation.]
• ...
```

Keep each gist to one line. This reply is human-facing context; order it the same as the
top-priority list in the main post.

After posting all three (main + snapshot reply + status reply), return the main message's
permalink to the user.

---

## Notes & failure modes

- **Never silently skip a metric.** If a query returns nothing for a section, show it as 0, not absent.
- **Department field null** → "Unassigned" bucket; don't drop those tickets from the total.
- **No file upload to Slack.** The current Slack toolset posts text only; the graphical pie lives in the Claude-inline render. The Slack message uses the text bar instead. If a future run has a Slack file-upload tool available, the chart image MAY be attached, but do not assume it.
- **More than ~100 open tickets** → paginate the JQL search; the board has not approached this, but don't assume the first page is complete without checking `isLast`.
- **First ever run** → no prior snapshot; produce the report with deltas omitted and say so.
