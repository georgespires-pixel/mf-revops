"""Local web app: sales dashboard + deck-fit upload.

Reads aggregated signals from the local SQLite store. Live name/email/lifecycle
are joined from HubSpot only at render time (never duplicated into the store,
since they go stale). Read-only against HubSpot throughout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import anthropic
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .config import Config, load_config
from .deck_fit import DeckFitReporter, extract_deck_text
from .hubspot_client import HubSpotClient
from .normalize import canonical_fund_names
from .store import Store

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    app = FastAPI(title="Moonfare Investor Signals", version="0.1.0")

    store = Store(config.store_path)
    # HubSpot client is optional at read time; if the token is missing the
    # dashboard still works, just without the live name/email join.
    hs: HubSpotClient | None = (
        HubSpotClient(config.hubspot_token) if config.hubspot_token else None
    )

    def _attach_contact_details(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Attach name/email/lifecycle. Prefers a live HubSpot join; falls back
        to the local directory (offline MVP with synthetic data)."""
        if not rows:
            return rows
        ids = [r["contact_id"] for r in rows]
        if hs:
            contacts = hs.get_contacts(ids)
            for r in rows:
                props = contacts.get(r["contact_id"], {})
                name = " ".join(
                    p for p in [props.get("firstname"), props.get("lastname")] if p
                ).strip()
                r["display_name"] = name or None
                r["email"] = props.get("email")
                r["lifecycle_stage"] = props.get("lifecyclestage")
            return rows
        directory = store.get_contact_directory(ids)
        for r in rows:
            d = directory.get(r["contact_id"], {})
            r["display_name"] = d.get("name")
            r["email"] = d.get("email")
            r["lifecycle_stage"] = d.get("lifecycle_stage")
        return rows

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "hubspot_join": hs is not None,
            "offline": config.offline,
            "store": store.stats(),
        }

    @app.get("/api/funds")
    def funds() -> list[str]:
        return canonical_fund_names()

    @app.get("/api/taxonomy")
    def taxonomy_endpoint() -> dict[str, Any]:
        from . import taxonomy as tax

        return {
            "funds": canonical_fund_names(),
            "asset_classes": tax.ASSET_CLASSES,
            "gics_sectors": tax.GICS_SECTORS,
            "geographies": tax.GEOGRAPHIES,
            "currencies": tax.CURRENCIES,
            "cap_sizes": tax.CAP_SIZES,
        }

    @app.get("/api/stats")
    def stats() -> dict[str, Any]:
        return {
            "totals": store.stats(),
            "asset_class_interest": store.asset_class_interest(),
        }

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        return store.overview()

    @app.get("/api/owners")
    def owners() -> list[dict[str, Any]]:
        if hs:
            return [
                {
                    "id": str(o["id"]),
                    "name": " ".join(
                        p for p in [o.get("firstName"), o.get("lastName")] if p
                    ).strip()
                    or o.get("email"),
                    "email": o.get("email"),
                }
                for o in hs.list_active_owners()
            ]
        # Offline fallback: owners recorded by the synthetic seed.
        return [
            {"id": o["owner_id"], "name": o["name"], "email": o["email"]}
            for o in store.list_owners()
        ]

    @app.get("/api/contacts")
    def contacts(
        # Use typing.Optional (not `str | None`) here: FastAPI evaluates route
        # parameter annotations at runtime, and the `|` union syntax only
        # evaluates on Python 3.10+. This keeps the app runnable on 3.9 (macOS
        # system Python) without extra packages.
        fund: Optional[str] = Query(None),
        asset_class: Optional[str] = Query(None),
        sector: Optional[str] = Query(None),
        geography: Optional[str] = Query(None),
        currency: Optional[str] = Query(None),
        cap_size: Optional[str] = Query(None),
        sentiment: Optional[str] = Query(None),
        rep: Optional[str] = Query(None, description="contact owner id"),
    ) -> list[dict[str, Any]]:
        rows = store.query_contacts(
            fund=fund, asset_class=asset_class, sector=sector, geography=geography,
            currency=currency, cap_size=cap_size, sentiment=sentiment, owner_id=rep,
        )
        return _attach_contact_details(rows)

    @app.post("/api/deck-fit")
    async def deck_fit(file: UploadFile = File(...)) -> JSONResponse:
        data = await file.read()
        try:
            deck_text = extract_deck_text(file.filename or "deck", data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not deck_text.strip():
            raise HTTPException(422, "Could not extract any text from the deck.")

        signals = store.all_signals()
        if config.offline:
            # MVP: keyword-overlap heuristic, no external call.
            from .deck_fit import heuristic_assess

            report = heuristic_assess(deck_text, signals)
        else:
            try:
                reporter = DeckFitReporter(model=config.model)
                report = reporter.assess(deck_text, signals)
            except (anthropic.AnthropicError, TypeError) as exc:
                # AnthropicError covers API/rate-limit failures; the SDK raises a
                # bare TypeError when no credential can be resolved.
                raise HTTPException(
                    502, f"Claude API call failed (check ANTHROPIC_API_KEY): {exc}"
                ) from exc

        # Attach contact names to the evidence (live HubSpot or local directory).
        evidence = report.get("evidence", [])
        ids = [e["contact_id"] for e in evidence if e.get("contact_id")]
        if hs and ids:
            contacts_map = hs.get_contacts(ids)
            for e in evidence:
                props = contacts_map.get(e.get("contact_id", ""), {})
                name = " ".join(
                    p for p in [props.get("firstname"), props.get("lastname")] if p
                ).strip()
                e["contact_name"] = name or None
                e["contact_email"] = props.get("email")
        elif ids:
            directory = store.get_contact_directory(ids)
            for e in evidence:
                d = directory.get(e.get("contact_id", ""), {})
                e["contact_name"] = d.get("name")
                e["contact_email"] = d.get("email")
        return JSONResponse(report)

    return app
