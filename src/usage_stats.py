"""Per-day usage aggregation and SLO/uptime helpers.

Reads from the audit log table to build chart-ready time series.
`audit.ts` is a sqlite `CURRENT_TIMESTAMP` (ISO text) — we use datetime().
"""
from __future__ import annotations
import sqlite3

from src import audit, keys as keysdb


def _conn() -> sqlite3.Connection:
    c = keysdb._connect()
    c.executescript(audit._SCHEMA)
    return c


def daily_counts(api_key: str, days: int = 30) -> list[dict]:
    """Return [{day: YYYY-MM-DD, calls, smiles}] for the last `days`."""
    con = _conn()
    try:
        cur = con.execute(
            f"""SELECT substr(ts,1,10) AS day,
                       COUNT(*) AS calls,
                       COALESCE(SUM(n_smiles), 0) AS smiles
                FROM audit
                WHERE api_key = ?
                  AND ts >= datetime('now', '-{int(days)} days')
                GROUP BY day ORDER BY day ASC""",
            (api_key,),
        )
        return [{"day": r[0], "calls": r[1], "smiles": r[2]} for r in cur]
    finally:
        con.close()


def endpoint_breakdown(api_key: str, days: int = 30) -> list[dict]:
    con = _conn()
    try:
        cur = con.execute(
            f"""SELECT path, COUNT(*) AS calls,
                       COALESCE(SUM(n_smiles), 0) AS smiles
                FROM audit
                WHERE api_key = ?
                  AND ts >= datetime('now', '-{int(days)} days')
                GROUP BY path ORDER BY calls DESC""",
            (api_key,),
        )
        return [{"endpoint": r[0], "calls": r[1], "smiles": r[2]} for r in cur]
    finally:
        con.close()


def global_slo(days: int = 7) -> dict:
    """Global uptime SLO across all keys (last `days` days).

    A call counts as successful when status < 500. SLO = ok / total.
    """
    con = _conn()
    try:
        cur = con.execute(
            f"""SELECT
                 SUM(CASE WHEN status < 500 THEN 1 ELSE 0 END) AS ok,
                 SUM(CASE WHEN status >= 500 THEN 1 ELSE 0 END) AS err,
                 COUNT(*) AS total
               FROM audit
               WHERE ts >= datetime('now', '-{int(days)} days')""",
        )
        row = cur.fetchone() or (0, 0, 0)
        ok, err, total = (row[0] or 0), (row[1] or 0), (row[2] or 0)
        slo = (ok / total) if total else 1.0
        return {"days": days, "ok": ok, "errors": err, "total": total,
                "slo": round(slo, 6)}
    finally:
        con.close()
