"""SQLite + Parquet storage and ingestion metadata."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

MOLECULES_SCHEMA = """
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
    source_name TEXT,
    source_record_id TEXT,
    source_license TEXT,
    raw_smiles TEXT,
    source_metadata TEXT,
    provenance_json TEXT,
    ingested_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_success ON molecules(success);
CREATE INDEX IF NOT EXISTS idx_inchikey ON molecules(inchikey);
CREATE INDEX IF NOT EXISTS idx_scaffold ON molecules(murcko_scaffold);
"""

MOLECULE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_molecules_source ON molecules(source_name, source_record_id);
CREATE INDEX IF NOT EXISTS idx_molecules_smiles ON molecules(smiles);
"""

SOURCE_MAPPINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS molecule_sources (
    source_name TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    cid INTEGER,
    canonical_smiles TEXT NOT NULL,
    source_license TEXT,
    metadata_json TEXT,
    provenance_json TEXT,
    raw_smiles TEXT,
    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP,
    is_duplicate INTEGER DEFAULT 0,
    duplicate_of_cid INTEGER,
    PRIMARY KEY (source_name, source_record_id)
);
CREATE INDEX IF NOT EXISTS idx_sources_cid ON molecule_sources(cid);
CREATE INDEX IF NOT EXISTS idx_sources_dup ON molecule_sources(duplicate_of_cid);
"""

RAW_SNAPSHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_record_id TEXT,
    canonical_smiles TEXT,
    payload_json TEXT,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_raw_run ON raw_snapshots(run_id);
CREATE INDEX IF NOT EXISTS idx_raw_source ON raw_snapshots(source_name, source_record_id);
"""

INGESTION_SOURCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingestion_sources (
    source_name TEXT PRIMARY KEY,
    next_cursor TEXT,
    sync_interval_minutes INTEGER NOT NULL DEFAULT 60,
    paused INTEGER NOT NULL DEFAULT 0,
    last_run_started_at TEXT,
    last_run_finished_at TEXT,
    last_success_at TEXT,
    last_error_at TEXT,
    last_error TEXT,
    total_requested INTEGER NOT NULL DEFAULT 0,
    total_accepted INTEGER NOT NULL DEFAULT 0,
    total_duplicates INTEGER NOT NULL DEFAULT 0,
    total_invalid INTEGER NOT NULL DEFAULT 0
);
"""

INGESTION_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    start_cursor TEXT,
    next_cursor TEXT,
    requested INTEGER NOT NULL DEFAULT 0,
    fetched INTEGER NOT NULL DEFAULT 0,
    accepted INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    invalid INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingestion_runs_source ON ingestion_runs(source_name, started_at DESC);
"""

MOLECULE_EXTRA_COLUMNS = {
    "source_name": "TEXT",
    "source_record_id": "TEXT",
    "source_license": "TEXT",
    "raw_smiles": "TEXT",
    "source_metadata": "TEXT",
    "provenance_json": "TEXT",
    "ingested_at": "TEXT",
}

MOLECULE_COLUMNS = [
    "cid", "smiles", "method", "basis", "num_atoms", "num_heavy_atoms",
    "num_electrons", "num_qubits", "energy_hartree", "homo_hartree",
    "lumo_hartree", "dipole_debye", "mw", "logp", "tpsa", "hbd", "hba",
    "rotatable_bonds", "ring_count", "aromatic_rings", "qed", "ecfp4_hash",
    "inchikey", "murcko_scaffold", "fsp3", "heteroatom_count",
    "formal_charge", "stereo_centers", "mol_refractivity", "lipinski_pass",
    "veber_pass", "pains_hit", "runtime_seconds", "success", "error",
    "source_name", "source_record_id", "source_license", "raw_smiles",
    "source_metadata", "provenance_json", "ingested_at",
]


