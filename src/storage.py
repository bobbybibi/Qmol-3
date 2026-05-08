"""SQLite + Parquet storage."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS molecules (
    cid INTEGER PRIMARY KEY,
    smiles TEXT NOT NULL,
    method TEXT,
    basis TEXT,
    num_atoms INTEGER,
    num_heavy_atoms INTEGER,
    num_electrons INTEGER,
    num_qubits INTEGER,
    energy_hartree REAL,
    homo_hartree REAL,
    lumo_hartree REAL,
    dipole_debye REAL,
    mw REAL,
    logp REAL,
    tpsa REAL,
    hbd INTEGER,
    hba INTEGER,
    rotatable_bonds INTEGER,
    ring_count INTEGER,
    aromatic_rings INTEGER,
    qed REAL,
    ecfp4_hash TEXT,
    inchikey TEXT,
    murcko_scaffold TEXT,
    fsp3 REAL,
    heteroatom_count INTEGER,
    formal_charge INTEGER,
    stereo_centers INTEGER,
    mol_refractivity REAL,
    lipinski_pass INTEGER,
    veber_pass INTEGER,
    pains_hit INTEGER,
    runtime_seconds REAL,
    success INTEGER,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_success ON molecules(success);
CREATE INDEX IF NOT EXISTS idx_inchikey ON molecules(inchikey);
CREATE INDEX IF NOT EXISTS idx_scaffold ON molecules(murcko_scaffold);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def upsert(conn: sqlite3.Connection, row: dict) -> None:
    cols = [
        "cid", "smiles", "method", "basis", "num_atoms", "num_heavy_atoms",
        "num_electrons", "num_qubits", "energy_hartree", "homo_hartree",
        "lumo_hartree", "dipole_debye",
        "mw", "logp", "tpsa", "hbd", "hba", "rotatable_bonds",
        "ring_count", "aromatic_rings", "qed", "ecfp4_hash",
        "inchikey", "murcko_scaffold", "fsp3", "heteroatom_count",
        "formal_charge", "stereo_centers", "mol_refractivity",
        "lipinski_pass", "veber_pass", "pains_hit",
        "runtime_seconds", "success", "error",
    ]
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    values = [row.get(c) for c in cols]
    values[cols.index("success")] = 1 if row.get("success") else 0
    conn.execute(
        f"INSERT OR REPLACE INTO molecules ({col_list}) VALUES ({placeholders})",
        values,
    )
    conn.commit()


def export_parquet(conn: sqlite3.Connection, out_path: Path) -> int:
    df = pd.read_sql_query(
        "SELECT * FROM molecules WHERE success=1 ORDER BY cid", conn
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    return len(df)


def export_csv(conn: sqlite3.Connection, out_path: Path) -> int:
    df = pd.read_sql_query(
        "SELECT * FROM molecules WHERE success=1 ORDER BY cid", conn
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return len(df)


def export_sample(conn: sqlite3.Connection, out_path: Path, n: int = 100) -> int:
    """Export a free sample (first N rows) for marketing/Gumroad preview."""
    df = pd.read_sql_query(
        "SELECT * FROM molecules WHERE success=1 ORDER BY cid LIMIT ?",
        conn, params=(n,),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return len(df)


def row_count(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COUNT(*) FROM molecules WHERE success=1")
    return cur.fetchone()[0]


def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text())


def save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))
