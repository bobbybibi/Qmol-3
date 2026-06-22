"""Tests for the pairwise similarity matrix module + /similarity/matrix endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import (simmatrix, scopes, keys as keysdb, ratelimit,
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

def test_matrix_shape_and_diagonal():
    r = simmatrix.compute(["CCO", "c1ccccc1", "CC(=O)O"])
    assert r.n == 3
    assert len(r.matrix) == 3 and all(len(row) == 3 for row in r.matrix)
    assert all(r.matrix[i][i] == 1.0 for i in range(3))


def test_matrix_symmetric():
    r = simmatrix.compute(["CCO", "CCN", "c1ccccc1"])
    assert all(r.matrix[i][j] == r.matrix[j][i]
               for i in range(r.n) for j in range(r.n))


def test_identical_molecules_similarity_one():
    r = simmatrix.compute(["CCO", "CCO"])
    assert r.matrix[0][1] == 1.0
    assert r.nearest[0]["nearest_j"] == 1
    assert r.nearest[0]["similarity"] == 1.0


def test_dissimilar_molecules_low_similarity():
    r = simmatrix.compute(["CCO", "c1ccccc1"])
    assert r.matrix[0][1] < 0.3


def test_invalid_smiles_tracked_not_fatal():
    r = simmatrix.compute(["CCO", "bad-smiles", "CCN"])
    assert r.invalid == [1]          # index in the *input*
    assert r.n == 2                  # only the two valid ones
    assert r.smiles == ["CCO", "CCN"]


def test_all_invalid_raises():
    with pytest.raises(ValueError):
        simmatrix.compute(["nope", "also-bad"])


# ---------- endpoint ----------

def test_matrix_requires_key():
    client = TestClient(api.app)
    r = client.post("/similarity/matrix", json={"smiles": ["CCO", "CCN"]})
    assert r.status_code == 401


def test_matrix_happy_path_charges_per_molecule():
    info = keysdb.provision("m@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/similarity/matrix",
                    json={"smiles": ["CCO", "CCN", "c1ccccc1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n"] == 3
    assert body["quota_charged"] == 3
    assert body["matrix"][0][0] == 1.0
    assert len(body["nearest"]) == 3

    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 3


def test_matrix_requires_at_least_two():
    info = keysdb.provision("m2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/similarity/matrix", json={"smiles": ["CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 422   # pydantic min_length=2


def test_matrix_uses_similarity_scope():
    info = keysdb.provision("m3@u.com", "research")
    scopes.set_scopes(info.key, ["compute"])      # no similarity scope
    client = TestClient(api.app)
    r = client.post("/similarity/matrix", json={"smiles": ["CCO", "CCN"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    scopes.set_scopes(info.key, ["similarity"])
    r2 = client.post("/similarity/matrix", json={"smiles": ["CCO", "CCN"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
