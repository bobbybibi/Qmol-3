"""Tests for rate limiting, self-signup, admin CLI, qmol_client SDK."""
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import api
from src import keys as keysdb, ratelimit
from admin import app as admin_app


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def isolated_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(api, "API_KEYS", set())


# ---------- rate limiter ----------

def test_ratelimit_allows_under_limit():
    for _ in range(5):
        ratelimit.check("u1", limit=5, window_seconds=60)


def test_ratelimit_blocks_over_limit():
    for _ in range(3):
        ratelimit.check("u2", limit=3, window_seconds=60)
    with pytest.raises(ratelimit.RateLimited):
        ratelimit.check("u2", limit=3, window_seconds=60)


# ---------- /signup ----------

def test_signup_returns_key(isolated_keys):
    client = TestClient(api.app)
    r = client.post("/signup", json={"email": "new@user.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["api_key"].startswith("qmol_")
    assert body["tier"] == "free"
    assert body["monthly_quota"] == 500


def test_signup_is_idempotent_by_email(isolated_keys):
    client = TestClient(api.app)
    r1 = client.post("/signup", json={"email": "same@u.com"})
    ratelimit.reset()  # bypass per-IP throttle so we can re-signup
    r2 = client.post("/signup", json={"email": "same@u.com"})
    assert r1.json()["api_key"] == r2.json()["api_key"]


def test_signup_rate_limited(isolated_keys):
    client = TestClient(api.app)
    r1 = client.post("/signup", json={"email": "a@b.com"})
    r2 = client.post("/signup", json={"email": "c@d.com"})
    assert r1.status_code == 200
    assert r2.status_code == 429


def test_signup_rejects_bad_email(isolated_keys):
    client = TestClient(api.app)
    r = client.post("/signup", json={"email": "not-an-email"})
    assert r.status_code == 422


# ---------- admin CLI ----------

def test_admin_report_runs(isolated_keys, tmp_path):
    keysdb.provision("x@y.com", "commercial")
    keysdb.provision("a@b.com", "research")
    runner = CliRunner()
    result = runner.invoke(admin_app, ["report"])
    assert result.exit_code == 0
    assert "commercial" in result.output
    assert "research" in result.output


def test_admin_revenue(isolated_keys):
    keysdb.provision("rev@x.com", "commercial")
    keysdb.provision("rev2@x.com", "research")
    runner = CliRunner()
    result = runner.invoke(admin_app, ["revenue"])
    assert result.exit_code == 0
    # commercial $299 + research $29 = $328
    assert "$328" in result.output or "328" in result.output


def test_admin_issue_and_revoke(isolated_keys):
    runner = CliRunner()
    r = runner.invoke(admin_app, ["issue", "give@away.com", "--tier", "research"])
    assert r.exit_code == 0
    key = r.output.split("Issued:")[1].strip().split()[0]

    info = keysdb.lookup(key)
    assert info and info.active

    r2 = runner.invoke(admin_app, ["revoke", key])
    assert r2.exit_code == 0
    assert not keysdb.lookup(key).active


# ---------- qmol_client SDK ----------

def test_client_compute_against_local_app(isolated_keys):
    """SDK hits the live in-process TestClient."""
    import qmol_client

    client_app = TestClient(api.app)

    class _Adapter:
        @staticmethod
        def post(url, json=None, headers=None, timeout=None):
            path = url.split("://", 1)[-1].split("/", 1)[-1]
            return client_app.post("/" + path, json=json, headers=headers or {})

        @staticmethod
        def get(url, headers=None, timeout=None):
            path = url.split("://", 1)[-1].split("/", 1)[-1]
            return client_app.get("/" + path, headers=headers or {})

    import qmol_client as qc
    qc.requests = _Adapter  # type: ignore[attr-defined]

    # Free path (no key)
    c = qc.Client(api_key=None, base_url="http://testserver")
    out = c.compute(["CCO"])
    assert len(out) == 1
    assert out[0]["mw"] > 0

    # Premium path (with provisioned key)
    info = keysdb.provision("sdkuser@x.com", "research")
    c2 = qc.Client(api_key=info.key, base_url="http://testserver")
    out2 = c2.compute(["c1ccccc1"])
    assert out2[0]["mw"] > 0
    usage = c2.usage()
    assert usage["tier"] == "research"
