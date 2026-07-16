"""Sync orchestration: pull -> extract -> normalize -> persist (incremental).

Read-only against HubSpot. Skips bodies with no/near-empty content (voicemails,
one-liners) — roughly a third of raw calls actually qualify; that is expected,
not a bug.

Owner resolution rule (from the skill): the investor-facing signal is written to
the CONTACT's owner (the relationship owner), not the call's owner (whoever
happened to dial). We fetch both; the call owner is recorded separately in the
audit log for activity reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import Config
from .extract import Extractor
from .hubspot_client import BODY_PROPERTY, HubSpotClient
from .normalize import normalize_funds
from .store import Store


@dataclass
class SyncReport:
    owners_scoped: list[str] = field(default_factory=list)
    fetched: int = 0
    skipped_no_body: int = 0
    skipped_already_processed: int = 0
    skipped_no_contact: int = 0
    extracted: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"owners={len(self.owners_scoped)} fetched={self.fetched} "
            f"extracted={self.extracted} "
            f"skipped(no_body={self.skipped_no_body}, "
            f"already={self.skipped_already_processed}, "
            f"no_contact={self.skipped_no_contact}) errors={len(self.errors)}"
        )


def _ms_to_iso(ts_ms: str | int | None) -> str:
    if ts_ms is None or ts_ms == "":
        return ""
    try:
        return datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        # hs_timestamp can also arrive as an ISO string.
        return str(ts_ms)


def resolve_owner_ids(config: Config, hs: HubSpotClient) -> list[str | None]:
    """Return the owner IDs to loop over.

    Pilot mode uses the configured owner_ids (start with one rep). Team mode
    resolves all active owners; if the config already lists owner_ids in team
    mode those win. A team-wide unfiltered pull is represented by ``[None]``.
    """
    if config.scope.owner_ids:
        return list(config.scope.owner_ids)
    if config.scope.mode == "team":
        owners = hs.list_active_owners()
        return [str(o["id"]) for o in owners]
    raise RuntimeError(
        "Pilot mode requires at least one owner_id in config.yaml (sync.owner_ids). "
        "Start with one rep to validate extraction quality before a team run."
    )


def run_sync(config: Config, *, hs: HubSpotClient | None = None,
             extractor: Extractor | None = None, store: Store | None = None) -> SyncReport:
    hs = hs or HubSpotClient(config.require_hubspot())
    extractor = extractor or Extractor(model=config.model)
    store = store or Store(config.store_path)
    report = SyncReport()

    owner_ids = resolve_owner_ids(config, hs)
    report.owners_scoped = [str(o) for o in owner_ids if o is not None]

    for object_type in config.scope.object_types:
        body_prop = BODY_PROPERTY.get(object_type)
        if not body_prop:
            report.errors.append(f"Unknown object type {object_type}; skipping")
            continue

        last_ts = store.get_last_ts(object_type)
        max_ts_seen = last_ts or 0

        for owner_id in owner_ids:
            for record in hs.search_engagements(
                object_type,
                start_ms=config.scope.start_ms,
                end_ms=config.scope.end_ms,
                owner_id=owner_id,
                extra_after_ms=last_ts,
            ):
                report.fetched += 1
                object_id = str(record["id"])
                props = record.get("properties", {})

                # Track the newest timestamp for the incremental cursor.
                raw_ts = props.get("hs_timestamp")
                try:
                    ts_ms = int(raw_ts) if raw_ts and str(raw_ts).isdigit() else None
                except (ValueError, TypeError):
                    ts_ms = None
                if ts_ms:
                    max_ts_seen = max(max_ts_seen, ts_ms)

                if store.is_processed(object_type, object_id):
                    report.skipped_already_processed += 1
                    continue

                body = (props.get(body_prop) or "").strip()
                if len(body) < config.min_body_chars:
                    report.skipped_no_body += 1
                    continue

                contact_ids = hs.get_associated_contact_ids(object_type, object_id)
                if not contact_ids:
                    report.skipped_no_contact += 1
                    continue

                # Resolve the contact's owner (the relationship owner) for
                # persistence; the call owner is audit-only metadata.
                call_owner_id = props.get("hubspot_owner_id")
                contacts = hs.get_contacts(contact_ids, ["hubspot_owner_id"])
                call_date = _ms_to_iso(raw_ts)
                title = props.get("hs_call_title") or props.get("hs_email_subject") or ""

                for contact_id in contact_ids:
                    contact_owner_id = contacts.get(contact_id, {}).get(
                        "hubspot_owner_id"
                    )
                    try:
                        extraction = extractor.extract(
                            contact_id=contact_id,
                            call_id=object_id,
                            call_date=call_date,
                            title=title,
                            body=body,
                        )
                    except Exception as exc:  # noqa: BLE001 - report, keep going
                        report.errors.append(
                            f"{object_type}:{object_id} contact {contact_id}: {exc}"
                        )
                        continue

                    normalized = normalize_funds(
                        extraction.get("funds_mentioned", []),
                        threshold=config.match_threshold,
                    )
                    store.upsert_signal(
                        contact_id=contact_id,
                        contact_owner_id=contact_owner_id,
                        normalized_funds=normalized,
                        extraction=extraction,
                    )
                    report.extracted += 1

                store.mark_processed(
                    object_type, object_id, contact_ids[0], call_owner_id
                )

        if max_ts_seen and max_ts_seen != (last_ts or 0):
            store.set_last_ts(object_type, max_ts_seen)

    return report
