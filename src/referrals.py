"""Referral / affiliate program.

Every active API key gets a `ref_code`. When a new user signs up or buys via
that code, a referral row is recorded. Referrers earn credit (bonus SMILES
on free tier, or revenue share on paid purchases).
"""
from __future__ import annotations
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src import keys as keysdb

REFERRAL_BONUS_FREE = 500      # extra SMILES for each free signup
REFERRAL_REVENUE_SHARE = 0.20  # 20% of paid-tier price

_PRICE = {"research": 29, "commercial": 299, "redistribution": 999, "enterprise": 5000}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ref_codes (
    code TEXT PRIMARY KEY,
    api_key TEXT UNIQUE NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_code TEXT NOT NULL,
    referred_email TEXT NOT NULL,
    tier TEXT NOT NULL,
    bonus_smiles INTEGER DEFAULT 0,
    revenue_cents INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass
class RefStats:
    code: str
    total_referrals: int
    free_signups: int
    paid_purchases: int
    earned_cents: int
    bonus_smiles: int


def _conn() -> sqlite3.Connection:
    c = keysdb._connect()
    c.executescript(_SCHEMA)
    return c


def code_for(api_key: str) -> str:
    """Return (or lazily create) the referral code for this API key."""
    c = _conn()
    row = c.execute("SELECT code FROM ref_codes WHERE api_key=?", (api_key,)).fetchone()
    if row:
        c.close()
        return row[0]
    code = secrets.token_urlsafe(6)
    c.execute("INSERT INTO ref_codes (code, api_key) VALUES (?,?)", (code, api_key))
    c.commit()
    c.close()
    return code


def resolve(code: str) -> str | None:
    """Look up the API key that owns a referral code."""
    c = _conn()
    row = c.execute("SELECT api_key FROM ref_codes WHERE code=?", (code,)).fetchone()
    c.close()
    return row[0] if row else None


def credit(code: str, referred_email: str, tier: str) -> dict:
    """Record a referral event and pay the referrer.

    - Free signup -> bonus SMILES on the referrer's quota (recorded as negative
      usage so the referrer sees extra headroom).
    - Paid signup -> revenue_share credit stored in cents.
    """
    owner_key = resolve(code)
    if not owner_key:
        return {"credited": False, "reason": "unknown ref code"}

    bonus = 0
    revenue_cents = 0

    if tier == "free":
        bonus = REFERRAL_BONUS_FREE
        # negative usage entry = quota credit
        keysdb.record(owner_key, "/ref/bonus", -bonus)
    elif tier in _PRICE:
        revenue_cents = int(_PRICE[tier] * REFERRAL_REVENUE_SHARE * 100)

    c = _conn()
    c.execute(
        "INSERT INTO referrals (ref_code, referred_email, tier, "
        "bonus_smiles, revenue_cents) VALUES (?,?,?,?,?)",
        (code, referred_email, tier, bonus, revenue_cents),
    )
    c.commit()
    c.close()
    return {"credited": True, "bonus_smiles": bonus,
            "revenue_cents": revenue_cents, "owner_key": owner_key}


def stats(api_key: str) -> RefStats:
    c = _conn()
    row = c.execute("SELECT code FROM ref_codes WHERE api_key=?", (api_key,)).fetchone()
    if not row:
        c.close()
        return RefStats(code="", total_referrals=0, free_signups=0,
                        paid_purchases=0, earned_cents=0, bonus_smiles=0)
    code = row[0]
    agg = c.execute(
        "SELECT COUNT(*), "
        "SUM(CASE WHEN tier='free' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN tier!='free' THEN 1 ELSE 0 END), "
        "COALESCE(SUM(revenue_cents),0), "
        "COALESCE(SUM(bonus_smiles),0) "
        "FROM referrals WHERE ref_code=?",
        (code,),
    ).fetchone()
    c.close()
    return RefStats(
        code=code,
        total_referrals=int(agg[0] or 0),
        free_signups=int(agg[1] or 0),
        paid_purchases=int(agg[2] or 0),
        earned_cents=int(agg[3] or 0),
        bonus_smiles=int(agg[4] or 0),
    )
