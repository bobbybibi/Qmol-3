"""Main worker loop. Runs forever: ingest -> compute -> store -> publish."""
from __future__ import annotations
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

import config
from src import ingest, compute, storage, publish
from src import kaggle_publish, gumroad_publish

log = logging.getLogger("qmol.worker")

_running = True


def _stop(_sig, _frame):
    global _running
    log.info("Shutdown signal received, finishing current molecule…")
    _running = False


def run() -> None:
    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    conn = storage.connect(config.DB_PATH)
    state = storage.load_state(config.STATE_PATH)
    start_cid = int(state.get("next_cid", config.PUBCHEM_START_CID))
    log.info("Starting worker at CID=%s", start_cid)

    processed_since_publish = 0
    last_publish_time = datetime.now(timezone.utc)

    for rec in ingest.iter_cids(start_cid, batch_size=config.PUBCHEM_BATCH_SIZE):
        if not _running:
            break

        # Skip already-computed CIDs
        cur = conn.execute("SELECT 1 FROM molecules WHERE cid=?", (rec.cid,))
        if cur.fetchone():
            state["next_cid"] = rec.cid + 1
            storage.save_state(config.STATE_PATH, state)
            continue

        # Skip stereoisomer / tautomer duplicates by InChIKey
        from rdkit import Chem as _Chem
        from rdkit.Chem import inchi as _inchi
        _m_check = _Chem.MolFromSmiles(rec.smiles)
        if _m_check is not None:
            try:
                ikey = _inchi.MolToInchiKey(_m_check)
                if ikey:
                    dup = conn.execute(
                        "SELECT 1 FROM molecules WHERE inchikey=? LIMIT 1", (ikey,)
                    ).fetchone()
                    if dup:
                        log.info("skip CID=%s dup inchikey=%s", rec.cid, ikey)
                        state["next_cid"] = rec.cid + 1
                        storage.save_state(config.STATE_PATH, state)
                        continue
            except Exception:  # noqa: BLE001
                pass

        # Skip molecules too big for our compute budget
        from rdkit import Chem  # local import to avoid heavy import at module load
        m = Chem.MolFromSmiles(rec.smiles)
        if m is None or m.GetNumHeavyAtoms() > config.MAX_HEAVY_ATOMS:
            log.info("skip CID=%s smiles=%s (too large / invalid)", rec.cid, rec.smiles)
            state["next_cid"] = rec.cid + 1
            storage.save_state(config.STATE_PATH, state)
            continue

        log.info("compute CID=%s formula=%s smiles=%s", rec.cid, rec.formula, rec.smiles)
        result = compute.compute_molecule(
            cid=rec.cid,
            smiles=rec.smiles,
            basis=config.BASIS_SET,
            use_vqe_up_to_qubits=config.USE_VQE_UP_TO_QUBITS,
            max_seconds=config.MAX_CPU_SECONDS_PER_MOL,
            mw=rec.mw,
        )
        storage.upsert(conn, result.to_dict())
        state["next_cid"] = rec.cid + 1
        storage.save_state(config.STATE_PATH, state)

        if result.success:
            processed_since_publish += 1
            log.info(
                "  -> %s E=%.6f Ha qubits=%s t=%.1fs",
                result.method, result.energy_hartree or 0.0,
                result.num_qubits, result.runtime_seconds,
            )
        else:
            log.warning("  -> FAILED: %s", result.error)

        # Publish snapshot if threshold reached or interval elapsed
        now = datetime.now(timezone.utc)
        hours_since = (now - last_publish_time).total_seconds() / 3600
        if (
            processed_since_publish >= config.PUBLISH_EVERY_N_MOLECULES
            or hours_since >= config.SNAPSHOT_EVERY_HOURS
        ):
            publish_snapshot(conn)
            processed_since_publish = 0
            last_publish_time = now

    # Final snapshot before exit
    publish_snapshot(conn)
    conn.close()
    log.info("Worker stopped cleanly.")


def publish_snapshot(conn) -> None:
    n = storage.export_parquet(conn, config.PARQUET_PATH)
    log.info("Exported %s rows -> %s", n, config.PARQUET_PATH.name)

    # gather stats
    methods = {}
    for row in conn.execute(
        "SELECT method, COUNT(*) FROM molecules WHERE success=1 GROUP BY method"
    ):
        methods[row[0]] = row[1]
    stats = {"row_count": n, "methods": methods}

    ok = publish.publish_to_hf(
        config.PARQUET_PATH, config.HF_REPO_ID, config.HF_TOKEN, config.HF_PRIVATE
    )
    if ok:
        publish.write_dataset_card(
            config.PARQUET_PATH, config.HF_REPO_ID, config.HF_TOKEN, stats
        )

    # Build sellable bundle and push to marketplaces (no-op if creds missing)
    try:
        import build_release
        build_release.main()
    except Exception as e:  # noqa: BLE001
        log.warning("build_release failed: %s", e)

    try:
        kaggle_publish.publish_to_kaggle(
            __import__("pathlib").Path("release/qmol_full.parquet")
        )
    except Exception as e:  # noqa: BLE001
        log.warning("kaggle publish failed: %s", e)

    try:
        gumroad_publish.publish_release()
    except Exception as e:  # noqa: BLE001
        log.warning("gumroad publish failed: %s", e)

    # Daily metrics snapshot for admin dashboard trend chart
    try:
        from src import metrics as _metrics
        snap = _metrics.snapshot(stats["row_count"])
        log.info("metrics snapshot: %s", snap)
    except Exception as e:  # noqa: BLE001
        log.warning("metrics snapshot failed: %s", e)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
