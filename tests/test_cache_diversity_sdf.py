"""Tests for cache, diversity picker, SDF download, docs/reference pages."""
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from src import (cache as result_cache, diversity, sdf_out,
                 keys as keysdb, ratelimit)


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(api, "API_KEYS", set())
    result_cache.COMPUTE_CACHE.clear()
    yield


# ---------- cache ----------

def test_cache_hit_miss_and_ttl():
    c = result_cache.LRUCache(max_size=4, ttl_seconds=3600)
    c.set("a", 1)
    assert c.get("a") == 1
    assert c.get("missing") is None
    s = c.stats()
    assert s["hits"] == 1 and s["misses"] == 1


def test_cache_lru_eviction():
    c = result_cache.LRUCache(max_size=2, ttl_seconds=3600)
    c.set("a", 1); c.set("b", 2); c.set("c", 3)
    assert c.get("a") is None  # evicted
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_memoize_uses_cache():
    result_cache.COMPUTE_CACHE.clear()
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return {"x": 42}

    a = result_cache.memoize("t", "CCO", producer)
    b = result_cache.memoize("t", "CCO", producer)
    assert a == b
    assert calls["n"] == 1  # second call served from cache


def test_compute_uses_cache():
    client = TestClient(api.app)
    result_cache.COMPUTE_CACHE.clear()
    r1 = client.post("/compute", json={"smiles": ["CCO", "c1ccccc1"]})
    assert r1.status_code == 200
    r2 = client.post("/compute", json={"smiles": ["CCO", "c1ccccc1"]})
    assert r2.status_code == 200
    stats = result_cache.COMPUTE_CACHE.stats()
    assert stats["hits"] >= 2
    assert stats["size"] >= 2


# ---------- diversity ----------

def test_diversity_pick_basic():
    smis = ["CCO", "CCN", "CCC", "c1ccccc1", "c1ccncc1", "O=C(O)C"]
    r = diversity.pick(smis, k=3, seed=1)
    assert r.k == 3
    assert len(r.picked_smiles) == 3
    assert len(set(r.picked_smiles)) == 3


def test_diversity_k_ge_n_returns_all():
    smis = ["CCO", "CCN"]
    r = diversity.pick(smis, k=10)
    assert len(r.picked_smiles) == 2


def test_diversity_ignores_invalid():
    smis = ["CCO", "not-a-mol", "c1ccccc1", "???", "CCN"]
    r = diversity.pick(smis, k=2, seed=1)
    for s in r.picked_smiles:
        assert s in {"CCO", "c1ccccc1", "CCN"}


def test_diversity_endpoint():
    info = keysdb.provision("d@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/diversity", json={
        "smiles": ["CCO", "CCN", "c1ccccc1", "CCCCCCCC", "c1ccncc1"],
        "k": 3,
    }, headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["k"] == 3
    assert len(body["picked_smiles"]) == 3
    assert body["quota_charged"] == 5


def test_diversity_endpoint_auth():
    client = TestClient(api.app)
    r = client.post("/diversity", json={"smiles": ["CCO", "CCN"], "k": 1})
    assert r.status_code == 401


# ---------- SDF download ----------

def test_smiles_to_sdf_basic():
    sdf = sdf_out.smiles_to_sdf(["CCO", "c1ccccc1"])
    assert "$$$$" in sdf
    assert sdf.count("$$$$") == 2
    assert "SMILES" in sdf


def test_smiles_to_sdf_skips_invalid():
    sdf = sdf_out.smiles_to_sdf(["CCO", "not-a-mol", "CCN"])
    assert sdf.count("$$$$") == 2


def test_sdf_download_endpoint():
    info = keysdb.provision("sdf@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/download/sdf", json={"smiles": ["CCO", "c1ccccc1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("chemical/x-mdl-sdfile")
    assert "$$$$" in r.text
    assert 'filename="qmol.sdf"' in r.headers.get("content-disposition", "")


# ---------- admin cache endpoint ----------

def test_admin_cache_requires_token(monkeypatch):
    monkeypatch.setattr(api, "ADMIN_TOKEN", "secret")
    client = TestClient(api.app)
    r = client.get("/admin/cache")
    assert r.status_code == 401
    r2 = client.get("/admin/cache", headers={"x-admin-token": "secret"})
    assert r2.status_code == 200
    assert "hits" in r2.json()


# ---------- landing pages ----------

def test_reference_page_served():
    client = TestClient(api.app)
    r = client.get("/reference")
    assert r.status_code == 200
    assert "Q-Mol API Reference" in r.text
    assert "openapi.json" in r.text


def test_landing_app_served():
    root = Path(__file__).resolve().parents[1]
    if not (root / "landing" / "index.html").exists():
        pytest.skip("no landing/index.html in this checkout")
    client = TestClient(api.app)
    r = client.get("/app")
    assert r.status_code == 200
    assert "<html" in r.text.lower()
