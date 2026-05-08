"""Tests for scopes, retro, plans, dashboard."""
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from src import (scopes, retro, plans, keys as keysdb, ratelimit,
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


# ---------- scopes lib ----------

def test_scopes_roundtrip():
    info = keysdb.provision("s@u.com", "research")
    assert scopes.get_scopes(info.key) is None     # unrestricted
    saved = scopes.set_scopes(info.key, ["compute", "usage"])
    assert saved == ["compute", "usage"]
    assert scopes.get_scopes(info.key) == ["compute", "usage"]
    scopes.clear_scopes(info.key)
    assert scopes.get_scopes(info.key) is None


def test_scopes_rejects_unknown():
    info = keysdb.provision("s2@u.com", "research")
    with pytest.raises(ValueError):
        scopes.set_scopes(info.key, ["not-a-real-scope"])


def test_path_to_scope():
    assert scopes.path_to_scope("/compute") == "compute"
    assert scopes.path_to_scope("/compute/premium") == "compute:premium"
    assert scopes.path_to_scope("/key/rotate") == "key:rotate"
    assert scopes.path_to_scope("/usage/history") == "usage"


def test_allowed_logic():
    info = keysdb.provision("a@u.com", "research")
    # unrestricted
    assert scopes.allowed(info.key, "/compute") is True
    # explicit
    scopes.set_scopes(info.key, ["compute"])
    assert scopes.allowed(info.key, "/compute") is True
    assert scopes.allowed(info.key, "/download/sdf") is False
    # wildcard
    scopes.set_scopes(info.key, ["*"])
    assert scopes.allowed(info.key, "/anything") is True
    # prefix (compute should match compute:premium)
    scopes.set_scopes(info.key, ["compute"])
    assert scopes.allowed(info.key, "/compute/premium") is True


def test_scope_middleware_blocks():
    info = keysdb.provision("b@u.com", "research")
    scopes.set_scopes(info.key, ["usage"])
    client = TestClient(api.app)
    r = client.get("/usage", headers={"x-api-key": info.key})
    assert r.status_code == 200
    r2 = client.post("/substructure", json={"smarts": "c1ccccc1",
                                            "smiles": ["CCO"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 403


def test_scope_endpoints():
    info = keysdb.provision("c@u.com", "research")
    client = TestClient(api.app)
    r = client.get("/key/scopes", headers={"x-api-key": info.key})
    assert r.status_code == 200
    assert r.json()["unrestricted"] is True
    r = client.put("/key/scopes", json={"scopes": ["compute", "usage"]},
                   headers={"x-api-key": info.key})
    assert r.status_code == 200
    assert set(r.json()["scopes"]) == {"compute", "usage"}
    r = client.delete("/key/scopes", headers={"x-api-key": info.key})
    assert r.status_code == 200
    assert r.json()["unrestricted"] is True


def test_scope_endpoint_bad_scope():
    info = keysdb.provision("d@u.com", "research")
    client = TestClient(api.app)
    r = client.put("/key/scopes", json={"scopes": ["nope"]},
                   headers={"x-api-key": info.key})
    assert r.status_code == 400


# ---------- retro ----------

def test_retro_amide_disconnection():
    # phenylacetamide
    steps = retro.one_step("CC(=O)Nc1ccccc1")
    names = {s.name for s in steps}
    assert "amide_coupling" in names


def test_retro_invalid_smiles():
    with pytest.raises(ValueError):
        retro.one_step("not-a-smiles")


def test_retro_endpoint():
    info = keysdb.provision("r@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/retro", json={"smiles": "CC(=O)Nc1ccccc1"},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 1
    assert body["n"] >= 1
    # at least one reactants set is present
    assert all("reactants" in s for s in body["steps"])


def test_retro_endpoint_auth():
    client = TestClient(api.app)
    r = client.post("/retro", json={"smiles": "CCO"})
    assert r.status_code == 401


# ---------- plans ----------

def test_plans_catalog():
    assert any(p["id"] == "research" for p in plans.PLANS)
    assert plans.by_id("commercial")["price_usd"] == 299
    assert plans.by_id("nope") is None


def test_plans_endpoint():
    client = TestClient(api.app)
    r = client.get("/plans")
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()["plans"]}
    assert {"free", "research", "commercial", "enterprise"} <= ids


# ---------- dashboard ----------

def test_dashboard_served():
    client = TestClient(api.app)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Q-Mol Dashboard" in r.text
    assert "/usage/history" in r.text
