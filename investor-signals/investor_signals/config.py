"""Configuration loading for the investor-signals tool.

Scope (date range + owner scope) lives in a YAML config file so a run can be
pointed at one rep for one month (pilot mode) before syncing the whole team.
Secrets (HubSpot token, Anthropic key) come from the environment, never the
config file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def _to_epoch_ms(date_str: str, *, end_of_day: bool = False) -> int:
    """Convert a ``YYYY-MM-DD`` string to a UTC epoch-millisecond timestamp.

    HubSpot's ``hs_timestamp`` filters expect epoch milliseconds. ``end_of_day``
    pushes the timestamp to 23:59:59.999 so an inclusive end date works.
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999000)
    return int(dt.timestamp() * 1000)


@dataclass
class SyncScope:
    mode: str = "pilot"  # "pilot" (one rep) | "team" (all active owners)
    owner_ids: list[str] = field(default_factory=list)
    start_date: str = ""
    end_date: str = ""
    object_types: list[str] = field(default_factory=lambda: ["calls"])

    @property
    def start_ms(self) -> int:
        return _to_epoch_ms(self.start_date)

    @property
    def end_ms(self) -> int:
        return _to_epoch_ms(self.end_date, end_of_day=True)


@dataclass
class Config:
    scope: SyncScope
    model: str = "claude-opus-4-8"
    min_body_chars: int = 80
    match_threshold: int = 82
    store_path: str = "investor_signals.db"
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    hubspot_token: str = ""
    anthropic_api_key: str = ""

    @property
    def anthropic_ready(self) -> bool:
        # The Anthropic SDK also resolves an `ant auth login` profile, so an
        # unset env var does not necessarily mean "no credentials".
        return True

    def require_hubspot(self) -> str:
        if not self.hubspot_token:
            raise RuntimeError(
                "HUBSPOT_TOKEN is not set. Create a read-only HubSpot private-app "
                "token and export it as HUBSPOT_TOKEN."
            )
        return self.hubspot_token


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Config file not found at {cfg_path}. Copy config.example.yaml to "
            f"config.yaml and edit the scope."
        )
    raw: dict[str, Any] = yaml.safe_load(cfg_path.read_text()) or {}

    sync_raw = raw.get("sync", {})
    date_raw = sync_raw.get("date_range", {})
    scope = SyncScope(
        mode=sync_raw.get("mode", "pilot"),
        owner_ids=[str(o) for o in sync_raw.get("owner_ids", []) or []],
        start_date=date_raw.get("start", ""),
        end_date=date_raw.get("end", ""),
        object_types=sync_raw.get("object_types", ["calls"]),
    )

    extraction = raw.get("extraction", {})
    normalize = raw.get("normalize", {})
    store = raw.get("store", {})
    server = raw.get("server", {})

    # Resolve the store path relative to the config file so runs are stable
    # regardless of the working directory.
    store_path = store.get("path", "investor_signals.db")
    if not os.path.isabs(store_path):
        store_path = str(cfg_path.parent / store_path)

    return Config(
        scope=scope,
        model=extraction.get("model", "claude-opus-4-8"),
        min_body_chars=int(extraction.get("min_body_chars", 80)),
        match_threshold=int(normalize.get("match_threshold", 82)),
        store_path=store_path,
        server_host=server.get("host", "127.0.0.1"),
        server_port=int(server.get("port", 8000)),
        hubspot_token=os.environ.get("HUBSPOT_TOKEN", ""),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
    )
