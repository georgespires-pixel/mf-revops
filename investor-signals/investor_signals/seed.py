"""Seed the local store from synthetic data — the MVP path (no HubSpot).

Offline by default: uses each synthetic engagement's ground-truth signal, so the
whole app populates with zero external calls. Pass ``use_llm=True`` to instead
run the real Claude extractor over the synthetic bodies (useful to sanity-check
extraction quality before wiring up real HubSpot data).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config
from .normalize import normalize_funds
from .store import Store
from .synthetic import generate


@dataclass
class SeedReport:
    contacts: int = 0
    engagements: int = 0
    signals_written: int = 0
    servicing_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"contacts={self.contacts} engagements={self.engagements} "
            f"signals={self.signals_written} servicing_no_signal={self.servicing_skipped} "
            f"errors={len(self.errors)}"
        )


def seed_store(
    config: Config,
    *,
    n_contacts: int = 12,
    use_llm: bool = False,
    reset: bool = True,
    seed: int = 42,
) -> SeedReport:
    if reset:
        import os

        if os.path.exists(config.store_path):
            os.remove(config.store_path)

    store = Store(config.store_path)
    report = SeedReport()

    extractor = None
    if use_llm:
        from .extract import Extractor

        extractor = Extractor(model=config.model)

    engagements, contacts = generate(n_contacts, seed=seed)
    report.contacts = len(contacts)

    # Local directory (offline fallback for name/email/rep in the app).
    for c in contacts:
        store.upsert_contact_directory(
            c["contact_id"],
            name=c["name"],
            email=c["email"],
            lifecycle_stage=c["lifecycle_stage"],
            owner_id=c["owner_id"],
        )
    from .synthetic import OWNERS

    for o in OWNERS:
        store.upsert_owner(o["id"], o["name"], o["email"])

    for eng in engagements:
        report.engagements += 1
        if store.is_processed(eng.object_type, eng.call_id):
            continue

        if use_llm:
            try:
                extraction = extractor.extract(  # type: ignore[union-attr]
                    contact_id=eng.contact_id,
                    call_id=eng.call_id,
                    call_date=eng.call_date,
                    title=eng.title,
                    body=eng.body,
                )
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{eng.call_id}: {exc}")
                continue
        else:
            extraction = {
                "contact_id": eng.contact_id,
                "call_id": eng.call_id,
                "call_date": eng.call_date,
                **eng.truth,
            }

        if not extraction.get("funds_mentioned") and not extraction.get(
            "industry_or_asset_class"
        ):
            # Servicing / no-interest engagement: record it as processed but
            # write no investor signal (matches the pipeline's real behavior).
            report.servicing_skipped += 1
            store.mark_processed(
                eng.object_type, eng.call_id, eng.contact_id, eng.call_owner_id
            )
            continue

        normalized = normalize_funds(
            extraction.get("funds_mentioned", []), threshold=config.match_threshold
        )
        store.upsert_signal(
            contact_id=eng.contact_id,
            contact_owner_id=eng.contact_owner_id,
            normalized_funds=normalized,
            extraction=extraction,
        )
        store.mark_processed(
            eng.object_type, eng.call_id, eng.contact_id, eng.call_owner_id
        )
        report.signals_written += 1

    store.close()
    return report
