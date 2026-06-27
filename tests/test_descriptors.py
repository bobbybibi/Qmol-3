"""Tests for the full descriptor panel module + /descriptors endpoint."""
from __future__ import annotations
import math

import pytest
from fastapi.testclient import TestClient

import api
from src import (descriptors, scopes, keys as keysdb, ratelimit,
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

def test_full_panel_present():
    r = descriptors.compute_one("CC(=O)Oc1ccccc1C(=O)O")
    d = r["descriptors"]
    assert len(d) == len(descriptors.ALL_NAMES) > 100
    assert "MolWt" in d and abs(d["MolWt"] - 180.16) < 0.1


def test_subset_selection():
    r = descriptors.compute_one("CCO", names=["MolWt", "TPSA", "qed"])
    assert set(r["descriptors"]) == {"MolWt", "TPSA", "qed"}


def test_unknown_name_raises():
    with pytest.raises(ValueError):
        descriptors.compute_one("CCO", names=["NotADescriptor"])


def test_invalid_smiles_raises():
    with pytest.raises(ValueError):
        descriptors.compute_one("not-a-smiles")


def test_nan_inf_cleaned_to_none():
    assert descriptors._clean(float("nan")) is None
    assert descriptors._clean(float("inf")) is None
    assert descriptors._clean(1.5) == 1.5


def test_no_nan_in_output():
    # whatever the molecule, the serialized values must be JSON-safe
    r = descriptors.compute_one("[O-][N+](=O)c1ccccc1")
    assert all(not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
               for v in r["descriptors"].values())


# ---------- endpoint ----------

def test_descriptors_requires_key():
    client = TestClient(api.app)
    r = client.post("/descriptors", json={"smiles": ["CCO"]})
    assert r.status_code == 401


def test_descriptors_happy_path_charges_double():
    info = keysdb.provision("d@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/descriptors", json={"smiles": ["CCO", "c1ccccc1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 4          # 2 molecules * 2
    assert len(body["results"]) == 2
    assert "MolWt" in body["results"][0]["descriptors"]

    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 4


def test_descriptors_names_public():
    client = TestClient(api.app)
    r = client.get("/descriptors/names")
    assert r.status_code == 200
    body = r.json()
    assert body["n"] == len(descriptors.ALL_NAMES)
    assert "MolWt" in body["names"]


def test_descriptors_subset_via_api():
    info = keysdb.provision("d2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/descriptors",
                    json={"smiles": ["CCO"], "names": ["MolWt", "TPSA"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    assert set(r.json()["results"][0]["descriptors"]) == {"MolWt", "TPSA"}


def test_descriptors_bad_name_400():
    info = keysdb.provision("d3@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/descriptors",
                    json={"smiles": ["CCO"], "names": ["Nope"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


def test_descriptors_scope_enforced():
    info = keysdb.provision("d4@u.com", "research")
    scopes.set_scopes(info.key, ["compute"])      # no descriptors scope
    client = TestClient(api.app)
    r = client.post("/descriptors", json={"smiles": ["CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    scopes.set_scopes(info.key, ["descriptors"])
    r2 = client.post("/descriptors", json={"smiles": ["CCO"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
