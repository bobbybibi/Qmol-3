"""Tests for API-key DB, usage tracking, SDF/JSONL exports."""
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from src import keys as keysdb
from src import compute, storage, exports


@pytest.fixture
def keys_db(tmp_path, monkeypatch):
    db = tmp_path / "k.sqlite"
    monkeypatch.setattr(keysdb, "DEFAULT_DB", db)
    return db


def test_provision_and_lookup(keys_db):
    info = keysdb.provision("buyer@x.com", "commercial")
    assert info.key.startswith("qmol_")
    assert info.tier == "commercial"
    assert info.monthly_quota == 100_000
    again = keysdb.provision("buyer@x.com", "commercial")
    assert again.key == info.key  # idempotent

    looked = keysdb.lookup(info.key)
    assert looked is not None
    assert looked.email == "buyer@x.com"


def test_usage_tracking(keys_db):
    info = keysdb.provision("u@x.com", "research")
    assert keysdb.month_usage(info.key) == 0
    keysdb.record(info.key, "/compute/premium", 100)
    keysdb.record(info.key, "/compute/premium", 250)
    assert keysdb.month_usage(info.key) == 350


def test_deactivate(keys_db):
    info = keysdb.provision("d@x.com", "research")
    keysdb.deactivate(info.key)
    assert not keysdb.lookup(info.key).active


def test_api_premium_uses_db_key(tmp_path, monkeypatch):
    db = tmp_path / "k.sqlite"
    monkeypatch.setattr(keysdb, "DEFAULT_DB", db)
    monkeypatch.setattr(api, "API_KEYS", set())  # disable env keys
    info = keysdb.provision("api-user@x.com", "research")

    client = TestClient(api.app)
    r = client.post(
        "/compute/premium",
        json={"smiles": ["CCO"]},
        headers={"x-api-key": info.key},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["quota"]["used_this_month"] == 1
    assert body["quota"]["tier"] == "research"


def test_api_quota_exceeded(tmp_path, monkeypatch):
    db = tmp_path / "k.sqlite"
    monkeypatch.setattr(keysdb, "DEFAULT_DB", db)
    monkeypatch.setattr(api, "API_KEYS", set())
    info = keysdb.provision("q@x.com", "free")  # quota = 500

    client = TestClient(api.app)
    # pretend they've already used 499
    keysdb.record(info.key, "/compute/premium", 499)
    r = client.post(
        "/compute/premium",
        json={"smiles": ["CCO", "c1ccccc1"]},
        headers={"x-api-key": info.key},
    )
    assert r.status_code == 402


def test_api_usage_endpoint(tmp_path, monkeypatch):
    db = tmp_path / "k.sqlite"
    monkeypatch.setattr(keysdb, "DEFAULT_DB", db)
    info = keysdb.provision("usage@x.com", "commercial")

    client = TestClient(api.app)
    r = client.get("/usage", headers={"x-api-key": info.key})
    assert r.status_code == 200
    assert r.json()["tier"] == "commercial"
    assert r.json()["monthly_quota"] == 100_000


def test_health():
    client = TestClient(api.app)
    assert client.get("/health").json() == {"status": "ok"}


def test_sdf_and_jsonl_export(tmp_path):
    conn = storage.connect(tmp_path / "t.sqlite")
    for i, smi in enumerate(["CCO", "c1ccccc1", "CC(=O)O"]):
        r = compute.compute_molecule(cid=1000 + i, smiles=smi)
        storage.upsert(conn, r.to_dict())

    sdf = tmp_path / "out.sdf"
    n = exports.export_sdf(conn, sdf)
    assert n == 3
    assert "$$$$" in sdf.read_text()

    jsonl = tmp_path / "out.jsonl"
    n2 = exports.export_jsonl(conn, jsonl)
    assert n2 == 3
    lines = jsonl.read_text().strip().splitlines()
    assert len(lines) == 3
    import json
    rec = json.loads(lines[0])
    assert "smiles" in rec and "mw" in rec
