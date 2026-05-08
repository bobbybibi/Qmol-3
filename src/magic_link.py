"""Magic-link login: email a one-time token that returns the user's API key.

Key recovery without passwords. Tokens are short-lived (15 minutes),
single-use, and hashed in storage.
"""
from __future__ import annotations
import hashlib
import secrets
import sqlite3
import time

from src import keys as keysdb

TOKEN_TTL_SECONDS = 15 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS magic_tokens (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    issued_at REAL NOT NULL,
    used_at REAL
);
"""


def _conn() -> sqlite3.Connection:
    c = keysdb._connect()
    c.executescript(_SCHEMA)
    return c


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(email: str) -> str:
    """Return a raw token to send by email. Only the hash is stored."""
    token = secrets.token_urlsafe(24)
    c = _conn()
    c.execute(
        "INSERT OR REPLACE INTO magic_tokens (token_hash, email, issued_at) VALUES (?,?,?)",
        (_hash(token), email, time.time()),
    )
    c.commit()
    c.close()
    return token


def consume(token: str) -> str | None:
    """Validate a token and return the matching API key, or None.

    The token is burned on successful use.
    """
    h = _hash(token)
    c = _conn()
    row = c.execute(
        "SELECT email, issued_at, used_at FROM magic_tokens WHERE token_hash=?",
        (h,),
    ).fetchone()
    if not row:
        c.close()
        return None
    email, issued, used = row
    if used is not None:
        c.close()
        return None
    if time.time() - issued > TOKEN_TTL_SECONDS:
        c.close()
        return None
    # Find the user's existing API key (most recent active)
    k = c.execute(
        "SELECT key FROM api_keys WHERE email=? AND active=1 "
        "ORDER BY created_at DESC LIMIT 1",
        (email,),
    ).fetchone()
    c.execute("UPDATE magic_tokens SET used_at=? WHERE token_hash=?",
              (time.time(), h))
    c.commit()
    c.close()
    return k[0] if k else None
