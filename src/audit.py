"""Structured JSON request log + audit trail.

Every non-public request is written as a single JSON line to logs/api.jsonl
AND into a sqlite audit table (so we can query it for invoices, forensics,
abuse detection). Downstream: ship logs/api.jsonl to Loki/Datadog/S3.
"""
from __future__ import annotations
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from src import keys as keysdb

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "api.jsonl"
_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT DEFAULT CURRENT_TIMESTAMP,
    api_key TEXT,
    ip TEXT,
    method TEXT,
    path TEXT,
    status INTEGER,
    ms INTEGER,
    n_smiles INTEGER DEFAULT 0,
    extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_key ON audit(api_key);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
"""


def _conn() -> sqlite3.Connection:
    c = keysdb._connect()
    c.executescript(_SCHEMA)
    return c


def log_event(api_key: str | None, ip: str | None, method: str, path: str,
              status: int, ms: int, n_smiles: int = 0,
              extra: dict[str, Any] | None = None) -> None:
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "api_key": (api_key[:12] + "…") if api_key else None,
        "ip": ip, "method": method, "path": path,
        "status": status, "ms": ms, "n_smiles": n_smiles,
    }
    if extra:
        rec.update(extra)
    # File: best-effort
    try:
        LOG_DIR.mkdir(exist_ok=True)
        with _LOCK, LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass
    # SQLite: always
    try:
        c = _conn()
        c.execute(
            "INSERT INTO audit (api_key, ip, method, path, status, ms, n_smiles, extra) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (api_key, ip, method, path, status, ms, n_smiles,
             json.dumps(extra) if extra else None),
        )
        c.commit()
        c.close()
    except Exception:
        pass


def recent(api_key: str, limit: int = 100) -> list[dict]:
    c = _conn()
    rows = c.execute(
        "SELECT ts, method, path, status, ms, n_smiles "
        "FROM audit WHERE api_key=? ORDER BY id DESC LIMIT ?",
        (api_key, limit),
    ).fetchall()
    c.close()
    cols = ["ts", "method", "path", "status", "ms", "n_smiles"]
    return [dict(zip(cols, r)) for r in rows]
