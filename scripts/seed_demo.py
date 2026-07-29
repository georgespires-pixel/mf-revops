#!/usr/bin/env python3
"""Seed demo PQL leads in the HubSpot SANDBOX for a BD CRM Screening demo.

Creates a spread of contacts (lifecyclestage=lead = PQL) each with an associated
Lead object, designed to exercise the rubric's three outcomes:
  - two obvious MQLs (famous founder/owner + wealth signals)
  - one NEEDS_REVIEW (mid-level, ambiguous, thin wealth signal)
  - one NOT_MQL (clearly junior, no wealth/ownership)

Sandbox-only (refuses on non-sandbox portals). Reads HUBSPOT_BD_WRITE_TOKEN.
Run:  python3 scripts/seed_demo.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://api.hubapi.com"
TOK = os.environ.get("HUBSPOT_BD_WRITE_TOKEN")
SANDBOX_TYPES = {"SANDBOX", "DEVELOPER_TEST", "APP_DEVELOPER"}

# Expected rubric outcome is a hint for the demo narrative, not written to HubSpot.
PERSONAS = [
    {"firstname": "Cristiano", "lastname": "Ronaldo", "jobtitle": "Founder & Owner",
     "company": "CR7 Lifestyle / Pestana CR7 Hotels", "country": "Portugal",
     "expected": "MQL — founder/owner, multiple businesses, very high net worth"},
    {"firstname": "Lionel", "lastname": "Messi", "jobtitle": "Co-Owner & Founder",
     "company": "Inter Miami CF / Play Time SL", "country": "United States",
     "expected": "MQL — co-owner/founder, athlete-entrepreneur, very high net worth"},
    {"firstname": "Georgi", "lastname": "Petrov", "jobtitle": "Project Manager",
     "company": "Acme IT Services", "country": "Bulgaria",
     "expected": "NEEDS_REVIEW — mid-level IC, no clear ownership/wealth signal"},
    {"firstname": "John", "lastname": "Carter", "jobtitle": "Personal Trainer",
     "company": "FitZone Gym", "country": "United Kingdom",
     "expected": "NOT_MQL — junior/IC, no offsetting wealth or ownership"},
]


def req(method, path, body):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method=method)
    r.add_header("Authorization", "Bearer " + TOK)
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def get(path):
    r = urllib.request.Request(BASE + path)
    r.add_header("Authorization", "Bearer " + TOK)
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read().decode())


def main():
    if not TOK:
        sys.exit("ERROR: HUBSPOT_BD_WRITE_TOKEN not set.")
    acct = get("/account-info/v3/details")
    if acct.get("accountType") not in SANDBOX_TYPES:
        sys.exit(f"REFUSING: portal {acct.get('portalId')} is not a sandbox "
                 f"(accountType={acct.get('accountType')}).")
    print(f"Sandbox portal {acct['portalId']} — seeding {len(PERSONAS)} demo leads\n")
    stamp = str(int(time.time()))
    rows = []
    for p in PERSONAS:
        email = f"{p['firstname'].lower()}.{p['lastname'].lower()}+demo{stamp}@example.com"
        s, contact = req("POST", "/crm/v3/objects/contacts", {"properties": {
            "email": email, "firstname": p["firstname"], "lastname": p["lastname"],
            "jobtitle": p["jobtitle"], "company": p["company"], "country": p["country"],
            "lifecyclestage": "lead",
        }})
        if s not in (200, 201):
            print(f"  ! contact {p['firstname']} {p['lastname']} failed: {s} {contact}")
            continue
        cid = contact["id"]
        s, lead = req("POST", "/crm/v3/objects/leads", {
            "properties": {"hs_lead_name": f"{p['firstname']} {p['lastname']}"},
            "associations": [{"to": {"id": cid}, "types": [
                {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 578}]}],
        })
        lid = lead.get("id", "?") if s in (200, 201) else f"FAILED {s}"
        rows.append((f"{p['firstname']} {p['lastname']}", cid, lid, p["jobtitle"], p["expected"]))
        print(f"  ✓ {p['firstname']} {p['lastname']:10} contact={cid} lead={lid}")
    print("\n=== Demo queue (expected rubric outcomes) ===")
    for name, cid, lid, title, exp in rows:
        print(f"  {name:20} [{title}]  contact={cid}\n      → {exp}")
    print("\nContacts are lifecyclestage=lead (PQL). Run Pass A to score + propose.")


if __name__ == "__main__":
    main()
