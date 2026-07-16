"""Read-only HubSpot client.

Pulls Calls, Emails, Contacts and Owners via the HubSpot v3/v4 REST API using a
read-only private-app token. This module NEVER writes to HubSpot — no create,
update, delete, or property-definition calls exist here by design.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

import requests

BASE_URL = "https://api.hubapi.com"

# Properties we ask HubSpot for, per object type. Only read.
CALL_PROPERTIES = [
    "hs_call_title",
    "hs_call_summary",
    "hs_call_disposition",
    "hs_call_duration",
    "hs_timestamp",
    "hubspot_owner_id",
]
EMAIL_PROPERTIES = [
    "hs_email_subject",
    "hs_email_text",
    "hs_email_direction",
    "hs_timestamp",
    "hubspot_owner_id",
]
CONTACT_DISPLAY_PROPERTIES = [
    "firstname",
    "lastname",
    "email",
    "lifecyclestage",
    "hubspot_owner_id",
]

# The property that carries the free-text body we extract from, per object type.
BODY_PROPERTY = {"calls": "hs_call_summary", "emails": "hs_email_text"}


class HubSpotClient:
    """Thin read-only wrapper over the HubSpot REST API."""

    def __init__(self, token: str, *, timeout: float = 30.0, max_retries: int = 4):
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )
        self._timeout = timeout
        self._max_retries = max_retries

    # -- low-level ---------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        delay = 2.0
        for attempt in range(self._max_retries + 1):
            resp = self._session.request(method, url, timeout=self._timeout, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self._max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    time.sleep(float(retry_after) if retry_after else delay)
                    delay *= 2
                    continue
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        resp.raise_for_status()  # pragma: no cover - loop always returns/raises
        return {}

    # -- owners ------------------------------------------------------------

    def list_active_owners(self) -> list[dict[str, Any]]:
        """Return all active owners (``isActive: true``)."""
        owners: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 100}
            if after:
                params["after"] = after
            data = self._request("GET", "/crm/v3/owners/", params=params)
            for owner in data.get("results", []):
                if owner.get("archived"):
                    continue
                owners.append(owner)
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return owners

    # -- engagement search -------------------------------------------------

    def search_engagements(
        self,
        object_type: str,
        *,
        start_ms: int,
        end_ms: int,
        owner_id: str | None = None,
        extra_after_ms: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield calls/emails in the window, paginated.

        ``extra_after_ms`` narrows to records strictly newer than the last sync
        (incremental). Owner filter is optional (omit for a team-wide pull).
        """
        if object_type not in ("calls", "emails"):
            raise ValueError(f"Unsupported engagement type: {object_type}")

        properties = CALL_PROPERTIES if object_type == "calls" else EMAIL_PROPERTIES
        # HubSpot BETWEEN is inclusive; use the later of the window start and the
        # incremental cursor.
        effective_start = max(start_ms, extra_after_ms) if extra_after_ms else start_ms

        filters: list[dict[str, Any]] = [
            {
                "propertyName": "hs_timestamp",
                "operator": "BETWEEN",
                "value": str(effective_start),
                "highValue": str(end_ms),
            }
        ]
        if owner_id:
            filters.append(
                {
                    "propertyName": "hubspot_owner_id",
                    "operator": "EQ",
                    "value": str(owner_id),
                }
            )

        after: str | None = None
        while True:
            body: dict[str, Any] = {
                "filterGroups": [{"filters": filters}],
                "properties": properties,
                "sorts": [{"propertyName": "hs_timestamp", "direction": "ASCENDING"}],
                "limit": 100,
            }
            if after:
                body["after"] = after
            data = self._request(
                "POST", f"/crm/v3/objects/{object_type}/search", json=body
            )
            for record in data.get("results", []):
                yield record
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break

    # -- associations ------------------------------------------------------

    def get_associated_contact_ids(self, object_type: str, object_id: str) -> list[str]:
        """Return contact IDs associated with a call/email (v4 associations)."""
        path = f"/crm/v4/objects/{object_type}/{object_id}/associations/contacts"
        ids: list[str] = []
        after: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 500}
            if after:
                params["after"] = after
            data = self._request("GET", path, params=params)
            for row in data.get("results", []):
                # v4 shape: {"toObjectId": 123, "associationTypes": [...]}
                to_id = row.get("toObjectId") or row.get("to", {}).get("id")
                if to_id is not None:
                    ids.append(str(to_id))
            after = data.get("paging", {}).get("next", {}).get("after")
            if not after:
                break
        return ids

    # -- contacts (batch read for live name/email join) --------------------

    def get_contacts(
        self, contact_ids: list[str], properties: list[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        """Batch-read contacts, returning ``{contact_id: {properties...}}``."""
        if not contact_ids:
            return {}
        props = properties or CONTACT_DISPLAY_PROPERTIES
        out: dict[str, dict[str, Any]] = {}
        # HubSpot batch read caps at 100 inputs per call.
        for i in range(0, len(contact_ids), 100):
            chunk = contact_ids[i : i + 100]
            body = {
                "properties": props,
                "inputs": [{"id": str(cid)} for cid in chunk],
            }
            data = self._request(
                "POST", "/crm/v3/objects/contacts/batch/read", json=body
            )
            for record in data.get("results", []):
                out[str(record["id"])] = record.get("properties", {})
        return out
