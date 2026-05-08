"""Pricing / plan catalog.

Single source of truth consumed by:
  - checkout.html  (shows what you're buying)
  - /plans         (API; used by landing/portal)
  - invoice.py     (tier -> unit price for metered overage)
"""
from __future__ import annotations

# All prices in USD.
PLANS = [
    {
        "id": "free",
        "name": "Free",
        "price_usd": 0,
        "cadence": "forever",
        "monthly_quota": 500,
        "features": [
            "500 SMILES / month",
            "/compute, /similarity",
            "No credit card",
        ],
        "stripe_price_id": None,
    },
    {
        "id": "research",
        "name": "Research",
        "price_usd": 49,
        "cadence": "month",
        "monthly_quota": 10_000,
        "features": [
            "10k SMILES / month",
            "All endpoints (descriptors, substructure, diversity, SDF, Parquet)",
            "Audit log + CSV exports",
            "Email support",
        ],
        "stripe_price_id": "price_research_monthly",
    },
    {
        "id": "commercial",
        "name": "Commercial",
        "price_usd": 299,
        "cadence": "month",
        "monthly_quota": 100_000,
        "features": [
            "100k SMILES / month",
            "Commercial redistribution rights",
            "Teams + shared quota pool",
            "Outbound webhooks",
            "Priority email support",
        ],
        "stripe_price_id": "price_commercial_monthly",
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "price_usd": None,   # "contact us"
        "cadence": "year",
        "monthly_quota": 10_000_000,
        "features": [
            "10M SMILES / month",
            "SLA + dedicated Slack",
            "SSO / custom deployment",
            "On-prem Docker image option",
        ],
        "stripe_price_id": None,
    },
]


def by_id(plan_id: str) -> dict | None:
    for p in PLANS:
        if p["id"] == plan_id:
            return p
    return None