def _row_to_dict(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict[str, Any]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _ensure_columns(conn: sqlite3.Connection, table: str,
                    required: dict[str, str]) -> None:
    existing = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, typ in required.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(MOLECULES_SCHEMA)
    _ensure_columns(conn, "molecules", MOLECULE_EXTRA_COLUMNS)
    conn.executescript(MOLECULE_INDEXES)
    conn.executescript(SOURCE_MAPPINGS_SCHEMA)
    conn.executescript(RAW_SNAPSHOTS_SCHEMA)
    conn.executescript(INGESTION_SOURCES_SCHEMA)
    conn.executescript(INGESTION_RUNS_SCHEMA)
    conn.commit()
    return conn


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def upsert(conn: sqlite3.Connection, row: dict) -> None:
    placeholders = ",".join(["?"] * len(MOLECULE_COLUMNS))
    col_list = ",".join(MOLECULE_COLUMNS)
    values = [row.get(c) for c in MOLECULE_COLUMNS]
    values[MOLECULE_COLUMNS.index("success")] = 1 if row.get("success") else 0
    for key in ("source_metadata", "provenance_json"):
        idx = MOLECULE_COLUMNS.index(key)
        values[idx] = _json_or_none(values[idx])
    conn.execute(
        f"INSERT OR REPLACE INTO molecules ({col_list}) VALUES ({placeholders})",
        values,
    )
    conn.commit()


def record_source_mapping(conn: sqlite3.Connection, *, source_name: str,
                          source_record_id: str, canonical_smiles: str,
                          source_license: str | None = None,
                          metadata_json: Any = None,
                          provenance_json: Any = None,
                          raw_smiles: str | None = None,
                          ingested_at: str | None = None,
                          cid: int | None = None,
                          is_duplicate: bool = False,
                          duplicate_of_cid: int | None = None) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO molecule_sources (
            source_name, source_record_id, cid, canonical_smiles, source_license,
            metadata_json, provenance_json, raw_smiles, ingested_at, is_duplicate,
            duplicate_of_cid
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            source_name,
            source_record_id,
            cid,
            canonical_smiles,
            source_license,
            _json_or_none(metadata_json),
            _json_or_none(provenance_json),
            raw_smiles,
            ingested_at,
            1 if is_duplicate else 0,
            duplicate_of_cid,
        ),
    )
    conn.commit()


def record_raw_snapshot(conn: sqlite3.Connection, *, run_id: str, source_name: str,
                        source_record_id: str | None, canonical_smiles: str | None,
                        payload_json: Any) -> None:
    conn.execute(
        """
        INSERT INTO raw_snapshots (run_id, source_name, source_record_id, canonical_smiles, payload_json)
        VALUES (?,?,?,?,?)
        """,
        (run_id, source_name, source_record_id, canonical_smiles, _json_or_none(payload_json)),
    )
    conn.commit()


def ensure_ingestion_sources(conn: sqlite3.Connection,
                             sources: dict[str, dict[str, Any]]) -> None:
    for source_name, details in sources.items():
        conn.execute(
            """
            INSERT INTO ingestion_sources (source_name, next_cursor, sync_interval_minutes, paused)
            VALUES (?,?,?,?)
            ON CONFLICT(source_name) DO UPDATE SET
                sync_interval_minutes=excluded.sync_interval_minutes
            """,
            (
                source_name,
                str(details.get("start_cursor", "")),
                int(details.get("sync_interval_minutes", 60)),
                0 if details.get("active", False) else 1,
            ),
        )
    conn.commit()


def set_source_cursor_if_empty(conn: sqlite3.Connection, source_name: str,
                               cursor: str | int | None) -> None:
    if cursor is None:
        return
    row = conn.execute(
        "SELECT next_cursor FROM ingestion_sources WHERE source_name=?",
        (source_name,),
    ).fetchone()
    if row and (row["next_cursor"] is None or str(row["next_cursor"]).strip() == ""):
        conn.execute(
            "UPDATE ingestion_sources SET next_cursor=? WHERE source_name=?",
            (str(cursor), source_name),
        )
        conn.commit()


def list_ingestion_sources(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT * FROM ingestion_sources ORDER BY source_name"
    )
    return [_row_to_dict(cur, row) for row in cur.fetchall()]


def get_ingestion_source(conn: sqlite3.Connection, source_name: str) -> dict[str, Any] | None:
    cur = conn.execute(
        "SELECT * FROM ingestion_sources WHERE source_name=?",
        (source_name,),
    )
    row = cur.fetchone()
    return _row_to_dict(cur, row) if row else None


def list_due_ingestion_sources(conn: sqlite3.Connection,
                               active_sources: list[str]) -> list[dict[str, Any]]:
    if not active_sources:
        return []
    placeholders = ",".join("?" for _ in active_sources)
    cur = conn.execute(
        f"""
        SELECT * FROM ingestion_sources
        WHERE paused=0
          AND source_name IN ({placeholders})
          AND (
              last_run_finished_at IS NULL OR
              datetime(last_run_finished_at, '+' || sync_interval_minutes || ' minutes')
                  <= datetime('now')
          )
        ORDER BY COALESCE(last_run_finished_at, '1970-01-01T00:00:00')
        """,
        tuple(active_sources),
    )
    return [_row_to_dict(cur, row) for row in cur.fetchall()]


