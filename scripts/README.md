# Pass B write tooling — BD CRM Screening

`passb_hubspot.py` is the write channel for **Pass B** of the BD CRM screening
automation. The connected HubSpot MCP is **read-only** and cannot see the Leads
object, so approved qualify decisions are written via a **HubSpot private-app
token + REST** (base `https://api.hubapi.com`). The write logic here mirrors the
"Pass B write path" section of [`../crm-screening.md`](../crm-screening.md) —
that playbook stays the single source of truth.

Stdlib only (Python 3, `urllib`) — no `pip install` needed in a scheduled session.

## One-time setup — create the sandbox + private-app token (HubSpot admin)

This is a HubSpot **UI** action; no API/MCP can mint a private-app token.

1. **Create/enter a Standard sandbox:** HubSpot → **Settings → Account
   Management → Sandboxes** → *Create standard sandbox* (or open an existing
   one). The sandbox is a **separate portal** with its own portal ID and its own
   data — the production token/MCP will not work against it.
2. **In the SANDBOX portal:** **Settings → Integrations → Private Apps →
   Create a private app**.
3. **Scopes** (Auth tab):
   - `crm.objects.contacts.read`
   - `crm.objects.contacts.write`
   - `crm.objects.leads.read`
   - `crm.objects.leads.write`
   - `crm.schemas.contacts.read`

   Note: `crm.objects.leads.read` is enough to read the Lead **property list**
   (`GET /crm/v3/properties/leads`) — there is no separate "leads schema" scope
   in the picker. Only if that call returns **403** do you need to also add
   `crm.schemas.custom.read`.
4. **Create**, then **copy the access token**.
5. **Store it as an env var in the screening session** (never commit it):
   ```bash
   export HUBSPOT_BD_WRITE_TOKEN='pat-...'
   ```

## Confirm the sandbox + Lead property names, then verify Pass B on ONE lead

```bash
# 0) Confirm we're pointed at the SANDBOX, not prod
python3 scripts/passb_hubspot.py whoami

# 1) Discover the Lead-object internal names + enum values.
#    Sandboxes may NOT mirror prod's custom properties — confirm here.
python3 scripts/passb_hubspot.py props leads --grep business
python3 scripts/passb_hubspot.py props leads --grep "lead type"

# 2) Record them: copy lead_props.json.example -> lead_props.json and fill in
#    the real internal names + option values from step 1.
cp scripts/lead_props.json.example scripts/lead_props.json
#    ...edit scripts/lead_props.json...

# 3) (If the sandbox has no PQL data) seed a throwaway contact + associated lead
python3 scripts/passb_hubspot.py seed-test

# 4) Dry-run the qualify action (prints what it WOULD write; no changes)
python3 scripts/passb_hubspot.py qualify --contact-id <ID>

# 5) Apply for real on that ONE lead, then verify
python3 scripts/passb_hubspot.py qualify --contact-id <ID> --apply
```

## What `qualify` does (matches the playbook exactly)

1. `PATCH /crm/v3/objects/contacts/{id}` → `lifecyclestage = marketingqualifiedlead`
2. `GET  /crm/v4/objects/contacts/{id}/associations/leads` → resolve the Lead id
3. `PATCH /crm/v3/objects/leads/{leadId}` → Business Development = `Yes`,
   Lead type = `New Business` (internal names read from `lead_props.json`)
4. **Owner is NOT set** — the native HubSpot by-country workflow assigns it once
   the lifecycle stage changes.

## Safety rails

- **No token → clear error.** Nothing runs without `HUBSPOT_BD_WRITE_TOKEN`.
- **Writes refuse on non-sandbox portals.** `seed-test` and `qualify --apply`
  call `whoami` first and abort unless `accountType` is a sandbox/developer-test
  portal (override only with the hidden `--allow-prod` flag).
- **`qualify` is dry-run by default.** Writes happen only with `--apply`.
- **Unconfirmed Lead names block writes.** `qualify --apply` refuses to PATCH the
  lead unless `lead_props.json` exists with real internal names.
- **`lead_props.json` (real, filled-in) is safe to commit** once confirmed — it
  holds no secrets, only property names. The **token is never written to disk.**
