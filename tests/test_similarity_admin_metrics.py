"""Tests for similarity search, admin endpoints, metrics snapshot."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
import config
from src import compute, storage, keys as keysdb, metrics, similarity, ratelimit


@pytest.fixture(autouse=True)
def _reset():
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def populated_db(tmp_path, monkeypatch):
    db = tmp_path / "mols.sqlite"
    parquet = tmp_path / "mols.parquet"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(config, "PARQUET_PATH", parquet)
    conn = storage.connect(db)
    for i, smi in enumerate(["CCO", "CCCCO", "CCN", "c1ccccc1", "c1ccncc1"]):
        r = compute.compute_molecule(cid=i + 1, smiles=smi)
        storage.upsert(conn, r.to_dict())
    conn.commit()
    conn.close()
    yield db


@pytest.fixture
def isolated_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(metrics, "DEFAULT_DB", tmp_path / "m.sqlite")
    monkeypatch.setattr(api, "API_KEYS", set())


# ---------- similarity ----------

def test_similarity_search_finds_self(populated_db):
    conn = storage.connect(populated_db)
    hits = similarity.search(conn, "CCO", top_k=3, min_similarity=0.0)
    conn.close()
    assert len(hits) >= 1
    assert hits[0].similarity == pytest.approx(1.0, abs=0.01)
    assert hits[0].smiles == "CCO"


def test_similarity_rejects_bad_smiles(populated_db):
    conn = storage.connect(populated_db)
    with pytest.raises(ValueError):
        similarity.search(conn, "not-a-smiles", top_k=5)
    conn.close()


def test_similarity_endpoint_charges_quota(populated_db, isolated_keys):
    info = keysdb.provision("sim@u.com", "research")
    client = TestClient(api.app)
    r = client.post(
        "/similarity",
        json={"smiles": "CCO", "top_k": 3, "min_similarity": 0.0},
        headers={"x-api-key": info.key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 100
    assert any(h["smiles"] == "CCO" for h in body["hits"])
    assert keysdb.month_usage(info.key) == 100


def test_similarity_endpoint_requires_key(populated_db, isolated_keys):
    client = TestClient(api.app)
    r = client.post("/similarity", json={"smiles": "CCO"})
    assert r.status_code == 401


# ---------- admin endpoints ----------

def test_admin_requires_token(isolated_keys, monkeypatch):
    monkeypatch.setattr(api, "ADMIN_TOKEN", "secret123")
    client = TestClient(api.app)
    r = client.get("/admin/stats")
    assert r.status_code == 401
    r2 = client.get("/admin/stats", headers={"x-admin-token": "wrong"})
    assert r2.status_code == 401


def test_admin_stats_works(populated_db, isolated_keys, monkeypatch):
    monkeypatch.setattr(api, "ADMIN_TOKEN", "secret123")
    keysdb.provision("paid@u.com", "commercial")
    client = TestClient(api.app)
    r = client.get("/admin/stats", headers={"x-admin-token": "secret123"})
    assert r.status_code == 200
    body = r.json()
    assert body["active_keys"] >= 1
    assert body["paid_keys"] >= 1
    assert body["est_revenue"] >= 299


def test_admin_top_users(populated_db, isolated_keys, monkeypatch):
    monkeypatch.setattr(api, "ADMIN_TOKEN", "t")
    info = keysdb.provision("heavy@u.com", "research")
    keysdb.record(info.key, "/compute/premium", 1234)
    client = TestClient(api.app)
    r = client.get("/admin/top-users", headers={"x-admin-token": "t"})
    assert r.status_code == 200
    users = r.json()["users"]
    assert users[0]["email"] == "heavy@u.com"
    assert users[0]["smiles_count"] == 1234


# ---------- metrics ----------

def test_metrics_snapshot_roundtrip(isolated_keys):
    keysdb.provision("m@u.com", "research")
    snap = metrics.snapshot(molecule_count=42)
    assert snap["molecules"] == 42
    assert snap["active_keys"] >= 1
    hist = metrics.history(limit=5)
    assert len(hist) == 1
    assert hist[0]["molecules"] == 42


def test_metrics_snapshot_upserts_same_day(isolated_keys):
    metrics.snapshot(molecule_count=10)
    metrics.snapshot(molecule_count=20)  # same day overwrites
    hist = metrics.history()
    assert len(hist) == 1
    assert hist[0]["molecules"] == 20