def begin_ingestion_run(conn: sqlite3.Connection, source_name: str,
                        start_cursor: str | int, requested: int) -> str:
    run_id = f"ing_{uuid.uuid4().hex[:16]}"
    conn.execute(
        """
        INSERT INTO ingestion_runs (run_id, source_name, status, start_cursor, requested)
        VALUES (?,?,?,?,?)
        """,
        (run_id, source_name, "running", str(start_cursor), requested),
    )
    conn.execute(
        "UPDATE ingestion_sources SET last_run_started_at=CURRENT_TIMESTAMP WHERE source_name=?",
        (source_name,),
    )
    conn.commit()
    return run_id


def finish_ingestion_run(conn: sqlite3.Connection, *, run_id: str, source_name: str,
                         next_cursor: str | int, fetched: int, accepted: int,
                         duplicates: int, invalid: int, error: str | None = None) -> None:
    status = "failed" if error else "ok"
    conn.execute(
        """
        UPDATE ingestion_runs
        SET status=?, finished_at=CURRENT_TIMESTAMP, next_cursor=?, fetched=?,
            accepted=?, duplicates=?, invalid=?, error=?
        WHERE run_id=?
        """,
        (status, str(next_cursor), fetched, accepted, duplicates, invalid, error, run_id),
    )
    conn.execute(
        """
        UPDATE ingestion_sources
        SET next_cursor=?,
            last_run_finished_at=CURRENT_TIMESTAMP,
            last_success_at=CASE WHEN ? IS NULL THEN CURRENT_TIMESTAMP ELSE last_success_at END,
            last_error_at=CASE WHEN ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE last_error_at END,
            last_error=?,
            total_requested=total_requested + ?,
            total_accepted=total_accepted + ?,
            total_duplicates=total_duplicates + ?,
            total_invalid=total_invalid + ?
        WHERE source_name=?
        """,
        (
            str(next_cursor),
            error,
            error,
            error,
            fetched,
            accepted,
            duplicates,
            invalid,
            source_name,
        ),
    )
    conn.commit()


def list_ingestion_runs(conn: sqlite3.Connection, source_name: str | None = None,
                        limit: int = 50) -> list[dict[str, Any]]:
    if source_name:
        cur = conn.execute(
            """
            SELECT * FROM ingestion_runs
            WHERE source_name=?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (source_name, limit),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM ingestion_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
    return [_row_to_dict(cur, row) for row in cur.fetchall()]


def list_raw_snapshots(conn: sqlite3.Connection, source_name: str | None = None,
                       limit: int = 50) -> list[dict[str, Any]]:
    if source_name:
        cur = conn.execute(
            """
            SELECT * FROM raw_snapshots
            WHERE source_name=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (source_name, limit),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM raw_snapshots ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    return [_row_to_dict(cur, row) for row in cur.fetchall()]


def list_molecules(conn: sqlite3.Connection, *, source_name: str | None = None,
                   limit: int = 100, success_only: bool = False) -> list[dict[str, Any]]:
    where = []
    params: list[Any] = []
    if source_name:
        where.append("source_name=?")
        params.append(source_name)
    if success_only:
        where.append("success=1")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    cur = conn.execute(
        f"""
        SELECT cid, smiles, mw, source_name, source_record_id, source_license,
               raw_smiles, source_metadata, provenance_json, ingested_at, success, error
        FROM molecules
        {clause}
        ORDER BY cid DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    rows = [_row_to_dict(cur, row) for row in cur.fetchall()]
    for row in rows:
        for field in ("source_metadata", "provenance_json"):
            if row.get(field):
                row[field] = json.loads(row[field])
    return rows


def get_source_mapping(conn: sqlite3.Connection, source_name: str,
                       source_record_id: str) -> dict[str, Any] | None:
    cur = conn.execute(
        """
        SELECT * FROM molecule_sources
        WHERE source_name=? AND source_record_id=?
        """,
        (source_name, source_record_id),
    )
    row = cur.fetchone()
    if not row:
        return None
    out = _row_to_dict(cur, row)
    for field in ("metadata_json", "provenance_json"):
        if out.get(field):
            out[field] = json.loads(out[field])
    return out


def find_molecule_by_smiles(conn: sqlite3.Connection, smiles: str) -> int | None:
    row = conn.execute(
        "SELECT cid FROM molecules WHERE smiles=? LIMIT 1",
        (smiles,),
    ).fetchone()
    return int(row["cid"]) if row else None


def find_molecule_by_inchikey(conn: sqlite3.Connection, inchikey: str | None) -> int | None:
    if not inchikey:
        return None
    row = conn.execute(
        "SELECT cid FROM molecules WHERE inchikey=? LIMIT 1",
        (inchikey,),
    ).fetchone()
    return int(row["cid"]) if row else None


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
