"""Tests for 3D shape descriptors module + /shape3d endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import (shape3d, scopes, keys as keysdb, ratelimit,
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

def test_aspirin_shape_ranges():
    r = shape3d.compute_one("CC(=O)Oc1ccccc1C(=O)O")
    assert r.success
    # NPR axes: 0 <= NPR1 <= NPR2 <= 1, and NPR1+NPR2 >= 1 (moment triangle)
    assert 0.0 <= r.npr1 <= r.npr2 <= 1.0001
    assert r.npr1 + r.npr2 >= 0.99
    assert r.radius_of_gyration > 0


def test_rod_is_rod():
    r = shape3d.compute_one("C#CC#CC#C")     # linear -> NPR1~0, NPR2~1
    assert r.success
    assert r.npr1 < 0.1
    assert r.npr2 > 0.9


def test_sphere_is_round():
    r = shape3d.compute_one("C1C2CC3CC1CC(C2)C3")  # adamantane
    assert r.success
    assert r.npr1 > 0.8 and r.npr2 > 0.8


def test_invalid_raises():
    with pytest.raises(ValueError):
        shape3d.compute_one("not-a-smiles")


# ---------- endpoint ----------

def test_shape_requires_key():
    client = TestClient(api.app)
    r = client.post("/shape3d", json={"smiles": ["CCO"]})
    assert r.status_code == 401


def test_shape_happy_path_charges_5x():
    info = keysdb.provision("sh@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/shape3d", json={"smiles": ["CCO", "c1ccccc1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 10         # 2 molecules * 5
    assert all(res["success"] for res in body["results"])

    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 10


def test_shape_bad_smiles_400():
    info = keysdb.provision("sh2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/shape3d", json={"smiles": ["bad-smiles"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


def test_shape_scope_enforced():
    info = keysdb.provision("sh3@u.com", "research")
    scopes.set_scopes(info.key, ["compute"])     # no shape3d scope
    client = TestClient(api.app)
    r = client.post("/shape3d", json={"smiles": ["CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    scopes.set_scopes(info.key, ["shape3d"])
    r2 = client.post("/shape3d", json={"smiles": ["CCO"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
