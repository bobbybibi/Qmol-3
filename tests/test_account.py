"""Tests for account export + deletion (GDPR / Play 'delete my account')."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api
from src import keys as keysdb, ratelimit, audit, cache as result_cache, scopes


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(api, "API_KEYS", set())
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(audit, "LOG_FILE", tmp_path / "logs" / "api.jsonl")
    result_cache.COMPUTE_CACHE.clear()
    yield


# ---------- export ----------

def test_export_requires_key():
    client = TestClient(api.app)
    assert client.get("/account/export").status_code == 401


def test_export_returns_account():
    info = keysdb.provision("e@u.com", "research")
    keysdb.record(info.key, "/compute/premium", 5)
    client = TestClient(api.app)
    r = client.get("/account/export", headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["account"]["email"] == "e@u.com"
    assert body["account"]["tier"] == "research"
    assert body["used_this_month"] == 5
    assert "usage_by_endpoint" in body


# ---------- delete ----------

def test_delete_requires_key():
    client = TestClient(api.app)
    assert client.delete("/account").status_code == 401
    assert client.delete("/account", headers={"x-api-key": "nope"}).status_code == 401


def test_delete_removes_everything():
    info = keysdb.provision("d@u.com", "research")
    keysdb.record(info.key, "/compute/premium", 7)
    scopes.set_scopes(info.key, ["compute"])
    assert keysdb.month_usage(info.key) == 7

    client = TestClient(api.app)
    r = client.delete("/account", headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] is True
    assert body["email"] == "d@u.com"
    assert body["keys_deleted"] == 1

    # key is gone, usage is gone, scopes are gone
    assert keysdb.lookup(info.key) is None
    assert keysdb.month_usage(info.key) == 0
    assert scopes.get_scopes(info.key) is None
    # and the now-deleted key no longer authenticates
    assert client.get("/account/export",
                      headers={"x-api-key": info.key}).status_code == 401


def test_delete_removes_all_keys_under_email():
    a = keysdb.provision("multi@u.com", "research")
    b = keysdb.provision("multi@u.com", "commercial")   # same email, 2nd tier/key
    assert a.key != b.key
    client = TestClient(api.app)
    r = client.delete("/account", headers={"x-api-key": a.key})
    assert r.status_code == 200, r.text
    assert r.json()["keys_deleted"] == 2
    assert keysdb.lookup(a.key) is None
    assert keysdb.lookup(b.key) is None
