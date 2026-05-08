"""Tests for file upload, substructure filter, exports, GitHub Actions CI."""
from __future__ import annotations
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from src import (uploads, substructure, exporters, keys as keysdb,
                 ratelimit, audit)


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(api, "API_KEYS", set())
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(audit, "LOG_FILE", tmp_path / "logs" / "api.jsonl")
    yield
    ratelimit.reset()


# ---------- upload parsers ----------

def test_upload_parse_smi():
    blob = b"CCO\nc1ccccc1 benzene\n# comment\nnot-a-mol\n\nCCN ethylamine"
    r = uploads.parse(blob, filename="mols.smi")
    assert r.format == "smi"
    assert r.smiles == ["CCO", "c1ccccc1", "CCN"]


def test_upload_parse_csv_with_header():
    blob = b"id,smiles,name\n1,CCO,ethanol\n2,c1ccccc1,benzene\n3,junk,bad\n"
    r = uploads.parse(blob, filename="mols.csv")
    assert r.format == "csv"
    assert r.smiles == ["CCO", "c1ccccc1"]


def test_upload_parse_csv_no_header():
    blob = b"CCO\nc1ccccc1\nCCN\n"
    r = uploads.parse(blob, filename="nohead.csv")
    assert r.smiles == ["CCO", "c1ccccc1", "CCN"]


def test_upload_parse_sdf_roundtrip():
    from rdkit import Chem
    from rdkit.Chem import AllChem
    mol = Chem.MolFromSmiles("CCO")
    mol = Chem.AddHs(mol)
    AllChem.EmbedMolecule(mol, randomSeed=1)
    sdf = Chem.MolToMolBlock(mol) + "\n$$$$\n"
    r = uploads.parse(sdf.encode(), filename="x.sdf")
    assert r.format == "sdf"
    assert len(r.smiles) == 1
    assert "O" in r.smiles[0]  # ethanol


def test_upload_endpoint_runs_compute():
    info = keysdb.provision("up@u.com", "research")
    client = TestClient(api.app)
    files = {"file": ("mols.smi", b"CCO\nc1ccccc1\n", "chemical/x-daylight-smiles")}
    r = client.post("/upload/compute", files=files,
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_parsed"] == 2
    assert body["quota_charged"] == 2
    assert len(body["results"]) == 2
    assert body["results"][0]["mw"] > 0
    assert keysdb.month_usage(info.key) == 2


def test_upload_endpoint_rejects_empty():
    info = keysdb.provision("up2@u.com", "research")
    client = TestClient(api.app)
    files = {"file": ("empty.smi", b"# just a comment\n", "text/plain")}
    r = client.post("/upload/compute", files=files,
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


def test_upload_endpoint_requires_auth():
    client = TestClient(api.app)
    files = {"file": ("x.smi", b"CCO\n", "text/plain")}
    r = client.post("/upload/compute", files=files)
    assert r.status_code == 401


# ---------- substructure ----------

def test_substructure_benzene():
    smis = ["CCO", "c1ccccc1", "c1ccccc1C", "CCN", "c1ccncc1"]
    hits = substructure.filter_smarts("c1ccccc1", smis)
    got = {h.smiles for h in hits}
    assert "c1ccccc1" in got
    assert "c1ccccc1C" in got
    assert "CCO" not in got


def test_substructure_sulfonamide():
    smis = ["CS(=O)(=O)N", "CCO", "c1ccc(S(=O)(=O)N)cc1", "CCN"]
    hits = substructure.filter_smarts("S(=O)(=O)N", smis)
    assert len(hits) == 2
    for h in hits:
        assert len(h.match_atoms) >= 4  # S + 2 O + N


def test_substructure_invalid_smarts():
    with pytest.raises(ValueError):
        substructure.filter_smarts("[[[broken", ["CCO"])


def test_substructure_endpoint():
    info = keysdb.provision("sub@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/substructure", json={
        "smarts": "c1ccccc1",
        "smiles": ["CCO", "c1ccccc1", "c1ccccc1C"],
    }, headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_input"] == 3
    assert body["n_hits"] == 2
    assert body["quota_charged"] == 3


def test_substructure_endpoint_bad_smarts_400():
    info = keysdb.provision("sub2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/substructure", json={
        "smarts": "[[broken", "smiles": ["CCO"],
    }, headers={"x-api-key": info.key})
    assert r.status_code == 400


# ---------- exporters ----------

def test_to_csv_roundtrip():
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y,z"}]
    out = exporters.to_csv(rows)
    assert "a,b" in out
    assert '"y,z"' in out  # quoting


def test_to_csv_column_order():
    rows = [{"a": 1, "b": 2, "c": 3}]
    out = exporters.to_csv(rows, columns=["c", "a"])
    first_line = out.splitlines()[0]
    assert first_line == "c,a"


def test_to_jsonl():
    rows = [{"a": 1}, {"a": 2}]
    out = exporters.to_jsonl(rows)
    lines = out.strip().splitlines()
    assert len(lines) == 2
    assert lines[0] == '{"a": 1}'


def test_audit_csv_endpoint():
    info = keysdb.provision("aud@u.com", "research")
    client = TestClient(api.app)
    client.get("/usage", headers={"x-api-key": info.key})
    client.get("/usage", headers={"x-api-key": info.key})
    r = client.get("/audit.csv", headers={"x-api-key": info.key})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "ts,method,path,status,ms,n_smiles" in r.text


def test_invoice_csv_endpoint():
    info = keysdb.provision("inv@u.com", "research")
    keysdb.record(info.key, "/compute", 5)
    client = TestClient(api.app)
    r = client.get("/invoice.csv", headers={"x-api-key": info.key})
    assert r.status_code == 200
    assert "endpoint,calls,smiles" in r.text
    assert "/compute" in r.text


# ---------- GitHub Actions ----------

def test_github_actions_workflow_present():
    root = Path(__file__).resolve().parents[1]
    wf = root / ".github" / "workflows" / "ci.yml"
    assert wf.exists()
    text = wf.read_text()
    assert "pytest" in text
    assert "docker build" in text
    assert "/health" in text
