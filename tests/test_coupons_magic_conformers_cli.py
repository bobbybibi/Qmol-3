"""Tests for coupons, magic-link auth, 3D conformers, extended CLI."""
from __future__ import annotations
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import api
from cli import cli as qmol_cli
from src import coupons, magic_link, conformers, keys as keysdb, ratelimit


@pytest.fixture(autouse=True)
def _reset():
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(api, "API_KEYS", set())


# ---------- coupons ----------

def test_coupon_percent_discount(isolated):
    coupons.create("LAUNCH50", percent_off=50, max_redemptions=100)
    r = coupons.apply("LAUNCH50", "commercial", 29900)
    assert r["valid"]
    assert r["discount_cents"] == 14950
    assert r["final_cents"] == 14950


def test_coupon_fixed_amount(isolated):
    coupons.create("TENOFF", amount_off_cents=1000)
    r = coupons.apply("TENOFF", "research", 2900)
    assert r["valid"] and r["final_cents"] == 1900


def test_coupon_unknown(isolated):
    r = coupons.apply("NOPE", "research", 2900)
    assert not r["valid"]
    assert r["final_cents"] == 2900


def test_coupon_expiry(isolated):
    coupons.create("OLD", percent_off=10, expires_at=time.time() - 1)
    r = coupons.apply("OLD", "research", 2900)
    assert not r["valid"]
    assert r["reason"] == "expired"


def test_coupon_redemption_limit(isolated):
    coupons.create("ONCE", percent_off=10, max_redemptions=1)
    assert coupons.redeem("ONCE")
    assert not coupons.redeem("ONCE")
    r = coupons.apply("ONCE", "research", 2900)
    assert not r["valid"]


def test_coupon_tier_restriction(isolated):
    coupons.create("COMMONLY", percent_off=25, tier_restriction="commercial")
    r = coupons.apply("COMMONLY", "research", 2900)
    assert not r["valid"]
    r2 = coupons.apply("COMMONLY", "commercial", 29900)
    assert r2["valid"]


def test_coupon_check_endpoint(isolated):
    coupons.create("API50", percent_off=50)
    client = TestClient(api.app)
    r = client.post("/coupon/check", json={"code": "API50", "tier": "commercial"})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] and body["final_cents"] == 14950


# ---------- magic link ----------

def test_magic_link_roundtrip(isolated):
    info = keysdb.provision("mlink@u.com", "research")
    tok = magic_link.issue("mlink@u.com")
    recovered = magic_link.consume(tok)
    assert recovered == info.key


def test_magic_link_single_use(isolated):
    keysdb.provision("mlink2@u.com", "research")
    tok = magic_link.issue("mlink2@u.com")
    assert magic_link.consume(tok) is not None
    assert magic_link.consume(tok) is None  # burned


def test_magic_link_expired(isolated, monkeypatch):
    keysdb.provision("mlink3@u.com", "research")
    tok = magic_link.issue("mlink3@u.com")
    monkeypatch.setattr(magic_link, "TOKEN_TTL_SECONDS", 0)
    assert magic_link.consume(tok) is None


def test_magic_link_endpoint_returns_dev_token(isolated):
    keysdb.provision("mlink4@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/auth/magic-link", json={"email": "mlink4@u.com"})
    assert r.status_code == 200
    body = r.json()
    # Mailgun not configured in tests -> dev_token returned
    assert body["dev_token"]

    r2 = client.get(f"/auth/redeem?token={body['dev_token']}")
    assert r2.status_code == 200
    assert r2.json()["api_key"].startswith("qmol_")


def test_magic_link_bad_token(isolated):
    client = TestClient(api.app)
    r = client.get("/auth/redeem?token=garbage")
    assert r.status_code == 400


# ---------- conformers ----------

def test_conformer_ethanol():
    c = conformers.generate("CCO", n_conformers=5)
    assert c.n_conformers >= 1
    # ethanol with H's = 9 atoms
    assert len(c.coords) == 9
    assert "V2000" in c.sdf or "V3000" in c.sdf
    assert c.energy_kcal_mol < 100  # sane


def test_conformer_invalid_smiles():
    with pytest.raises(ValueError):
        conformers.generate("not-a-mol")


def test_conformer_endpoint(isolated):
    info = keysdb.provision("c@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/conformers", json={"smiles": "CCO", "n_conformers": 3},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 10
    assert len(body["coords"]) > 0
    assert keysdb.month_usage(info.key) == 10


# ---------- extended CLI ----------

def test_cli_screen():
    runner = CliRunner()
    r = runner.invoke(qmol_cli, ["screen", "CCO", "c1ccccc1"])
    assert r.exit_code == 0
    assert "n=2" in r.output


def test_cli_predict():
    runner = CliRunner()
    r = runner.invoke(qmol_cli, ["predict", "CCO"])
    assert r.exit_code == 0
    assert "BBB=" in r.output


def test_cli_conformer(tmp_path):
    runner = CliRunner()
    out = tmp_path / "c.sdf"
    r = runner.invoke(qmol_cli, ["conformer", "CCO", "--out", str(out), "--n-conformers", "3"])
    assert r.exit_code == 0, r.output
    assert out.exists()
    assert "V2000" in out.read_text() or "V3000" in out.read_text()
