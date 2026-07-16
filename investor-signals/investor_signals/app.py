"""Local web app: sales dashboard + deck-fit upload.

Reads aggregated signals from the local SQLite store. Live name/email/lifecycle
are joined from HubSpot only at render time (never duplicated into the store,
since they go stale). Read-only against HubSpot throughout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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

    def _join_hubspot(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not hs or not rows:
            for r in rows:
                r["display_name"] = None
                r["email"] = None
                r["lifecycle_stage"] = None
            return rows
        ids = [r["contact_id"] for r in rows]
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

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "hubspot_join": hs is not None,
            "store": store.stats(),
        }

    @app.get("/api/funds")
    def funds() -> list[str]:
        return canonical_fund_names()

    @app.get("/api/owners")
    def owners() -> list[dict[str, Any]]:
        if not hs:
            return []
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

    @app.get("/api/contacts")
    def contacts(
        fund: str | None = Query(None),
        industry: str | None = Query(None),
        sentiment: str | None = Query(None),
        rep: str | None = Query(None, description="contact owner id"),
    ) -> list[dict[str, Any]]:
        rows = store.query_contacts(
            fund=fund, industry=industry, sentiment=sentiment, owner_id=rep
        )
        return _join_hubspot(rows)

    @app.post("/api/deck-fit")
    async def deck_fit(file: UploadFile = File(...)) -> JSONResponse:
        if not config.anthropic_ready:
            raise HTTPException(500, "Anthropic credentials not configured.")
        data = await file.read()
        try:
            deck_text = extract_deck_text(file.filename or "deck", data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not deck_text.strip():
            raise HTTPException(422, "Could not extract any text from the deck.")

        reporter = DeckFitReporter(model=config.model)
        report = reporter.assess(deck_text, store.all_signals())

        # Join contact names onto the evidence so the report names investors.
        evidence = report.get("evidence", [])
        if hs and evidence:
            ids = [e["contact_id"] for e in evidence if e.get("contact_id")]
            contacts_map = hs.get_contacts(ids)
            for e in evidence:
                props = contacts_map.get(e.get("contact_id", ""), {})
                name = " ".join(
                    p for p in [props.get("firstname"), props.get("lastname")] if p
                ).strip()
                e["contact_name"] = name or None
                e["contact_email"] = props.get("email")
        return JSONResponse(report)

    return app
