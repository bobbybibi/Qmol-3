"""API-key scopes.

Restrict a key to a whitelist of endpoint prefixes. Useful for:
  - CI/CD keys that should only hit /compute
  - Public-read-only keys exposed in browser code
  - Team-member keys that shouldn't rotate or download bulk data

Stored as a separate table keyed by api_key. Absence of a row = unrestricted
(back-compat with existing keys).
"""
from __future__ import annotations
import json
import sqlite3
from typing import Sequence

from src import keys as keysdb

_SCHEMA = """
CREATE TABLE IF NOT EXISTS key_scopes (
    api_key   TEXT PRIMARY KEY,
    scopes    TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


def _conn() -> sqlite3.Connection:
    c = keysdb._connect()
    c.executescript(_SCHEMA)
    return c


# Well-known scopes. An endpoint path matches a scope if the scope is a prefix.
# Special value "*" = unrestricted.
KNOWN_SCOPES = {
    "*", "compute", "compute:premium", "similarity", "screen", "predict",
    "conformers", "reactions", "standardize", "tautomers", "scaffolds", "upload",
    "substructure", "diversity", "fingerprints", "cluster", "formula",
    "download", "export", "jobs", "usage",
    "audit", "invoice", "key:rotate", "teams", "webhooks", "referrals",
}


def set_scopes(api_key: str, scopes: Sequence[str]) -> list[str]:
    cleaned = sorted({s.strip().lower() for s in scopes if s and s.strip()})
    bad = [s for s in cleaned if s not in KNOWN_SCOPES]
    if bad:
        raise ValueError(f"Unknown scopes: {bad}. Known: {sorted(KNOWN_SCOPES)}")
    c = _conn()
    try:
        c.execute(
            "INSERT INTO key_scopes(api_key, scopes) VALUES(?,?) "
            "ON CONFLICT(api_key) DO UPDATE SET "
            "  scopes=excluded.scopes, updated_at=datetime('now')",
            (api_key, json.dumps(cleaned)),
        )
        c.commit()
    finally:
        c.close()
    return cleaned


def get_scopes(api_key: str) -> list[str] | None:
    """Return None = unrestricted; list (possibly empty) = restricted."""
    c = _conn()
    try:
        row = c.execute("SELECT scopes FROM key_scopes WHERE api_key=?",
                        (api_key,)).fetchone()
        if not row:
            return None
        return json.loads(row[0])
    finally:
        c.close()


def clear_scopes(api_key: str) -> None:
    c = _conn()
    try:
        c.execute("DELETE FROM key_scopes WHERE api_key=?", (api_key,))
        c.commit()
    finally:
        c.close()


def path_to_scope(path: str) -> str:
    """Canonical scope for an endpoint path."""
    p = path.strip("/").lower()
    if p == "compute/premium":
        return "compute:premium"
    if p == "key/rotate":
        return "key:rotate"
    # first segment after /
    return p.split("/", 1)[0] if p else ""


def allowed(api_key: str, path: str) -> bool:
    sc = get_scopes(api_key)
    if sc is None:     # unrestricted
        return True
    if "*" in sc:
        return True
    needed = path_to_scope(path)
    if needed in sc:
        return True
    # allow prefix matches for things like "compute" matching "compute:premium"
    if any(needed.startswith(s + ":") for s in sc):
        return True
    return False
