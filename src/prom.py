"""Prometheus-format /metrics endpoint.

Gives enterprise buyers and ops teams a real monitoring integration —
drop it into Grafana Cloud / Datadog / whatever. This is a checkbox on
most enterprise security questionnaires and closes deals.
"""
from __future__ import annotations
import time
from typing import Iterable

from src import keys as keysdb


def _fmt(name: str, value: float, labels: dict[str, str] | None = None,
         help_text: str = "", type_: str = "gauge") -> list[str]:
    lines: list[str] = []
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {type_}")
    if labels:
        lbl = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f"{name}{{{lbl}}} {value}")
    else:
        lines.append(f"{name} {value}")
    return lines


def render() -> str:
    """Return Prometheus text exposition format."""
    out: list[str] = []
    c = keysdb._connect()

    # Total active keys
    n_keys = c.execute(
        "SELECT COUNT(*) FROM api_keys WHERE active=1"
    ).fetchone()[0]
    out += _fmt("qmol_api_keys_active", n_keys, help_text="Active API keys")

    # Keys by tier
    rows = c.execute(
        "SELECT tier, COUNT(*) FROM api_keys WHERE active=1 GROUP BY tier"
    ).fetchall()
    out.append("# HELP qmol_api_keys_by_tier Active API keys per tier")
    out.append("# TYPE qmol_api_keys_by_tier gauge")
    for tier, n in rows:
        out.append(f'qmol_api_keys_by_tier{{tier="{tier}"}} {n}')

    # Usage (calls) in last 24h
    try:
        n_calls = c.execute(
            "SELECT COUNT(*) FROM usage WHERE ts >= datetime('now','-1 day')"
        ).fetchone()[0]
    except Exception:
        n_calls = 0
    out += _fmt("qmol_api_calls_24h", n_calls,
                help_text="API calls in last 24h", type_="counter")

    # SMILES charged last 24h
    try:
        n_smi = c.execute(
            "SELECT COALESCE(SUM(smiles_count),0) FROM usage "
            "WHERE ts >= datetime('now','-1 day')"
        ).fetchone()[0] or 0
    except Exception:
        n_smi = 0
    out += _fmt("qmol_smiles_charged_24h", n_smi,
                help_text="SMILES charged in last 24h", type_="counter")

    # Jobs queued/running/done (last 24h)
    try:
        for status in ("queued", "running", "done", "failed"):
            n = c.execute(
                "SELECT COUNT(*) FROM jobs WHERE status=? "
                "AND created_at >= datetime('now','-1 day')",
                (status,),
            ).fetchone()[0]
            out.append(f'qmol_jobs_24h{{status="{status}"}} {n}')
    except Exception:
        pass

    c.close()
    out += _fmt("qmol_uptime_seconds", time.time() - _START,
                help_text="Process uptime seconds", type_="counter")
    return "\n".join(out) + "\n"


_START = time.time()
