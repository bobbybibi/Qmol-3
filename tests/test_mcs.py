"""Tests for the MCS module + /mcs endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import (mcs, scopes, keys as keysdb, ratelimit,
                 audit, cache as result_cache)


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(api, "API_KEYS", set())
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(audit, "LOG_FILE", tmp_path / "logs" / "api.jsonl")
    result_cache.COMPUTE_CACHE.clear()
    yield


# ---------- library ----------

def test_shared_ring_found():
    r = mcs.find(["c1ccccc1C(=O)O", "c1ccccc1C(=O)N", "c1ccccc1CC(=O)O"])
    assert r.n_valid == 3
    assert r.smarts                       # non-empty SMARTS
    assert r.num_atoms >= 6               # at least the shared benzene ring
    assert r.completed is True


def test_identical_molecules_full_overlap():
    r = mcs.find(["c1ccccc1", "c1ccccc1"])
    assert r.num_atoms == 6
    assert r.smiles is not None


def test_invalid_tracked():
    r = mcs.find(["c1ccccc1", "bad-smiles", "c1ccccc1C"])
    assert r.invalid == [1]
    assert r.n_valid == 2


def test_needs_two_valid():
    with pytest.raises(ValueError):
        mcs.find(["c1ccccc1", "bad-smiles"])


# ---------- endpoint ----------

def test_mcs_requires_key():
    client = TestClient(api.app)
    r = client.post("/mcs", json={"smiles": ["c1ccccc1", "c1ccccc1C"]})
    assert r.status_code == 401


def test_mcs_happy_path_charges_per_molecule():
    info = keysdb.provision("x@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/mcs",
                    json={"smiles": ["c1ccccc1C(=O)O", "c1ccccc1C(=O)N"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 2
    assert body["num_atoms"] >= 6
    assert body["smarts"]

    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 2


def test_mcs_requires_two_smiles():
    info = keysdb.provision("x2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/mcs", json={"smiles": ["c1ccccc1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 422            # pydantic min_length=2


def test_mcs_all_invalid_400():
    info = keysdb.provision("x3@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/mcs", json={"smiles": ["nope", "bad"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


def test_mcs_scope_enforced():
    info = keysdb.provision("x4@u.com", "research")
    scopes.set_scopes(info.key, ["compute"])     # no mcs scope
    client = TestClient(api.app)
    r = client.post("/mcs", json={"smiles": ["c1ccccc1", "c1ccccc1C"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    scopes.set_scopes(info.key, ["mcs"])
    r2 = client.post("/mcs", json={"smiles": ["c1ccccc1", "c1ccccc1C"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
