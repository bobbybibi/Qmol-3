from __future__ import annotations

from fastapi.testclient import TestClient

import api
import config
from src import compute, ingest, storage


def test_fetch_batch_normalizes_pubchem(monkeypatch):
    def fake_get(_url, **_kw):
        class R:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"PropertyTable": {"Properties": [{
                    "CID": 7,
                    "ConnectivitySMILES": "OCC",
                    "IUPACName": "ethanol",
                    "MolecularFormula": "C2H6O",
                    "MolecularWeight": "46.07",
                }]}}

        return R()

    monkeypatch.setattr(ingest.requests, "get", fake_get)
    batch = ingest.fetch_batch("pubchem", start_cursor=7, batch_size=1)
    assert batch.next_cursor == 8
    assert len(batch.records) == 1
    rec = batch.records[0]
    assert rec.smiles == "CCO"
    assert rec.source_name == "pubchem"
    assert rec.source_license == config.APPROVED_SOURCES["pubchem"]["license"]
    assert rec.provenance[-1]["step"] == "normalize"


def test_storage_persists_ingestion_metadata(tmp_path):
    conn = storage.connect(tmp_path / "m.sqlite")
    storage.ensure_ingestion_sources(conn, config.APPROVED_SOURCES)
    run_id = storage.begin_ingestion_run(conn, "pubchem", start_cursor=1, requested=2)
    result = compute.compute_molecule(cid=702, smiles="CCO")
    row = result.to_dict() | {
        "source_name": "pubchem",
        "source_record_id": "702",
        "source_license": "CC0-1.0",
        "raw_smiles": "OCC",
        "source_metadata": {"approved_for_sale": True},
        "provenance_json": [{"step": "normalize"}],
        "ingested_at": "2026-01-01T00:00:00+00:00",
    }
    storage.upsert(conn, row)
    storage.record_source_mapping(
        conn,
        source_name="pubchem",
        source_record_id="702",
        canonical_smiles="CCO",
        source_license="CC0-1.0",
        metadata_json={"approved_for_sale": True},
        provenance_json=[{"step": "normalize"}],
        raw_smiles="OCC",
        ingested_at="2026-01-01T00:00:00+00:00",
        cid=702,
    )
    storage.record_raw_snapshot(
        conn,
        run_id=run_id,
        source_name="pubchem",
        source_record_id="702",
        canonical_smiles="CCO",
        payload_json={"cid": 702},
    )
    storage.finish_ingestion_run(
        conn,
        run_id=run_id,
        source_name="pubchem",
        next_cursor=3,
        fetched=2,
        accepted=1,
        duplicates=0,
        invalid=1,
    )
    rows = storage.list_molecules(conn, source_name="pubchem", limit=10)
    assert rows[0]["source_metadata"]["approved_for_sale"] is True
    assert rows[0]["provenance_json"][0]["step"] == "normalize"
    raw = storage.list_raw_snapshots(conn, source_name="pubchem", limit=10)
    assert raw[0]["source_record_id"] == "702"
    status = storage.get_ingestion_source(conn, "pubchem")
    assert status["next_cursor"] == "3"
    conn.close()


def test_admin_ingestion_endpoints(tmp_path, monkeypatch):
    db = tmp_path / "qmol.sqlite"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(api.config, "DB_PATH", db)
    monkeypatch.setattr(api, "ADMIN_TOKEN", "test-admin")
    conn = storage.connect(db)
    storage.ensure_ingestion_sources(conn, config.APPROVED_SOURCES)
    run_id = storage.begin_ingestion_run(conn, "pubchem", start_cursor=100, requested=1)
    result = compute.compute_molecule(cid=100, smiles="CCO")
    storage.upsert(conn, result.to_dict() | {
        "source_name": "pubchem",
        "source_record_id": "100",
        "source_license": "CC0-1.0",
        "raw_smiles": "CCO",
        "source_metadata": {"approved_for_sale": True},
        "provenance_json": [{"step": "normalize"}],
        "ingested_at": "2026-01-01T00:00:00+00:00",
    })
    storage.record_raw_snapshot(
        conn,
        run_id=run_id,
        source_name="pubchem",
        source_record_id="100",
        canonical_smiles="CCO",
        payload_json={"cid": 100},
    )
    storage.finish_ingestion_run(
        conn,
        run_id=run_id,
        source_name="pubchem",
        next_cursor=101,
        fetched=1,
        accepted=1,
        duplicates=0,
        invalid=0,
    )
    conn.close()

    client = TestClient(api.app)
    headers = {"x-admin-token": "test-admin"}

    r = client.get("/admin/ingestion/sources", headers=headers)
    assert r.status_code == 200
    assert any(s["source_name"] == "pubchem" for s in r.json()["sources"])

    r = client.get("/admin/ingestion/status", headers=headers)
    assert r.status_code == 200
    assert r.json()["public_rows"] >= 1

    r = client.get("/admin/ingestion/molecules?source_name=pubchem", headers=headers)
    assert r.status_code == 200
    assert r.json()["molecules"][0]["source_record_id"] == "100"

    r = client.get("/admin/ingestion/raw", headers=headers)
    assert r.status_code == 200
    assert r.json()["snapshots"][0]["source_name"] == "pubchem"

    r = client.get("/admin/ingestion/export.csv?source_name=pubchem", headers=headers)
    assert r.status_code == 200
    assert "source_record_id" in r.text
