"""Uptime / health pings storage, powering the public status page."""
from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from typing import List

DEFAULT_DB = Path("data/status.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pings (
    ts REAL NOT NULL,
    ok INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_pings_ts ON pings (ts);
"""


def _conn(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path or DEFAULT_DB)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p))
    c.executescript(_SCHEMA)
    return c


def record(ok: bool, latency_ms: float, note: str = "", path=None) -> None:
    c = _conn(path)
    c.execute("INSERT INTO pings (ts, ok, latency_ms, note) VALUES (?,?,?,?)",
              (time.time(), 1 if ok else 0, latency_ms, note))
    c.commit()
    c.close()


def summary(window_seconds: float = 24 * 3600, path=None) -> dict:
    cutoff = time.time() - window_seconds
    c = _conn(path)
    row = c.execute(
        "SELECT COUNT(*), COALESCE(SUM(ok),0), COALESCE(AVG(latency_ms),0) "
        "FROM pings WHERE ts >= ?",
        (cutoff,),
    ).fetchone()
    c.close()
    total, ok, avg = int(row[0]), int(row[1]), float(row[2])
    uptime = (ok / total) if total else 1.0
    return {
        "window_hours": window_seconds / 3600,
        "samples": total,
        "uptime": round(uptime, 4),
        "uptime_pct": round(uptime * 100, 2),
        "avg_latency_ms": round(avg, 1),
    }


def recent(limit: int = 100, path=None) -> List[dict]:
    c = _conn(path)
    rows = c.execute(
        "SELECT ts, ok, latency_ms, note FROM pings ORDER BY ts DESC LIMIT ?",
        (limit,),
    ).fetchall()
    c.close()
    return [{"ts": r[0], "ok": bool(r[1]), "latency_ms": r[2], "note": r[3]}
            for r in rows]
