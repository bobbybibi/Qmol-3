"""Tests for identifier/format conversion module + /convert endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import (convert, scopes, keys as keysdb, ratelimit,
                 audit, cache as result_cache)

ASPIRIN_SMI = "CC(=O)Oc1ccccc1C(=O)O"
ASPIRIN_IKEY = "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"


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

def test_smiles_to_identifiers():
    c = convert.convert_one(ASPIRIN_SMI)
    assert c.inchikey == ASPIRIN_IKEY
    assert c.inchi.startswith("InChI=1S/C9H8O4")
    assert c.canonical_smiles == "CC(=O)Oc1ccccc1C(=O)O"
    assert c.molblock is None             # not requested


def test_with_molblock():
    c = convert.convert_one("CCO", with_molblock=True)
    assert c.molblock is not None and "V2000" in c.molblock


def test_noncanonical_input_canonicalizes():
    # a deliberately non-canonical benzene spelling -> same canonical form
    a = convert.convert_one("C1=CC=CC=C1")
    b = convert.convert_one("c1ccccc1")
    assert a.canonical_smiles == b.canonical_smiles
    assert a.inchikey == b.inchikey


def test_from_inchi():
    ich = convert.convert_one(ASPIRIN_SMI).inchi
    c = convert.convert_one(ich, input_format="inchi")
    assert c.inchikey == ASPIRIN_IKEY


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        convert.convert_one("CCO", input_format="mol2")


def test_invalid_input_raises():
    with pytest.raises(ValueError):
        convert.convert_one("not-a-smiles")


# ---------- endpoint ----------

def test_convert_requires_key():
    client = TestClient(api.app)
    r = client.post("/convert", json={"smiles": ["CCO"]})
    assert r.status_code == 401


def test_convert_happy_path_charges_per_molecule():
    info = keysdb.provision("cv@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/convert", json={"smiles": [ASPIRIN_SMI, "CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 2
    assert body["results"][0]["inchikey"] == ASPIRIN_IKEY

    u = client.get("/usage", headers={"x-api-key": info.key})
    assert u.json()["used_this_month"] == 2


def test_convert_bad_smiles_400():
    info = keysdb.provision("cv2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/convert", json={"smiles": ["bad-smiles"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


def test_convert_scope_enforced():
    info = keysdb.provision("cv3@u.com", "research")
    scopes.set_scopes(info.key, ["compute"])     # no convert scope
    client = TestClient(api.app)
    r = client.post("/convert", json={"smiles": ["CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 403
    scopes.set_scopes(info.key, ["convert"])
    r2 = client.post("/convert", json={"smiles": ["CCO"]},
                     headers={"x-api-key": info.key})
    assert r2.status_code == 200, r2.text
