"""Extra export formats: SDF (sdwriter from RDKit) + JSON Lines.

Buyers often request SDF (the cheminformatics-standard format) and JSONL
(for streaming into data pipelines). Both ship alongside Parquet/CSV.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

import pandas as pd
from rdkit import Chem


def export_sdf(conn: sqlite3.Connection, out_path: Path, limit: int | None = None) -> int:
    """Write SDF with all descriptor fields as properties on each molecule."""
    q = "SELECT * FROM molecules WHERE success=1 ORDER BY cid"
    if limit:
        q += f" LIMIT {int(limit)}"
    df = pd.read_sql_query(q, conn)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w = Chem.SDWriter(str(out_path))
    n = 0
    for _, row in df.iterrows():
        mol = Chem.MolFromSmiles(row["smiles"])
        if mol is None:
            continue
        for col, val in row.items():
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            mol.SetProp(str(col), str(val))
        w.write(mol)
        n += 1
    w.close()
    return n


def export_jsonl(conn: sqlite3.Connection, out_path: Path, limit: int | None = None) -> int:
    q = "SELECT * FROM molecules WHERE success=1 ORDER BY cid"
    if limit:
        q += f" LIMIT {int(limit)}"
    df = pd.read_sql_query(q, conn)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for _, row in df.iterrows():
            d = {k: (None if pd.isna(v) else v) for k, v in row.items()}
            fh.write(json.dumps(d, default=str))
            fh.write("\n")
    return len(df)
