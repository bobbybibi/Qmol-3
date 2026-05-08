"""CSV / JSONL export helpers for audit and invoice data."""
from __future__ import annotations
import csv
import io
import json
from typing import Iterable, Sequence


def to_csv(rows: Sequence[dict], columns: Sequence[str] | None = None) -> str:
    if not rows:
        return ""
    cols = list(columns) if columns else list(rows[0].keys())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def to_jsonl(rows: Iterable[dict]) -> str:
    return "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else "")
