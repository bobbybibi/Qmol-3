"""Tests for tautomer enumeration module + /tautomers endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import (tautomers, scopes, keys as keysdb, ratelimit,
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

def test_keto_enol_enumerated():
    r = tautomers.enumerate_one("O=C1CCCCC1")   # cyclohexanone
    assert r.n_tautomers >= 2
    assert "O=C1CCCCC1" in r.tautomers          # keto form present
    assert any("=C" in t and "O" in t for t in r.tautomers)  # an enol form
    assert r.canonical                          # non-empty canonical


def test_forms_are_unique():
    r = tautomers.enumerate_one("O=C1CCCCC1")
    assert len(r.tautomers) == len(set(r.tautomers))


def test_max_tautomers_caps():
    r = tautomers.enumerate_one("O=C1CCCCC1", max_tautomers=1)
    assert r.n_tautomers == 1


def test_invalid_smiles_raises():
    with pytest.raises(ValueError):
        tautomers.enumerate_one("not-a-smiles")


# ---------- endpoint ----------

def test_tautomers_requires_key():
    client = TestClient(api.app)
    r = client.post("/tautomers", json={"smiles": ["O=C1CCCCC1"]})
    assert r.status_code == 401


def test_tautomers_happy_path_charges_double():
    info = keysdb.provision("t@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/tautomers",
                    json={"smiles": ["O=C1CCCCC1", "CC(=O)Oc1ccccc1C(=O)O"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 4          # 2 molecules * 2
    assert len(body["results"]) == 2
    assert body["results"][0]["n_tautomers"] >= 1

    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 4


def test_tautomers_invalid_smiles_400():
    info = keysdb.provision("t2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/tautomers", json={"smiles": ["bad-smiles"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


def test_tautomers_scope_enforced():
    info = keysdb.provision("t3@u.com", "research")
    scopes.set_scopes(info.key, ["compute"])   # no tautomers scope
    client = TestClient(api.app)
    r = client.post("/tautomers", json={"smiles": ["O=C1CCCCC1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    scopes.set_scopes(info.key, ["tautomers"])
    r2 = client.post("/tautomers", json={"smiles": ["O=C1CCCCC1"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
