# n8n — BD CRM Screening Pass B (reaction → HubSpot)

Event-driven **Pass B**: the moment an approver reacts ✅ on a screening proposal
in Slack, this workflow writes the qualify action to HubSpot. **No returning to
Claude.** Pass A (enrich + score + post proposals) stays a scheduled Claude
session; this handles only the deterministic write.

`bd-crm-passb.workflow.json` is importable into n8n (**Workflows → Import from
File**). It reuses the exact REST calls proven against the sandbox.

## Flow
1. **Webhook** receives Slack Events API callbacks (and answers Slack's
   `url_verification` challenge automatically).
2. **Gate** — proceed only if it's a `reaction_added` with the ✅ emoji
   (`white_check_mark`) in the screening channel; everything else stops.
3. **Get Slack message** (`conversations.history`) → read the reacted message.
4. **Extract contactId** — parsed from the HubSpot link in the message
   (`.../record/0-1/<contactId>`). No external state needed.
5. **HubSpot: contact → MQL** (`PATCH /crm/v3/objects/contacts/{id}`).
6. **Get associated lead** (`GET /crm/v4/objects/contacts/{id}/associations/leads`).
7. **HubSpot: lead → MQL stage + flags** (`PATCH /crm/v3/objects/leads/{leadId}`:
   `hs_pipeline_stage=159139484`, `business_development=true`, `hs_lead_type=NEW_BUSINESS`).
8. **Slack: confirm in thread**.

## One-time setup
1. **Create two n8n credentials** (Credentials → New → *Header Auth*):
   - **"HubSpot BD Write"** → Name `Authorization`, Value `Bearer <HUBSPOT_BD_WRITE_TOKEN>`
   - **"Slack Bot Token"** → Name `Authorization`, Value `Bearer <xoxb-… slack bot token>`
   After import, open the 4 HTTP nodes and select the matching credential
   (placeholders are `REPLACE_HUBSPOT_CRED` / `REPLACE_SLACK_CRED`).
2. **Slack app**: add a bot with scopes `reactions:read`, `channels:history`
   (or `groups:history` for a private channel), `chat:write`; invite it to the
   channel. Under **Event Subscriptions**, set the Request URL to this workflow's
   **Production webhook URL** (from the Webhook node) and subscribe to the bot
   event **`reaction_added`**. n8n auto-answers the verification challenge.
3. **Activate** the workflow.

## Configure for your portal (edit before production)
- **Channel id** — in the *Gate* node (`CHANNEL`), currently `C0BA557N4UA` (#test-claude).
- **MQL stage id** — in *HubSpot: lead → MQL stage + flags*, `hs_pipeline_stage`
  is `159139484` (sandbox). **Re-confirm against prod** (`GET /crm/v3/pipelines/leads`);
  stage ids can differ per portal.
- **Lead flags** — `business_development`, `hs_lead_type` match the confirmed
  sandbox mapping (see `../scripts/lead_props.json`).
- The token in the HubSpot credential decides **which portal** is written —
  sandbox token for testing, prod token to go live.

## Notes
- Only ✅ triggers a write; ❌ / other reactions are ignored (skips need no write).
- The workflow is **stateless** — it recovers the contact id from the message
  link, so Pass A and Pass B need not share a database.
- Node `typeVersion`s target a recent n8n; if your instance differs, n8n will
  offer to migrate on import. Review the 4 HTTP nodes' credential assignment
  after importing.
