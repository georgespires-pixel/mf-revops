"""Controlled vocabularies for investor-signal dimensions.

Shared by the synthetic generator, the heuristic (offline) extractor, the Claude
extraction prompt, and the dashboard filters, so the same terms are used
everywhere. Keeping these fixed also keeps historical data comparable.
"""

from __future__ import annotations

# Private-markets asset classes (replaces the old free-text "industry").
ASSET_CLASSES = [
    "Buyout",
    "Venture Capital",
    "Growth Equity",
    "Secondaries",
    "Private Credit",
    "Infrastructure",
    "Real Estate",
    "Fund of Funds",
    "Co-Investment",
]

# The 11 GICS sectors (used for the underlying-sector split).
GICS_SECTORS = [
    "Energy",
    "Materials",
    "Industrials",
    "Consumer Discretionary",
    "Consumer Staples",
    "Health Care",
    "Financials",
    "Information Technology",
    "Communication Services",
    "Utilities",
    "Real Estate",
]

GEOGRAPHIES = [
    "North America",
    "Europe",
    "DACH",
    "UK",
    "Nordics",
    "Asia-Pacific",
    "Emerging Markets",
    "Global",
]

CURRENCIES = ["USD", "EUR", "GBP", "CHF"]

# Buyout cap-size buckets.
CAP_SIZES = ["Small-cap", "Mid-cap", "Large-cap"]

# --- keyword maps for the heuristic (offline) extractor ---------------------
# Lowercased trigger -> canonical label. First match wins per dimension.

ASSET_CLASS_KEYWORDS = {
    "buyout": "Buyout",
    "lbo": "Buyout",
    "venture": "Venture Capital",
    "vc ": "Venture Capital",
    "early stage": "Venture Capital",
    "seed": "Venture Capital",
    "growth equity": "Growth Equity",
    "growth capital": "Growth Equity",
    "growth fund": "Growth Equity",
    "secondar": "Secondaries",
    "private credit": "Private Credit",
    "private debt": "Private Credit",
    "direct lending": "Private Credit",
    "mezzanine": "Private Credit",
    "infrastructure": "Infrastructure",
    "infra ": "Infrastructure",
    "real estate": "Real Estate",
    "fund of funds": "Fund of Funds",
    "fund-of-funds": "Fund of Funds",
    "co-invest": "Co-Investment",
    "coinvest": "Co-Investment",
}

GICS_KEYWORDS = {
    "software": "Information Technology",
    "saas": "Information Technology",
    "technology": "Information Technology",
    "semiconductor": "Information Technology",
    "fintech": "Financials",
    "bank": "Financials",
    "insurance": "Financials",
    "healthcare": "Health Care",
    "health care": "Health Care",
    "biotech": "Health Care",
    "pharma": "Health Care",
    "medical": "Health Care",
    "energy": "Energy",
    "oil": "Energy",
    "renewable": "Utilities",
    "utilit": "Utilities",
    "industrial": "Industrials",
    "manufactur": "Industrials",
    "logistics": "Industrials",
    "consumer": "Consumer Discretionary",
    "retail": "Consumer Discretionary",
    "media": "Communication Services",
    "telecom": "Communication Services",
    "materials": "Materials",
    "mining": "Materials",
    "real estate": "Real Estate",
    "property": "Real Estate",
}

GEOGRAPHY_KEYWORDS = {
    "north america": "North America",
    "united states": "North America",
    " us ": "North America",
    "u.s.": "North America",
    "europe": "Europe",
    "european": "Europe",
    "dach": "DACH",
    "germany": "DACH",
    "switzerland": "DACH",
    "austria": "DACH",
    "united kingdom": "UK",
    " uk ": "UK",
    "nordic": "Nordics",
    "asia": "Asia-Pacific",
    "apac": "Asia-Pacific",
    "china": "Asia-Pacific",
    "india": "Asia-Pacific",
    "emerging market": "Emerging Markets",
    "global": "Global",
    "worldwide": "Global",
}

CURRENCY_KEYWORDS = {
    "usd": "USD",
    "us$": "USD",
    "dollar": "USD",
    "eur": "EUR",
    "euro": "EUR",
    "€": "EUR",
    "gbp": "GBP",
    "£": "GBP",
    "sterling": "GBP",
    "pound": "GBP",
    "chf": "CHF",
    "swiss franc": "CHF",
}

CAP_KEYWORDS = {
    "large-cap": "Large-cap",
    "large cap": "Large-cap",
    "mega-cap": "Large-cap",
    "mid-cap": "Mid-cap",
    "mid cap": "Mid-cap",
    "middle market": "Mid-cap",
    "small-cap": "Small-cap",
    "small cap": "Small-cap",
    "lower mid": "Small-cap",
}
