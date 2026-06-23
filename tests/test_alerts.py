"""Tests for structural-alert screening module + /alerts endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import (alerts, scopes, keys as keysdb, ratelimit,
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

def test_clean_molecule():
    r = alerts.screen_one("CCO")
    assert r.clean is True
    assert r.n_alerts == 0
    assert r.catalogs_hit == []


def test_toxicophore_flagged():
    r = alerts.screen_one("O=[N+]([O-])c1ccccc1")   # nitroaromatic
    assert r.clean is False
    assert "BRENK" in r.catalogs_hit
    assert any("nitro" in a["description"].lower() for a in r.alerts)


def test_catechol_multiple_catalogs():
    r = alerts.screen_one("Oc1ccccc1O")
    assert len(r.catalogs_hit) >= 2     # PAINS/BRENK/NIH all flag catechols


def test_invalid_raises():
    with pytest.raises(ValueError):
        alerts.screen_one("not-a-smiles")


# ---------- endpoint ----------

def test_alerts_requires_key():
    client = TestClient(api.app)
    r = client.post("/alerts", json={"smiles": ["CCO"]})
    assert r.status_code == 401


def test_alerts_happy_path_charges_per_molecule():
    info = keysdb.provision("al@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/alerts", json={"smiles": ["CCO", "O=[N+]([O-])c1ccccc1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 2
    assert body["results"][0]["clean"] is True
    assert body["results"][1]["clean"] is False

    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 2


def test_alerts_catalogs_public():
    client = TestClient(api.app)
    r = client.get("/alerts/catalogs")
    assert r.status_code == 200
    cats = r.json()["catalogs"]
    assert "BRENK" in cats and "PAINS_A" in cats


def test_alerts_bad_smiles_400():
    info = keysdb.provision("al2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/alerts", json={"smiles": ["bad-smiles"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


def test_alerts_scope_enforced():
    info = keysdb.provision("al3@u.com", "research")
    scopes.set_scopes(info.key, ["compute"])     # no alerts scope
    client = TestClient(api.app)
    r = client.post("/alerts", json={"smiles": ["CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    scopes.set_scopes(info.key, ["alerts"])
    r2 = client.post("/alerts", json={"smiles": ["CCO"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
