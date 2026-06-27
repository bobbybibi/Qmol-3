"""Tests for the molecular fingerprints module + /fingerprints endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import (fingerprints, scopes, keys as keysdb, ratelimit,
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

def test_morgan_default():
    fp = fingerprints.compute_one("CC(=O)Oc1ccccc1C(=O)O")
    assert fp.kind == "morgan"
    assert fp.n_bits == 2048
    assert fp.bits is not None and fp.base64 is None
    assert fp.n_on_bits == len(fp.bits) > 0
    assert all(0 <= b < 2048 for b in fp.bits)


def test_radius_changes_fingerprint():
    a = fingerprints.compute_one("CC(=O)Oc1ccccc1C(=O)O", radius=2)
    b = fingerprints.compute_one("CC(=O)Oc1ccccc1C(=O)O", radius=4)
    # larger radius captures more environments -> generally more on-bits
    assert a.bits != b.bits


def test_maccs_fixed_width():
    fp = fingerprints.compute_one("CCO", kind="maccs")
    assert fp.n_bits == 167          # MACCS is fixed-width
    assert fp.n_on_bits > 0


@pytest.mark.parametrize("kind", ["morgan", "rdkit", "atompair", "torsion", "maccs"])
def test_all_kinds_produce_bits(kind):
    fp = fingerprints.compute_one("c1ccccc1", kind=kind)
    assert fp.n_on_bits >= 0
    assert fp.bits is not None


def test_output_base64_and_both():
    b64 = fingerprints.compute_one("CCO", output="base64")
    assert b64.base64 is not None and b64.bits is None
    both = fingerprints.compute_one("CCO", output="both")
    assert both.base64 is not None and both.bits is not None


def test_base64_roundtrips_to_same_onbits():
    from rdkit.DataStructs import ExplicitBitVect
    fp = fingerprints.compute_one("CC(=O)Oc1ccccc1C(=O)O", output="both")
    bv = ExplicitBitVect(fp.n_bits)
    bv.FromBase64(fp.base64)
    assert list(bv.GetOnBits()) == fp.bits


def test_invalid_smiles_raises():
    with pytest.raises(ValueError):
        fingerprints.compute_one("not-a-smiles")


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        fingerprints.compute_one("CCO", kind="nope")


def test_unknown_output_raises():
    with pytest.raises(ValueError):
        fingerprints.compute_one("CCO", output="nope")


# ---------- endpoint ----------

def test_fingerprints_requires_key():
    client = TestClient(api.app)
    r = client.post("/fingerprints", json={"smiles": ["CCO"]})
    assert r.status_code == 401


def test_fingerprints_happy_path_charges_per_molecule():
    info = keysdb.provision("fp@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/fingerprints",
                    json={"smiles": ["CCO", "c1ccccc1", "CC(=O)O"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "morgan"
    assert body["n"] == 3
    assert body["quota_charged"] == 3
    assert len(body["results"]) == 3
    assert all(row["bits"] is not None for row in body["results"])

    # usage reflects the 3 charged SMILES
    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 3


def test_fingerprints_maccs_via_api():
    info = keysdb.provision("fp2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/fingerprints",
                    json={"smiles": ["CCO"], "kind": "maccs"},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["n_bits"] == 167


def test_fingerprints_bad_kind_400():
    info = keysdb.provision("fp3@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/fingerprints",
                    json={"smiles": ["CCO"], "kind": "bogus"},
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


def test_fingerprints_kinds_public():
    client = TestClient(api.app)
    r = client.get("/fingerprints/kinds")
    assert r.status_code == 200
    body = r.json()
    assert "morgan" in body["kinds"] and "maccs" in body["kinds"]
    assert body["defaults"]["kind"] == "morgan"


def test_fingerprints_scope_enforced():
    info = keysdb.provision("fp4@u.com", "research")
    scopes.set_scopes(info.key, ["usage"])   # not allowed to hit /fingerprints
    client = TestClient(api.app)
    r = client.post("/fingerprints", json={"smiles": ["CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    # and a key scoped to fingerprints is allowed
    scopes.set_scopes(info.key, ["fingerprints", "usage"])
    r2 = client.post("/fingerprints", json={"smiles": ["CCO"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
