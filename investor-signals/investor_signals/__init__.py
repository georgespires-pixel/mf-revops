"""Moonfare investor-signal extraction — read-only against HubSpot, no CRM writes.

Governed by the investor-signal-extraction skill:
  * extract structured investor-interest signals from HubSpot calls/emails,
  * normalize fund mentions against a canonical list,
  * persist aggregated per-contact signals to a local SQLite store,
  * surface them in a small local web app (sales dashboard + deck-fit report).

Nothing in this package writes back to HubSpot.
"""

__version__ = "0.1.0"
