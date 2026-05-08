"""Invoice + usage-receipt generator.

Produces a plain-text invoice for a given API key + month, from the usage
log. Returned as a markdown string so it renders in the customer portal,
and as structured JSON for machine consumption / CSV export.

Keeps tax-compliance requirements low: we're selling API credits, prices
are preset at checkout, so invoices are informational receipts only.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

from src import keys as keysdb

TIER_PRICE_CENTS = {
    "free": 0,
    "research": 2900,
    "commercial": 29900,
    "redistribution": 99900,
    "enterprise": 500000,
}


@dataclass
class InvoiceLine:
    endpoint: str
    calls: int
    smiles: int

    def to_dict(self) -> dict:
        return {"endpoint": self.endpoint, "calls": self.calls,
                "smiles": self.smiles}


@dataclass
class Invoice:
    api_key: str
    email: str
    tier: str
    period: str  # YYYY-MM
    subtotal_cents: int
    total_smiles: int
    total_calls: int
    lines: List[InvoiceLine]

    def to_dict(self) -> dict:
        return {
            "api_key": self.api_key[:12] + "…",
            "email": self.email,
            "tier": self.tier,
            "period": self.period,
            "subtotal_cents": self.subtotal_cents,
            "subtotal_usd": round(self.subtotal_cents / 100, 2),
            "total_smiles": self.total_smiles,
            "total_calls": self.total_calls,
            "lines": [l.to_dict() for l in self.lines],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Q-Mol Invoice — {self.period}",
            "",
            f"**Customer**: {self.email}  ",
            f"**Tier**: {self.tier}  ",
            f"**API key**: `{self.api_key[:12]}…`  ",
            f"**Period**: {self.period}",
            "",
            "| Endpoint | Calls | SMILES |",
            "|---|---:|---:|",
        ]
        for l in self.lines:
            lines.append(f"| `{l.endpoint}` | {l.calls} | {l.smiles} |")
        lines += [
            f"| **Total** | **{self.total_calls}** | **{self.total_smiles}** |",
            "",
            f"**Subtotal:** ${self.subtotal_cents / 100:.2f} USD  ",
            "",
            "*Prepaid subscription — no additional charges this period.*",
        ]
        return "\n".join(lines)


def generate(api_key: str, year_month: str | None = None) -> Invoice:
    info = keysdb.lookup(api_key)
    if not info:
        raise ValueError("Unknown API key")
    period = year_month or datetime.now(timezone.utc).strftime("%Y-%m")

    c = keysdb._connect()
    rows = c.execute(
        "SELECT endpoint, COUNT(*), COALESCE(SUM(smiles_count),0) "
        "FROM usage WHERE key=? AND strftime('%Y-%m', ts)=? "
        "GROUP BY endpoint ORDER BY SUM(smiles_count) DESC",
        (api_key, period),
    ).fetchall()
    c.close()

    lines = [InvoiceLine(endpoint=ep or "(unknown)", calls=int(n), smiles=int(s))
             for ep, n, s in rows]
    total_smi = sum(l.smiles for l in lines)
    total_calls = sum(l.calls for l in lines)
    subtotal = TIER_PRICE_CENTS.get(info.tier, 0)

    return Invoice(
        api_key=api_key,
        email=info.email,
        tier=info.tier,
        period=period,
        subtotal_cents=subtotal,
        total_smiles=total_smi,
        total_calls=total_calls,
        lines=lines,
    )
