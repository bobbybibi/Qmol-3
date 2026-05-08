"""API-key management + usage tracking (SQLite).

Schema:
  api_keys(key PK, email, tier, monthly_quota, created_at, active)
  usage(ts, key, endpoint, smiles_count)

Tiers map to monthly quotas (SMILES processed per calendar month):
  free        -> 500        (no key needed; tracked by IP elsewhere)
  research    -> 10_000
  commercial  -> 100_000
  redistrib   -> 1_000_000

Called from:
  - stripe_webhook.deliver() when a purchase completes
  - api.py  to authenticate + increment usage

Local test:
    python -c "from src.keys import provision; print(provision('a@b.com','commercial'))"
"""
from __future__ import annotations
import hashlib
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB = Path(os.getenv("QMOL_KEYS_DB", "data/keys.sqlite"))

TIER_QUOTA = {
    "free": 500,
    "research": 10_000,
    "commercial": 100_000,
    "redistribution": 1_000_000,
    "enterprise": 10_000_000,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    key           TEXT PRIMARY KEY,
    email         TEXT NOT NULL,
    tier          TEXT NOT NULL,
    monthly_quota INTEGER NOT NULL,
    created_at    TEXT DEFAULT (datetime('now')),
    active        INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_email ON api_keys(email);

CREATE TABLE IF NOT EXISTS usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT DEFAULT (datetime('now')),
    key           TEXT NOT NULL,
    endpoint      TEXT,
    smiles_count  INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_usage_key ON usage(key);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);
"""


@dataclass
class KeyInfo:
    key: str
    email: str
    tier: str
    monthly_quota: int
    active: bool


def _connect(db: Path | None = None) -> sqlite3.Connection:
    db = db or DEFAULT_DB
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _generate(email: str) -> str:
    rand = secrets.token_hex(16)
    tag = hashlib.sha256(f"{email}|{rand}|{time.time()}".encode()).hexdigest()[:24]
    return f"qmol_{tag}"


def provision(email: str, tier: str = "research", db: Path | None = None) -> KeyInfo:
    """Create (or return existing active) API key for buyer+tier."""
    tier = tier.lower()
    if tier not in TIER_QUOTA:
        raise ValueError(f"unknown tier: {tier}")
    quota = TIER_QUOTA[tier]
    conn = _connect(db)
    row = conn.execute(
        "SELECT key FROM api_keys WHERE email=? AND tier=? AND active=1",
        (email, tier),
    ).fetchone()
    if row:
        k = row[0]
    else:
        k = _generate(email)
        conn.execute(
            "INSERT INTO api_keys (key, email, tier, monthly_quota) VALUES (?,?,?,?)",
            (k, email, tier, quota),
        )
        conn.commit()
    conn.close()
    return KeyInfo(key=k, email=email, tier=tier, monthly_quota=quota, active=True)


def lookup(key: str, db: Path | None = None) -> KeyInfo | None:
    conn = _connect(db)
    row = conn.execute(
        "SELECT key, email, tier, monthly_quota, active FROM api_keys WHERE key=?",
        (key,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return KeyInfo(key=row[0], email=row[1], tier=row[2],
                   monthly_quota=row[3], active=bool(row[4]))


def month_usage(key: str, db: Path | None = None) -> int:
    conn = _connect(db)
    row = conn.execute(
        "SELECT COALESCE(SUM(smiles_count),0) FROM usage "
        "WHERE key=? AND ts >= datetime('now','start of month')",
        (key,),
    ).fetchone()
    conn.close()
    return int(row[0])


def record(key: str, endpoint: str, smiles_count: int,
           db: Path | None = None) -> None:
    conn = _connect(db)
    conn.execute(
        "INSERT INTO usage (key, endpoint, smiles_count) VALUES (?,?,?)",
        (key, endpoint, smiles_count),
    )
    conn.commit()
    conn.close()


def deactivate(key: str, db: Path | None = None) -> None:
    conn = _connect(db)
    conn.execute("UPDATE api_keys SET active=0 WHERE key=?", (key,))
    conn.commit()
    conn.close()
