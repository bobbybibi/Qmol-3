"""Tests for the molecular formula module + /formula endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import (formula, scopes, keys as keysdb, ratelimit,
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

def test_aspirin_formula_and_masses():
    f = formula.compute_one("CC(=O)Oc1ccccc1C(=O)O")
    assert f.formula == "C9H8O4"
    assert abs(f.exact_mass - 180.0423) < 0.001
    assert abs(f.average_mass - 180.159) < 0.01
    assert f.composition == {"C": 9, "H": 8, "O": 4}
    assert f.rdbe == 6.0           # benzene (4) + 2 carbonyls
    assert f.num_rings == 1
    assert f.heavy_atoms == 13


def test_water():
    f = formula.compute_one("O")
    assert f.formula == "H2O"
    assert f.rdbe == 0.0
    assert f.composition == {"H": 2, "O": 1}


def test_benzene_rdbe():
    f = formula.compute_one("c1ccccc1")
    assert f.formula == "C6H6"
    assert f.rdbe == 4.0           # ring + 3 double bonds


def test_halogen_in_rdbe():
    # chlorobenzene C6H5Cl -> RDBE still 4
    f = formula.compute_one("Clc1ccccc1")
    assert f.composition.get("Cl") == 1
    assert f.rdbe == 4.0


def test_invalid_raises():
    with pytest.raises(ValueError):
        formula.compute_one("not-a-smiles")


# ---------- endpoint ----------

def test_formula_requires_key():
    client = TestClient(api.app)
    r = client.post("/formula", json={"smiles": ["CCO"]})
    assert r.status_code == 401


def test_formula_happy_path_charges_per_molecule():
    info = keysdb.provision("f@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/formula", json={"smiles": ["CCO", "O", "c1ccccc1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 3
    assert len(body["results"]) == 3
    assert body["results"][0]["formula"] == "C2H6O"

    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 3


def test_formula_bad_smiles_400():
    info = keysdb.provision("f2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/formula", json={"smiles": ["bad-smiles"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


def test_formula_scope_enforced():
    info = keysdb.provision("f3@u.com", "research")
    scopes.set_scopes(info.key, ["compute"])    # no formula scope
    client = TestClient(api.app)
    r = client.post("/formula", json={"smiles": ["CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    scopes.set_scopes(info.key, ["formula"])
    r2 = client.post("/formula", json={"smiles": ["CCO"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
