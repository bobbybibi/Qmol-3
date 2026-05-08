"""Tests for ADMET prediction and uptime status."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import keys as keysdb, predict, status_store, ratelimit


@pytest.fixture(autouse=True)
def _reset():
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(status_store, "DEFAULT_DB", tmp_path / "s.sqlite")
    monkeypatch.setattr(api, "API_KEYS", set())


# ---------- predict ----------

def test_predict_one_caffeine():
    r = predict.predict_one("Cn1cnc2c1c(=O)n(C)c(=O)n2C")
    assert r.gi_absorption in ("high", "low")
    assert r.herg_risk in ("low", "medium", "high")
    assert 0 <= r.bbb_probability <= 1
    assert 1 <= r.sa_score_lite <= 10


def test_predict_invalid_smiles_raises():
    with pytest.raises(ValueError):
        predict.predict_one("not-smiles")


def test_predict_endpoint_charges_3x(isolated):
    info = keysdb.provision("p@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/predict", json={"smiles": ["CCO", "c1ccccc1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 6
    assert len(body["results"]) == 2
    assert keysdb.month_usage(info.key) == 6


def test_predict_endpoint_bad_smiles_400(isolated):
    info = keysdb.provision("p2@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/predict", json={"smiles": ["not-a-mol"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 400


# ---------- status / uptime ----------

def test_status_records_on_request(isolated):
    client = TestClient(api.app)
    client.get("/health")
    client.get("/health")
    s = status_store.summary(window_seconds=3600)
    assert s["samples"] >= 2
    assert s["uptime"] == 1.0


def test_status_endpoint_returns_summary(isolated):
    client = TestClient(api.app)
    client.get("/health")
    r = client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert "24h" in body and "7d" in body
    assert body["24h"]["samples"] >= 1
    assert body["24h"]["uptime_pct"] > 0


def test_status_direct_record(isolated):
    status_store.record(True, 12.5, "ok")
    status_store.record(False, 999, "fail")
    s = status_store.summary()
    assert s["samples"] == 2
    assert s["uptime_pct"] == 50.0
