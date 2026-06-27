"""Tests for stereoisomer enumeration module + /stereoisomers endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import (stereoisomers as st, scopes, keys as keysdb, ratelimit,
                 audit, cache as result_cache)

# two undefined stereocenters -> 4 isomers
TWO_CENTERS = "CC(O)C(N)C(=O)O"


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

def test_two_centers_four_isomers():
    r = st.enumerate_one(TWO_CENTERS)
    assert r.n_isomers == 4
    assert not r.truncated
    assert len(set(r.isomers)) == 4


def test_no_stereocenters_one_isomer():
    r = st.enumerate_one("CCO")
    assert r.n_isomers == 1


def test_max_isomers_truncates():
    r = st.enumerate_one(TWO_CENTERS, max_isomers=2)
    assert r.n_isomers == 2
    assert r.truncated is True


def test_invalid_raises():
    with pytest.raises(ValueError):
        st.enumerate_one("not-a-smiles")


# ---------- endpoint ----------

def test_stereo_requires_key():
    client = TestClient(api.app)
    r = client.post("/stereoisomers", json={"smiles": [TWO_CENTERS]})
    assert r.status_code == 401


def test_stereo_happy_path_charges_double():
    info = keysdb.provision("st@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/stereoisomers", json={"smiles": [TWO_CENTERS, "CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 4          # 2 molecules * 2
    assert body["results"][0]["n_isomers"] == 4
    assert body["results"][1]["n_isomers"] == 1

    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 4


def test_stereo_bad_smiles_400():
    info = keysdb.provision("st2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/stereoisomers", json={"smiles": ["bad-smiles"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


def test_stereo_scope_enforced():
    info = keysdb.provision("st3@u.com", "research")
    scopes.set_scopes(info.key, ["compute"])     # no stereoisomers scope
    client = TestClient(api.app)
    r = client.post("/stereoisomers", json={"smiles": ["CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    scopes.set_scopes(info.key, ["stereoisomers"])
    r2 = client.post("/stereoisomers", json={"smiles": ["CCO"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
