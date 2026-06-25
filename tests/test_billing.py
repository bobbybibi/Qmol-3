"""Tests for the /billing/checkout (Stripe Checkout session) endpoint."""
from __future__ import annotations
import sys
import types

import pytest
from fastapi.testclient import TestClient

import api
from src import keys as keysdb, ratelimit, audit, cache as result_cache


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(api, "API_KEYS", set())
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(audit, "LOG_FILE", tmp_path / "logs" / "api.jsonl")
    result_cache.COMPUTE_CACHE.clear()
    # default: ensure not configured unless a test opts in
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    yield


def _fake_stripe(captured):
    mod = types.ModuleType("stripe")
    mod.api_key = None

    def create(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(url="https://checkout.stripe.test/cs_123",
                                     id="cs_test_123")
    mod.checkout = types.SimpleNamespace(Session=types.SimpleNamespace(create=create))
    return mod


def test_unknown_tier_400():
    client = TestClient(api.app)
    r = client.post("/billing/checkout", json={"tier": "platinum"})
    assert r.status_code == 400


def test_unconfigured_returns_503(monkeypatch):
    # No STRIPE_SECRET_KEY -> 503 (whether or not the stripe lib is importable)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    client = TestClient(api.app)
    r = client.post("/billing/checkout", json={"tier": "research"})
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"].lower()


def test_success_with_mocked_stripe(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "stripe", _fake_stripe(captured))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_PRICE_COMMERCIAL", "price_commercial_live")
    monkeypatch.setenv("QMOL_PUBLIC_URL", "https://qmol.app")

    client = TestClient(api.app)
    r = client.post("/billing/checkout", json={"tier": "commercial"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] == "https://checkout.stripe.test/cs_123"
    assert body["tier"] == "commercial"
    # the session was created in subscription mode with the configured price
    assert captured["mode"] == "subscription"
    assert captured["line_items"][0]["price"] == "price_commercial_live"
    assert captured["success_url"].startswith("https://qmol.app")


def test_custom_redirect_urls(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "stripe", _fake_stripe(captured))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    client = TestClient(api.app)
    r = client.post("/billing/checkout", json={
        "tier": "research",
        "success_url": "https://x.test/ok",
        "cancel_url": "https://x.test/no",
    })
    assert r.status_code == 200, r.text
    assert captured["success_url"] == "https://x.test/ok"
    assert captured["cancel_url"] == "https://x.test/no"


# ---------- compliance: privacy/terms pages + Play billing ----------

def test_privacy_policy_served():
    client = TestClient(api.app)
    r = client.get("/privacy")
    assert r.status_code == 200
    assert "Privacy Policy" in r.text
    assert "do not sell" in r.text.lower() or "not sell" in r.text.lower()


def test_terms_served():
    client = TestClient(api.app)
    r = client.get("/terms")
    assert r.status_code == 200
    assert "Terms of Service" in r.text


def test_play_unknown_product_400():
    client = TestClient(api.app)
    r = client.post("/billing/play/verify",
                    json={"product_id": "not_a_product", "purchase_token": "tok"})
    assert r.status_code == 400


def test_play_unconfigured_503(monkeypatch):
    monkeypatch.delenv("ANDROID_PACKAGE_NAME", raising=False)
    monkeypatch.delenv("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", raising=False)
    client = TestClient(api.app)
    r = client.post("/billing/play/verify",
                    json={"product_id": "qmol_research_monthly", "purchase_token": "tok"})
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"].lower()
