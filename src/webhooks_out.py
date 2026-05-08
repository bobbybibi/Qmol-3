"""Outbound webhooks: notify customers when their async jobs finish.

Users register a target URL per-key; we POST {job_id, status, result_url}
on completion. Deliveries are logged and retried up to N times.
"""
from __future__ import annotations
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # tests can monkeypatch

from src import keys as keysdb

MAX_ATTEMPTS = 5
BACKOFF_BASE = 2.0  # seconds

_SCHEMA = """
CREATE TABLE IF NOT EXISTS webhooks (
    api_key TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    secret TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT,
    url TEXT,
    event TEXT,
    payload TEXT,
    attempts INTEGER DEFAULT 0,
    last_status INTEGER,
    last_error TEXT,
    delivered INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass
class Subscription:
    api_key: str
    url: str
    secret: str | None


def _conn() -> sqlite3.Connection:
    c = keysdb._connect()
    c.executescript(_SCHEMA)
    return c


def subscribe(api_key: str, url: str, secret: str | None = None) -> Subscription:
    c = _conn()
    c.execute(
        "INSERT OR REPLACE INTO webhooks (api_key, url, secret) VALUES (?,?,?)",
        (api_key, url, secret),
    )
    c.commit()
    c.close()
    return Subscription(api_key=api_key, url=url, secret=secret)


def unsubscribe(api_key: str) -> None:
    c = _conn()
    c.execute("DELETE FROM webhooks WHERE api_key=?", (api_key,))
    c.commit()
    c.close()


def get(api_key: str) -> Subscription | None:
    c = _conn()
    row = c.execute(
        "SELECT api_key, url, secret FROM webhooks WHERE api_key=?",
        (api_key,),
    ).fetchone()
    c.close()
    if not row:
        return None
    return Subscription(*row)


def deliver(api_key: str, event: str, payload: dict[str, Any]) -> bool:
    """Attempt delivery. Returns True on success. Logs every attempt."""
    sub = get(api_key)
    if not sub or requests is None:
        return False
    body = json.dumps({"event": event, **payload})
    headers = {"content-type": "application/json"}
    if sub.secret:
        import hashlib
        import hmac
        sig = hmac.new(sub.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        headers["x-qmol-signature"] = f"sha256={sig}"

    last_status: int | None = None
    last_err: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = requests.post(sub.url, data=body, headers=headers, timeout=15)
            last_status = r.status_code
            if 200 <= r.status_code < 300:
                _log(api_key, sub.url, event, body, attempt, last_status, None, True)
                return True
            last_err = f"non-2xx: {r.status_code} {r.text[:200]}"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:500]
        if attempt < MAX_ATTEMPTS:
            time.sleep(BACKOFF_BASE ** attempt)
    _log(api_key, sub.url, event, body, MAX_ATTEMPTS, last_status, last_err, False)
    return False


def deliver_async(api_key: str, event: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget background delivery."""
    t = threading.Thread(target=deliver, args=(api_key, event, payload), daemon=True)
    t.start()


def _log(api_key, url, event, body, attempts, status, error, delivered):
    c = _conn()
    c.execute(
        "INSERT INTO webhook_deliveries "
        "(api_key, url, event, payload, attempts, last_status, last_error, delivered) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (api_key, url, event, body, attempts, status, error, 1 if delivered else 0),
    )
    c.commit()
    c.close()
