"""Snapshot daily metrics so revenue / usage trend can be plotted.

Runs from worker.py once per day (after the HF publish step) and writes a row
into data/metrics.sqlite. Powers the /admin dashboard trend chart.
"""
from __future__ import annotations
import sqlite3
from datetime import date
from pathlib import Path

from src import keys as keysdb

DEFAULT_DB = Path("data/metrics.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    day TEXT PRIMARY KEY,
    molecules INTEGER,
    active_keys INTEGER,
    paid_keys INTEGER,
    month_smiles INTEGER,
    est_revenue INTEGER
);
"""

TIER_PRICE = {"free": 0, "research": 29, "commercial": 299,
              "redistribution": 999, "enterprise": 5000}


def _connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path or DEFAULT_DB)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.executescript(_SCHEMA)
    return conn


def snapshot(molecule_count: int, path: Path | str | None = None) -> dict:
    mc = metrics_today(molecule_count)
    conn = _connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO metrics "
        "(day, molecules, active_keys, paid_keys, month_smiles, est_revenue) "
        "VALUES (?,?,?,?,?,?)",
        (mc["day"], mc["molecules"], mc["active_keys"], mc["paid_keys"],
         mc["month_smiles"], mc["est_revenue"]),
    )
    conn.commit()
    conn.close()
    return mc


def metrics_today(molecule_count: int) -> dict:
    k = keysdb._connect()
    active = k.execute("SELECT COUNT(*) FROM api_keys WHERE active=1").fetchone()[0]
    paid = k.execute(
        "SELECT COUNT(*) FROM api_keys WHERE active=1 AND tier!='free'"
    ).fetchone()[0]
    month_smi = k.execute(
        "SELECT COALESCE(SUM(smiles_count),0) FROM usage "
        "WHERE ts >= datetime('now','start of month')"
    ).fetchone()[0]
    rev_rows = k.execute(
        "SELECT tier, COUNT(*) FROM api_keys WHERE active=1 GROUP BY tier"
    ).fetchall()
    k.close()
    revenue = sum(TIER_PRICE.get(t, 0) * n for t, n in rev_rows)
    return {
        "day": date.today().isoformat(),
        "molecules": molecule_count,
        "active_keys": active,
        "paid_keys": paid,
        "month_smiles": int(month_smi),
        "est_revenue": revenue,
    }


def history(limit: int = 30, path: Path | str | None = None) -> list[dict]:
    conn = _connect(path)
    rows = conn.execute(
        "SELECT day, molecules, active_keys, paid_keys, month_smiles, est_revenue "
        "FROM metrics ORDER BY day DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    cols = ["day", "molecules", "active_keys", "paid_keys", "month_smiles", "est_revenue"]
    return [dict(zip(cols, r)) for r in rows]
