"""Coupon / discount codes.

Used at checkout to discount any tier. Supports:
- Percent or fixed-amount discounts
- Usage limit (total redemptions)
- Expiry date
- Tier restriction (optional)
- Attribution to a referrer (auto-credits referral when redeemed)
"""
from __future__ import annotations
import sqlite3
import time
from dataclasses import dataclass

from src import keys as keysdb

_SCHEMA = """
CREATE TABLE IF NOT EXISTS coupons (
    code TEXT PRIMARY KEY,
    percent_off INTEGER DEFAULT 0,
    amount_off_cents INTEGER DEFAULT 0,
    max_redemptions INTEGER DEFAULT 0,      -- 0 = unlimited
    redemptions INTEGER DEFAULT 0,
    expires_at REAL,                        -- unix seconds, NULL = no expiry
    tier_restriction TEXT,                  -- NULL = any tier
    attributed_ref_code TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass
class Coupon:
    code: str
    percent_off: int
    amount_off_cents: int
    redemptions: int
    max_redemptions: int
    expires_at: float | None
    tier_restriction: str | None
    attributed_ref_code: str | None


def _conn() -> sqlite3.Connection:
    c = keysdb._connect()
    c.executescript(_SCHEMA)
    return c


def create(code: str, *, percent_off: int = 0, amount_off_cents: int = 0,
           max_redemptions: int = 0, expires_at: float | None = None,
           tier_restriction: str | None = None,
           attributed_ref_code: str | None = None) -> Coupon:
    if percent_off < 0 or percent_off > 100:
        raise ValueError("percent_off must be 0..100")
    if percent_off == 0 and amount_off_cents == 0:
        raise ValueError("coupon must discount something")
    c = _conn()
    c.execute(
        "INSERT OR REPLACE INTO coupons "
        "(code, percent_off, amount_off_cents, max_redemptions, expires_at, "
        "tier_restriction, attributed_ref_code) VALUES (?,?,?,?,?,?,?)",
        (code, percent_off, amount_off_cents, max_redemptions, expires_at,
         tier_restriction, attributed_ref_code),
    )
    c.commit()
    c.close()
    return lookup(code)  # type: ignore[return-value]


def lookup(code: str) -> Coupon | None:
    c = _conn()
    row = c.execute(
        "SELECT code, percent_off, amount_off_cents, redemptions, max_redemptions, "
        "expires_at, tier_restriction, attributed_ref_code FROM coupons WHERE code=?",
        (code,),
    ).fetchone()
    c.close()
    if not row:
        return None
    return Coupon(*row)


def apply(code: str, tier: str, base_cents: int) -> dict:
    """Return {"discount_cents": x, "final_cents": y, "valid": bool, "reason": str}."""
    cp = lookup(code)
    if not cp:
        return {"valid": False, "reason": "unknown code", "final_cents": base_cents,
                "discount_cents": 0}
    if cp.expires_at and time.time() > cp.expires_at:
        return {"valid": False, "reason": "expired", "final_cents": base_cents,
                "discount_cents": 0}
    if cp.max_redemptions and cp.redemptions >= cp.max_redemptions:
        return {"valid": False, "reason": "redemption limit reached",
                "final_cents": base_cents, "discount_cents": 0}
    if cp.tier_restriction and cp.tier_restriction != tier:
        return {"valid": False, "reason": f"tier must be {cp.tier_restriction}",
                "final_cents": base_cents, "discount_cents": 0}

    discount = 0
    if cp.percent_off:
        discount += base_cents * cp.percent_off // 100
    if cp.amount_off_cents:
        discount += cp.amount_off_cents
    discount = min(discount, base_cents)
    return {"valid": True, "reason": "ok",
            "discount_cents": discount,
            "final_cents": max(0, base_cents - discount),
            "attributed_ref_code": cp.attributed_ref_code}


def redeem(code: str) -> bool:
    """Mark one redemption; returns False if would exceed the limit."""
    c = _conn()
    row = c.execute(
        "SELECT redemptions, max_redemptions FROM coupons WHERE code=?",
        (code,),
    ).fetchone()
    if not row:
        c.close()
        return False
    red, maxr = row
    if maxr and red >= maxr:
        c.close()
        return False
    c.execute("UPDATE coupons SET redemptions = redemptions + 1 WHERE code=?", (code,))
    c.commit()
    c.close()
    return True
