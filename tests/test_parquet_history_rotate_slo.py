"""Tests for parquet export, usage history, key self-rotation, uptime badge."""
from __future__ import annotations
import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
from src import (parquet_out, usage_stats, keys as keysdb, ratelimit,
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


# ---------- parquet ----------

def test_to_parquet_roundtrip():
    rows = [{"smiles": "CCO", "mw": 46.0},
            {"smiles": "c1ccccc1", "mw": 78.1}]
    blob = parquet_out.to_parquet_bytes(rows)
    assert blob[:4] == b"PAR1"
    df = pd.read_parquet(io.BytesIO(blob))
    assert list(df.columns) == ["smiles", "mw"]
    assert len(df) == 2


def test_to_parquet_empty():
    blob = parquet_out.to_parquet_bytes([])
    assert blob[:4] == b"PAR1"


def test_parquet_endpoint():
    info = keysdb.provision("p@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/export/parquet", json={"smiles": ["CCO", "c1ccccc1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"PAR1"
    df = pd.read_parquet(io.BytesIO(r.content))
    assert len(df) == 2
    assert "mw" in df.columns
    assert 'filename="qmol.parquet"' in r.headers.get("content-disposition", "")


def test_parquet_endpoint_auth():
    client = TestClient(api.app)
    r = client.post("/export/parquet", json={"smiles": ["CCO"]})
    assert r.status_code == 401


# ---------- usage history ----------

def test_usage_history_endpoint():
    info = keysdb.provision("uh@u.com", "research")
    client = TestClient(api.app)
    client.get("/usage", headers={"x-api-key": info.key})
    client.get("/usage", headers={"x-api-key": info.key})
    r = client.get("/usage/history?days=7", headers={"x-api-key": info.key})
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 7
    assert "daily" in body and "by_endpoint" in body
    # at least one endpoint recorded
    paths = {e["endpoint"] for e in body["by_endpoint"]}
    assert "/usage" in paths


def test_usage_history_auth():
    client = TestClient(api.app)
    r = client.get("/usage/history")
    assert r.status_code == 401


def test_daily_counts_empty():
    out = usage_stats.daily_counts("nonexistent-key", days=30)
    assert out == []


# ---------- key self-rotation ----------

def test_key_rotate_endpoint():
    info = keysdb.provision("rot@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/key/rotate", headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "rot@u.com"
    assert body["new_key"] != info.key
    assert len(body["new_key"]) > 20
    # old key is now inactive
    old = keysdb.lookup(info.key)
    assert old is not None and old.active is False
    # new key works
    r2 = client.get("/usage", headers={"x-api-key": body["new_key"]})
    assert r2.status_code == 200


def test_key_rotate_requires_key():
    client = TestClient(api.app)
    r = client.post("/key/rotate")
    assert r.status_code == 401


def test_key_rotate_inactive_rejected():
    info = keysdb.provision("rot2@u.com", "research")
    keysdb.deactivate(info.key)
    client = TestClient(api.app)
    r = client.post("/key/rotate", headers={"x-api-key": info.key})
    assert r.status_code == 401


# ---------- uptime badge ----------

def test_uptime_badge_shape():
    client = TestClient(api.app)
    # generate some traffic
    info = keysdb.provision("slo@u.com", "research")
    for _ in range(3):
        client.get("/usage", headers={"x-api-key": info.key})
    r = client.get("/badge/uptime?days=7")
    assert r.status_code == 200
    body = r.json()
    assert body["schemaVersion"] == 1
    assert body["label"] == "uptime 7d"
    assert body["message"].endswith("%")
    assert body["color"] in {"brightgreen", "green", "yellow", "red"}
    assert 0.0 <= body["slo"] <= 1.0


def test_uptime_badge_public_no_auth():
    client = TestClient(api.app)
    r = client.get("/badge/uptime")
    assert r.status_code == 200


def test_global_slo_no_traffic():
    s = usage_stats.global_slo(days=1)
    assert s["slo"] == 1.0
    assert s["total"] == 0
