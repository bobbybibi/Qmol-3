"""Smoke test: ingest 5 molecules, compute, store, export parquet. No HF upload.

Run as a script: ``python smoke_test.py`` (requires PubChem network access).

NOTE: the work lives under ``if __name__ == "__main__"`` on purpose. The file
name matches pytest's default ``*_test.py`` glob, so a bare ``pytest`` run would
otherwise import this module and execute the live PubChem ingestion at
collection time — which hangs anywhere without outbound network.
"""
import logging
from pathlib import Path

import config
from src import ingest, compute, storage


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    conn = storage.connect(config.DB_PATH)
    n = 0
    for rec in ingest.iter_cids(start_cid=702, batch_size=5):
        if n >= 5:
            break
        print(f"[{n}] CID={rec.cid} {rec.formula} {rec.smiles}")
        r = compute.compute_molecule(
            cid=rec.cid, smiles=rec.smiles, mw=rec.mw,
        )
        storage.upsert(conn, r.to_dict())
        print(f"    -> method={r.method} mw={r.mw} logp={r.logp} qed={r.qed} t={r.runtime_seconds:.2f}s")
        n += 1

    rows = storage.export_parquet(conn, config.PARQUET_PATH)
    print(f"\nExported {rows} rows -> {config.PARQUET_PATH}")
    print(f"DB size: {Path(config.DB_PATH).stat().st_size} bytes")


if __name__ == "__main__":
    main()
