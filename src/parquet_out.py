"""Parquet export helpers.

Customers want columnar output for BI tools / data-science pipelines.
"""
from __future__ import annotations
from io import BytesIO
from typing import Sequence

import pandas as pd


def to_parquet_bytes(rows: Sequence[dict]) -> bytes:
    """Return a Parquet file (snappy-compressed) as bytes."""
    if not rows:
        df = pd.DataFrame()
    else:
        df = pd.DataFrame(list(rows))
    buf = BytesIO()
    df.to_parquet(buf, engine="pyarrow", compression="snappy", index=False)
    return buf.getvalue()
