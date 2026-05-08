"""Pytest suite. Run: pytest -q"""
from __future__ import annotations
import sqlite3
from pathlib import Path

import pytest

from src import compute, storage


def test_compute_ethanol():
    r = compute.compute_molecule(cid=702, smiles="CCO")
    assert r.success
    assert r.method.startswith("RDKit")
    assert 45 < r.mw < 47
    assert r.hbd == 1
    assert r.hba == 1
    assert r.lipinski_pass == 1
    assert r.inchikey and len(r.inchikey) == 27
    assert r.fsp3 == 1.0
    assert r.heteroatom_count == 1  # oxygen
    assert r.formal_charge == 0


def test_compute_invalid_smiles():
    r = compute.compute_molecule(cid=0, smiles="not-a-smiles")
    assert not r.success
    assert r.error


def test_compute_large_druglike():
    # aspirin
    r = compute.compute_molecule(cid=2244, smiles="CC(=O)Oc1ccccc1C(=O)O")
    assert r.success
    assert r.lipinski_pass == 1
    assert r.aromatic_rings == 1
    assert r.pains_hit in (0, 1)


def test_storage_roundtrip(tmp_path: Path):
    db = tmp_path / "t.sqlite"
    conn = storage.connect(db)
    r = compute.compute_molecule(cid=702, smiles="CCO")
    storage.upsert(conn, r.to_dict())
    assert storage.row_count(conn) == 1

    pq = tmp_path / "out.parquet"
    n = storage.export_parquet(conn, pq)
    assert n == 1 and pq.exists()

    csv = tmp_path / "out.csv"
    storage.export_csv(conn, csv)
    assert csv.exists()
    assert "inchikey" in csv.read_text().splitlines()[0]


def test_storage_upsert_replaces(tmp_path: Path):
    db = tmp_path / "t.sqlite"
    conn = storage.connect(db)
    r = compute.compute_molecule(cid=702, smiles="CCO")
    storage.upsert(conn, r.to_dict())
    storage.upsert(conn, r.to_dict())  # same CID again
    assert storage.row_count(conn) == 1


def test_ingest_smiles_key_robust(monkeypatch):
    """Ensure ingest handles both old CanonicalSMILES and new ConnectivitySMILES."""
    from src import ingest

    def fake_get(_url, **_kw):
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"PropertyTable": {"Properties": [{
                    "CID": 1, "ConnectivitySMILES": "CCO",
                    "MolecularFormula": "C2H6O", "MolecularWeight": "46.07"
                }]}}
        return R()

    monkeypatch.setattr(ingest.requests, "get", fake_get)
    rec = ingest.fetch_cid(1)
    assert rec is not None
    assert rec.smiles == "CCO"
