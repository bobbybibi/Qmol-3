"""Tests for Butina clustering module + /cluster endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import (clustering, scopes, keys as keysdb, ratelimit,
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

def test_identical_molecules_one_cluster():
    r = clustering.cluster(["CCO", "CCO", "CCO"], cutoff=0.3)
    assert r.n_clusters == 1
    assert r.clusters[0]["size"] == 3
    assert r.clusters[0]["centroid"] == "CCO"


def test_distinct_molecules_separate_clusters():
    r = clustering.cluster(["CCO", "c1ccccc1"], cutoff=0.3)
    assert r.n_clusters == 2


def test_centroid_is_a_member():
    r = clustering.cluster(["CCO", "CCCO", "c1ccccc1"], cutoff=0.5)
    for c in r.clusters:
        assert c["centroid"] in c["member_smiles"]
        assert c["size"] == len(c["members"])


def test_cutoff_one_merges_everything():
    r = clustering.cluster(["CCO", "c1ccccc1", "CC(=O)O"], cutoff=1.0)
    assert r.n_clusters == 1
    assert r.clusters[0]["size"] == 3


def test_invalid_tracked_not_fatal():
    r = clustering.cluster(["CCO", "bad-smiles", "CCO"], cutoff=0.3)
    assert r.invalid == [1]
    assert r.n_valid == 2


def test_all_invalid_raises():
    with pytest.raises(ValueError):
        clustering.cluster(["nope", "bad"])


# ---------- endpoint ----------

def test_cluster_requires_key():
    client = TestClient(api.app)
    r = client.post("/cluster", json={"smiles": ["CCO", "CCN"]})
    assert r.status_code == 401


def test_cluster_happy_path_charges_per_molecule():
    info = keysdb.provision("cl@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/cluster",
                    json={"smiles": ["CCO", "CCO", "c1ccccc1"], "cutoff": 0.3},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 3
    assert body["n_valid"] == 3
    assert body["cutoff"] == 0.3
    # CCO x2 should land together, benzene apart
    assert body["n_clusters"] == 2
    sizes = sorted(c["size"] for c in body["clusters"])
    assert sizes == [1, 2]

    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 3


def test_cluster_bad_input_400():
    info = keysdb.provision("cl2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/cluster", json={"smiles": ["nope", "also-bad"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


def test_cluster_scope_enforced():
    info = keysdb.provision("cl3@u.com", "research")
    scopes.set_scopes(info.key, ["compute"])     # no cluster scope
    client = TestClient(api.app)
    r = client.post("/cluster", json={"smiles": ["CCO", "CCN"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    scopes.set_scopes(info.key, ["cluster"])
    r2 = client.post("/cluster", json={"smiles": ["CCO", "CCN"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
