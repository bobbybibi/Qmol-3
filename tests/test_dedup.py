"""Tests for the dedup module + /dedup endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import (dedup, scopes, keys as keysdb, ratelimit,
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

def test_collapses_equivalent_spellings():
    # CCO == OCC (ethanol); two benzene spellings collapse too
    r = dedup.dedup(["CCO", "OCC", "c1ccccc1", "C1=CC=CC=C1", "CCO"])
    assert r.n_input == 5
    assert r.n_unique == 2
    assert r.n_duplicates == 3
    eth = next(g for g in r.groups if g["canonical_smiles"] == "CCO")
    assert eth["count"] == 3
    assert eth["input_indices"] == [0, 1, 4]
    assert eth["inchikey"]


def test_invalid_tracked():
    r = dedup.dedup(["CCO", "bad-smiles", "CCN"])
    assert r.invalid == [1]
    assert r.n_unique == 2


def test_all_unique():
    r = dedup.dedup(["CCO", "CCN", "CCC"])
    assert r.n_unique == 3
    assert r.n_duplicates == 0


# ---------- endpoint ----------

def test_dedup_requires_key():
    client = TestClient(api.app)
    r = client.post("/dedup", json={"smiles": ["CCO"]})
    assert r.status_code == 401


def test_dedup_happy_path_charges_per_input():
    info = keysdb.provision("dd@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/dedup", json={"smiles": ["CCO", "OCC", "c1ccccc1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 3          # charged per input, not per unique
    assert body["n_unique"] == 2

    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 3


def test_dedup_scope_enforced():
    info = keysdb.provision("dd2@u.com", "research")
    scopes.set_scopes(info.key, ["compute"])     # no dedup scope
    client = TestClient(api.app)
    r = client.post("/dedup", json={"smiles": ["CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    scopes.set_scopes(info.key, ["dedup"])
    r2 = client.post("/dedup", json={"smiles": ["CCO"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
