#!/usr/bin/env python3
"""Pass B write helper for BD CRM Screening — HubSpot private-app REST.

Single source of truth for the write logic is crm-screening.md ("Pass B write
path"). This CLI implements exactly that path, plus the sandbox-confirmation
steps the setup session needs:

  whoami                     Identify the portal (id + accountType). Confirms
                             we are pointed at the SANDBOX, not prod.
  props OBJECT [--grep T]    Dump an object's properties (name/label/type +
                             enum options). Use `props leads` to confirm the
                             internal names + enum values for "Business
                             Development" and "Lead type".
  seed-test                  (sandbox only) Create a throwaway contact + an
                             associated lead so `qualify` has something to hit.
  qualify --contact-id ID    The Pass B qualify action on ONE contact:
                             lifecyclestage -> marketingqualifiedlead, then set
                             Business Development + Lead type on the associated
                             lead. DRY-RUN by default; pass --apply to write.

Auth: reads the private-app token from env HUBSPOT_BD_WRITE_TOKEN (never commit
it). Base URL https://api.hubapi.com.

SAFETY: any command that writes (seed-test, qualify --apply) refuses to run
unless the portal's accountType is a sandbox/developer-test, UNLESS you pass
--allow-prod explicitly. Verify on ONE lead before any batch.

Stdlib only (urllib) so it runs in any scheduled session with no pip install.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.hubapi.com"
TOKEN_ENV = "HUBSPOT_BD_WRITE_TOKEN"
# accountType values HubSpot returns for non-production portals.
SANDBOX_ACCOUNT_TYPES = {"SANDBOX", "DEVELOPER_TEST", "APP_DEVELOPER"}


def _token():
    tok = os.environ.get(TOKEN_ENV)
    if not tok:
        sys.exit(
            f"ERROR: env {TOKEN_ENV} is not set. Create the sandbox private app "
            "(see crm-screening.md), then export the token as "
            f"{TOKEN_ENV} in this session."
        )
    return tok


def _request(method, path, body=None, params=None):
    """Return (status_code, parsed_json_or_text). Never raises on HTTP error."""
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + _token())
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: network failure calling {method} {path}: {e}")


def _account():
    status, data = _request("GET", "/account-info/v3/details")
    if status != 200:
        sys.exit(f"ERROR: /account-info/v3/details returned {status}: {data}")
    return data


def _guard_sandbox(allow_prod):
    acct = _account()
    acct_type = acct.get("accountType", "UNKNOWN")
    portal = acct.get("portalId", "?")
    is_sandbox = acct_type in SANDBOX_ACCOUNT_TYPES
    label = "SANDBOX" if is_sandbox else "PRODUCTION-LIKE"
    print(f"Portal {portal} — accountType={acct_type} ({label})")
    if not is_sandbox and not allow_prod:
        sys.exit(
            "REFUSING to write: this portal does not look like a sandbox "
            f"(accountType={acct_type}). Re-run against the sandbox token, or "
            "pass --allow-prod if you really mean production."
        )
    return acct


# ---------- commands ----------
def cmd_whoami(args):
    acct = _account()
    print(json.dumps({
        "portalId": acct.get("portalId"),
        "accountType": acct.get("accountType"),
        "timeZone": acct.get("timeZone"),
        "companyCurrency": acct.get("companyCurrency"),
        "uiDomain": acct.get("uiDomain"),
    }, indent=2))
    if acct.get("accountType") in SANDBOX_ACCOUNT_TYPES:
        print("\n=> This is a SANDBOX portal. Safe to seed + test writes.")
    else:
        print("\n=> NOT a sandbox portal. Writes are blocked unless --allow-prod.")


def cmd_props(args):
    obj = args.object
    status, data = _request("GET", f"/crm/v3/properties/{obj}")
    if status != 200:
        sys.exit(f"ERROR: GET /crm/v3/properties/{obj} returned {status}: {data}")
    results = data.get("results", [])
    term = (args.grep or "").lower()
    shown = 0
    for p in sorted(results, key=lambda r: r.get("label", "")):
        name, label = p.get("name", ""), p.get("label", "")
        if term and term not in name.lower() and term not in label.lower():
            continue
        shown += 1
        line = f"  {label!r:40} internal={name!r} type={p.get('type')}/{p.get('fieldType')}"
        print(line)
        opts = p.get("options") or []
        for o in opts:
            print(f"       option: label={o.get('label')!r} value={o.get('value')!r}")
    print(f"\n{shown} propert{'y' if shown == 1 else 'ies'} shown"
          f"{f' matching {args.grep!r}' if term else ''} (of {len(results)} on {obj}).")
    if term:
        print("Copy the internal name + option value into scripts/lead_props.json "
              "so `qualify` uses confirmed names, not guesses.")


def cmd_seed_test(args):
    _guard_sandbox(args.allow_prod)
    stamp = str(int(time.time()))
    email = f"bd-screening-test+{stamp}@example.com"
    # 1) contact
    status, contact = _request("POST", "/crm/v3/objects/contacts", body={
        "properties": {
            "email": email,
            "firstname": "BD",
            "lastname": f"ScreeningTest {stamp}",
            "lifecyclestage": "lead",
        }
    })
    if status not in (200, 201):
        sys.exit(f"ERROR creating contact: {status}: {contact}")
    contact_id = contact["id"]
    print(f"Created contact {contact_id} <{email}>")
    # 2) associated lead (association type resolved by v4 default labels)
    lead_body = {
        "properties": {"hs_lead_name": f"BD ScreeningTest {stamp}"},
        "associations": [{
            "to": {"id": contact_id},
            "types": [{
                "associationCategory": "HUBSPOT_DEFINED",
                # 578 = lead -> contact primary (standard). If the sandbox
                # rejects it, run `props leads` and check association config.
                "associationTypeId": 578,
            }],
        }],
    }
    status, lead = _request("POST", "/crm/v3/objects/leads", body=lead_body)
    if status not in (200, 201):
        print(f"WARNING: could not auto-create associated lead ({status}): {lead}")
        print("Create the lead manually in the sandbox UI and associate it to "
              f"contact {contact_id}, or adjust associationTypeId.")
        return
    print(f"Created lead {lead['id']} associated to contact {contact_id}")
    print(f"\nNow verify Pass B:\n  python3 scripts/passb_hubspot.py qualify "
          f"--contact-id {contact_id} --apply")


def _load_lead_props():
    """Confirmed Lead-object mapping. Filled in after `props leads`."""
    path = os.path.join(os.path.dirname(__file__), "lead_props.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def cmd_qualify(args):
    contact_id = args.contact_id
    apply = args.apply
    mode = "APPLY (writing)" if apply else "DRY-RUN (no writes)"
    print(f"=== Pass B qualify — contact {contact_id} — {mode} ===")
    if apply:
        _guard_sandbox(args.allow_prod)

    lp = _load_lead_props()
    if lp is None:
        print("\nNOTE: scripts/lead_props.json not found — Lead-object internal "
              "names are UNCONFIRMED. Run `props leads` first and create it:")
        print('  {"business_development": {"name": "<internal>", "value": "Yes"},')
        print('   "lead_type": {"name": "<internal>", "value": "New Business"}}')
        if apply:
            sys.exit("Refusing to write lead fields with unconfirmed names.")

    # 1) contact lifecyclestage -> MQL
    print("\n[1] Contact lifecyclestage -> marketingqualifiedlead")
    if apply:
        status, resp = _request(
            "PATCH", f"/crm/v3/objects/contacts/{contact_id}",
            body={"properties": {"lifecyclestage": "marketingqualifiedlead"}})
        print(f"    PATCH contact -> {status}")
        if status != 200:
            sys.exit(f"    ERROR: {resp}")
    else:
        print(f"    would PATCH /crm/v3/objects/contacts/{contact_id} "
              '{"lifecyclestage":"marketingqualifiedlead"}')

    # 2) find associated lead
    print("\n[2] Find associated Lead")
    status, assoc = _request(
        "GET", f"/crm/v4/objects/contacts/{contact_id}/associations/leads")
    if status != 200:
        sys.exit(f"    ERROR fetching associations: {status}: {assoc}")
    lead_ids = [r["toObjectId"] for r in assoc.get("results", [])]
    if not lead_ids:
        sys.exit("    No associated Lead found. Seed one (seed-test) or check the "
                 "contact. Owner/lead creation may be a native-workflow step.")
    lead_id = lead_ids[0]
    print(f"    associated lead id = {lead_id}"
          + (f"  (WARNING: {len(lead_ids)} leads, using first)" if len(lead_ids) > 1 else ""))

    # 3) set lead fields — including the Lead pipeline stage so Sales sees it
    print("\n[3] Lead: pipeline stage -> Marketing Qualified Lead, "
          "Business Development -> Yes, Lead type -> New Business")
    if lp:
        props = {
            lp["business_development"]["name"]: lp["business_development"]["value"],
            lp["lead_type"]["name"]: lp["lead_type"]["value"],
        }
        # Move the Lead through its own pipeline so it lands in the MQL column
        # (the Contact lifecycle change does NOT do this — verified in sandbox).
        stage = lp.get("lead_pipeline_stage")
        if stage:
            props[stage["name"]] = stage["value"]
    else:
        props = {"<business_development>": "Yes", "<lead_type>": "New Business"}
    if apply and lp:
        status, resp = _request(
            "PATCH", f"/crm/v3/objects/leads/{lead_id}", body={"properties": props})
        print(f"    PATCH lead {lead_id} {props} -> {status}")
        if status != 200:
            sys.exit(f"    ERROR: {resp}")
    else:
        print(f"    would PATCH /crm/v3/objects/leads/{lead_id} {props}")

    # 4) do NOT set owner (native workflow)
    print("\n[4] Owner: left to native HubSpot by-country workflow (not set here).")

    # verify
    if apply:
        print("\n=== Verify ===")
        _, c = _request("GET", f"/crm/v3/objects/contacts/{contact_id}",
                        params={"properties": "lifecyclestage"})
        print(f"    contact.lifecyclestage = "
              f"{c.get('properties', {}).get('lifecyclestage')}")
        if lp:
            names = [lp["business_development"]["name"], lp["lead_type"]["name"]]
            if lp.get("lead_pipeline_stage"):
                names.append(lp["lead_pipeline_stage"]["name"])
            _, l = _request("GET", f"/crm/v3/objects/leads/{lead_id}",
                            params={"properties": ",".join(names)})
            print(f"    lead props = {l.get('properties', {})}")
    print("\nDone.")


def main():
    ap = argparse.ArgumentParser(description="Pass B HubSpot write helper (BD CRM screening).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="identify the portal (sandbox vs prod)")

    p_props = sub.add_parser("props", help="dump object properties + enum options")
    p_props.add_argument("object", help="object type, e.g. leads or contacts")
    p_props.add_argument("--grep", help="filter by name/label substring")

    p_seed = sub.add_parser("seed-test", help="(sandbox) create test contact + lead")
    p_seed.add_argument("--allow-prod", action="store_true", help=argparse.SUPPRESS)

    p_q = sub.add_parser("qualify", help="run the Pass B qualify action on ONE contact")
    p_q.add_argument("--contact-id", required=True)
    p_q.add_argument("--apply", action="store_true", help="actually write (default: dry-run)")
    p_q.add_argument("--allow-prod", action="store_true", help=argparse.SUPPRESS)

    args = ap.parse_args()
    {"whoami": cmd_whoami, "props": cmd_props,
     "seed-test": cmd_seed_test, "qualify": cmd_qualify}[args.cmd](args)


if __name__ == "__main__":
    main()
