"""Async batch job manager.

Large customers want to submit a big SMILES file and come back later. This
module stores jobs in SQLite, runs them on a background thread (single worker
is fine for now — scale to Celery/RQ when revenue justifies it), and exposes
status + download endpoints.

Jobs are charged against the owner's monthly quota at submit time (so we don't
do work without billing first) but refunded on failure.
"""
from __future__ import annotations
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src import compute, keys as keysdb

DEFAULT_DB = Path("data/jobs.sqlite")
JOBS_DIR = Path("data/jobs")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    api_key TEXT NOT NULL,
    status TEXT NOT NULL,          -- queued, running, done, failed
    n_smiles INTEGER NOT NULL,
    n_processed INTEGER DEFAULT 0,
    result_path TEXT,
    error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);
"""

_LOCK = threading.Lock()
_WORKER_STARTED = False


@dataclass
class JobInfo:
    id: str
    status: str
    n_smiles: int
    n_processed: int
    result_path: str | None
    error: str | None


def _connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path or DEFAULT_DB)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.executescript(_SCHEMA)
    return conn


def submit(api_key: str, smiles: list[str]) -> str:
    """Queue a job. Returns job id. Does NOT charge quota here — caller does.

    Input is written to data/jobs/<id>.input.json so worker doesn't hold it in RAM.
    """
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = f"job_{uuid.uuid4().hex[:16]}"
    in_path = JOBS_DIR / f"{job_id}.input.json"
    in_path.write_text(json.dumps(smiles))

    conn = _connect()
    conn.execute(
        "INSERT INTO jobs (id, api_key, status, n_smiles) VALUES (?,?,?,?)",
        (job_id, api_key, "queued", len(smiles)),
    )
    conn.commit()
    conn.close()
    return job_id


def get(job_id: str) -> JobInfo | None:
    conn = _connect()
    row = conn.execute(
        "SELECT id,status,n_smiles,n_processed,result_path,error FROM jobs WHERE id=?",
        (job_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return JobInfo(*row)


def owner(job_id: str) -> str | None:
    conn = _connect()
    row = conn.execute("SELECT api_key FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def _run_one(job_id: str) -> None:
    conn = _connect()
    row = conn.execute(
        "SELECT api_key, n_smiles FROM jobs WHERE id=?", (job_id,)
    ).fetchone()
    if not row:
        conn.close()
        return
    api_key, n_smiles = row
    conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
    conn.commit()
    conn.close()

    in_path = JOBS_DIR / f"{job_id}.input.json"
    out_path = JOBS_DIR / f"{job_id}.result.jsonl"

    try:
        smiles = json.loads(in_path.read_text())
        processed = 0
        with out_path.open("w", encoding="utf-8") as out:
            for i, smi in enumerate(smiles):
                r = compute.compute_molecule(cid=-(i + 1), smiles=smi)
                out.write(json.dumps(r.to_dict()) + "\n")
                processed += 1
                if processed % 50 == 0:
                    c2 = _connect()
                    c2.execute("UPDATE jobs SET n_processed=? WHERE id=?",
                               (processed, job_id))
                    c2.commit()
                    c2.close()
        c2 = _connect()
        c2.execute(
            "UPDATE jobs SET status='done', n_processed=?, result_path=?, "
            "finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (processed, str(out_path), job_id),
        )
        c2.commit()
        c2.close()
        # Best-effort outbound webhook
        try:
            from src import webhooks_out
            webhooks_out.deliver_async(api_key, "job.done", {
                "job_id": job_id, "status": "done", "n_processed": processed,
                "result_url": f"/jobs/{job_id}/result",
            })
        except Exception:
            pass
    except Exception as e:  # noqa: BLE001
        # Refund quota on failure
        try:
            keysdb.record(api_key, "/jobs/refund", -n_smiles)
        except Exception:
            pass
        c2 = _connect()
        c2.execute(
            "UPDATE jobs SET status='failed', error=?, finished_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (str(e)[:500], job_id),
        )
        c2.commit()
        c2.close()
        try:
            from src import webhooks_out
            webhooks_out.deliver_async(api_key, "job.failed", {
                "job_id": job_id, "status": "failed", "error": str(e)[:200],
            })
        except Exception:
            pass


def _worker_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        conn = _connect()
        row = conn.execute(
            "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            _run_one(row[0])
        else:
            stop_event.wait(2.0)


def start_worker() -> None:
    """Idempotent background worker starter."""
    global _WORKER_STARTED
    with _LOCK:
        if _WORKER_STARTED:
            return
        _WORKER_STARTED = True
        stop = threading.Event()
        t = threading.Thread(target=_worker_loop, args=(stop,), daemon=True,
                             name="qmol-jobs")
        t.start()


def run_pending_sync() -> int:
    """Run all queued jobs synchronously. Used in tests."""
    n = 0
    while True:
        conn = _connect()
        row = conn.execute(
            "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return n
        _run_one(row[0])
        n += 1
