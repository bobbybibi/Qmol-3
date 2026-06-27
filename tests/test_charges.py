"""Tests for the Gasteiger charges module + /charges endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import (charges, scopes, keys as keysdb, ratelimit,
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

def test_ethanol_oxygen_most_negative():
    r = charges.compute_one("CCO")
    by_sym = {a["symbol"]: a["charge"] for a in r.atoms}
    assert len(r.atoms) == 3                  # heavy atoms only by default
    assert by_sym["O"] < by_sym["C"]          # O carries negative charge
    assert abs(r.total_charge) < 0.01         # neutral molecule conserves to ~0


def test_include_hs_reports_hydrogens():
    r = charges.compute_one("CCO", include_hs=True)
    assert any(a["symbol"] == "H" for a in r.atoms)
    assert len(r.atoms) == 9                  # C2H6O


def test_anion_total_charge_near_minus_one():
    r = charges.compute_one("CC(=O)[O-]")
    assert abs(r.total_charge - (-1.0)) < 0.05


def test_invalid_raises():
    with pytest.raises(ValueError):
        charges.compute_one("not-a-smiles")


# ---------- endpoint ----------

def test_charges_requires_key():
    client = TestClient(api.app)
    r = client.post("/charges", json={"smiles": ["CCO"]})
    assert r.status_code == 401


def test_charges_happy_path_charges_per_molecule():
    info = keysdb.provision("q@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/charges", json={"smiles": ["CCO", "c1ccccc1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 2
    assert len(body["results"]) == 2
    assert body["results"][0]["atoms"][0]["charge"] is not None

    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 2


def test_charges_bad_smiles_400():
    info = keysdb.provision("q2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/charges", json={"smiles": ["bad-smiles"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


def test_charges_scope_enforced():
    info = keysdb.provision("q3@u.com", "research")
    scopes.set_scopes(info.key, ["compute"])     # no charges scope
    client = TestClient(api.app)
    r = client.post("/charges", json={"smiles": ["CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    scopes.set_scopes(info.key, ["charges"])
    r2 = client.post("/charges", json={"smiles": ["CCO"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
