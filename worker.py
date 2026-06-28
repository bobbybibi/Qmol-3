"""Main worker loop. Runs forever: ingest -> compute -> store -> publish."""
from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, timezone

from rdkit import Chem
from rdkit.Chem import inchi

import config
from src import compute, gumroad_publish, ingest, kaggle_publish, publish, storage

log = logging.getLogger("qmol.worker")

_running = True


def _stop(_sig, _frame):
    global _running
    log.info("Shutdown signal received, finishing current sync run…")
    _running = False


def _merge_result(rec: ingest.MoleculeRecord, result) -> dict:
    row = result.to_dict()
    row.update(
        {
            "source_name": rec.source_name,
            "source_record_id": rec.source_record_id,
            "source_license": rec.source_license,
            "raw_smiles": rec.raw_smiles,
            "source_metadata": rec.metadata,
            "provenance_json": rec.provenance,
            "ingested_at": rec.ingested_at,
            "smiles": rec.smiles,
        }
    )
    return row


def _precompute_duplicate(conn, rec: ingest.MoleculeRecord) -> int | None:
    source_existing = storage.get_source_mapping(
        conn, rec.source_name, rec.source_record_id or str(rec.cid)
    )
    if source_existing:
        if source_existing["canonical_smiles"] != rec.smiles:
            raise ValueError("source record changed canonical_smiles")
        return int(source_existing.get("cid") or source_existing.get("duplicate_of_cid") or 0)
    existing = storage.find_molecule_by_smiles(conn, rec.smiles)
    if existing:
        return existing
    mol = Chem.MolFromSmiles(rec.smiles)
    if mol is None:
        return -1
    ikey = inchi.MolToInchiKey(mol)
    dup_by_inchikey = storage.find_molecule_by_inchikey(conn, ikey)
    if dup_by_inchikey:
        return dup_by_inchikey
    return None


def sync_source(conn, source_name: str) -> int:
    source_cfg = config.APPROVED_SOURCES[source_name]
    state = storage.get_ingestion_source(conn, source_name) or {}
    legacy_state = storage.load_state(config.STATE_PATH)
    start_cursor = int(
        state.get("next_cursor")
        or legacy_state.get("next_cid")
        or source_cfg.get("start_cursor", 1)
    )
    batch_size = int(source_cfg.get("batch_size", config.PUBCHEM_BATCH_SIZE))
    batch = ingest.fetch_batch(source_name, start_cursor, batch_size)
    run_id = storage.begin_ingestion_run(
        conn, source_name, start_cursor=start_cursor, requested=batch.requested
    )
    accepted = duplicates = invalid = 0
    error: str | None = None
    for rec in batch.records:
        if not _running:
            break
        storage.record_raw_snapshot(
            conn,
            run_id=run_id,
            source_name=source_name,
            source_record_id=rec.source_record_id,
            canonical_smiles=rec.smiles,
            payload_json=rec.raw_payload,
        )
        try:
            dup_cid = _precompute_duplicate(conn, rec)
        except ValueError as exc:
            invalid += 1
            error = str(exc)
            continue
        if dup_cid == -1:
            invalid += 1
            continue
        if dup_cid:
            storage.record_source_mapping(
                conn,
                source_name=rec.source_name,
                source_record_id=rec.source_record_id or str(rec.cid),
                canonical_smiles=rec.smiles,
                source_license=rec.source_license,
                metadata_json=rec.metadata,
                provenance_json=rec.provenance,
                raw_smiles=rec.raw_smiles,
                ingested_at=rec.ingested_at,
                cid=dup_cid,
                is_duplicate=True,
                duplicate_of_cid=dup_cid,
            )
            duplicates += 1
            continue
        mol = Chem.MolFromSmiles(rec.smiles)
        if mol is None or mol.GetNumHeavyAtoms() > config.MAX_HEAVY_ATOMS:
            invalid += 1
            continue
        log.info("compute %s:%s %s", rec.source_name, rec.source_record_id, rec.smiles)
        result = compute.compute_molecule(
            cid=rec.cid,
            smiles=rec.smiles,
            basis=config.BASIS_SET,
            use_vqe_up_to_qubits=config.USE_VQE_UP_TO_QUBITS,
            max_seconds=config.MAX_CPU_SECONDS_PER_MOL,
            mw=rec.mw,
        )
        row = _merge_result(rec, result)
        storage.upsert(conn, row)
        storage.record_source_mapping(
            conn,
            source_name=rec.source_name,
            source_record_id=rec.source_record_id or str(rec.cid),
            canonical_smiles=rec.smiles,
            source_license=rec.source_license,
            metadata_json=rec.metadata,
            provenance_json=rec.provenance,
            raw_smiles=rec.raw_smiles,
            ingested_at=rec.ingested_at,
            cid=rec.cid,
        )
        if result.success:
            accepted += 1
            log.info(
                "  -> %s E=%.6f Ha qubits=%s t=%.1fs",
                result.method,
                result.energy_hartree or 0.0,
                result.num_qubits,
                result.runtime_seconds,
            )
        else:
            invalid += 1
            log.warning("  -> FAILED: %s", result.error)
    storage.finish_ingestion_run(
        conn,
        run_id=run_id,
        source_name=source_name,
        next_cursor=batch.next_cursor,
        fetched=batch.requested,
        accepted=accepted,
        duplicates=duplicates,
        invalid=invalid,
        error=error,
    )
    storage.save_state(config.STATE_PATH, {"next_cid": batch.next_cursor})
    return accepted


def run() -> None:
    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    conn = storage.connect(config.DB_PATH)
    storage.ensure_ingestion_sources(conn, config.APPROVED_SOURCES)
    legacy_state = storage.load_state(config.STATE_PATH)
    if legacy_state.get("next_cid"):
        storage.set_source_cursor_if_empty(conn, "pubchem", legacy_state["next_cid"])

    processed_since_publish = 0
    last_publish_time = datetime.now(timezone.utc)

    while _running:
        due_sources = storage.list_due_ingestion_sources(conn, config.ACTIVE_INGEST_SOURCES)
        if not due_sources:
            time.sleep(config.INGEST_POLL_SECONDS)
            continue
        for source in due_sources:
            if not _running:
                break
            processed_since_publish += sync_source(conn, source["source_name"])
            now = datetime.now(timezone.utc)
            hours_since = (now - last_publish_time).total_seconds() / 3600
            if (
                processed_since_publish >= config.PUBLISH_EVERY_N_MOLECULES
                or hours_since >= config.SNAPSHOT_EVERY_HOURS
            ):
                publish_snapshot(conn)
                processed_since_publish = 0
                last_publish_time = now

    publish_snapshot(conn)
    conn.close()
    log.info("Worker stopped cleanly.")


def publish_snapshot(conn) -> None:
    n = storage.export_parquet(conn, config.PARQUET_PATH)
    log.info("Exported %s rows -> %s", n, config.PARQUET_PATH.name)

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

    try:
        from src import metrics as _metrics
        snap = _metrics.snapshot(stats.get("row_count", 0))
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
