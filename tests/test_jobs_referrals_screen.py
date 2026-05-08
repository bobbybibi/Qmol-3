"""Tests for async jobs, referral program, drug-likeness screen."""
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from src import jobs, keys as keysdb, referrals, screen, ratelimit


@pytest.fixture(autouse=True)
def _reset():
    ratelimit.reset()
    yield
    ratelimit.reset()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(jobs, "DEFAULT_DB", tmp_path / "jobs.sqlite")
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(api, "API_KEYS", set())


# ---------- screen ----------

def test_screen_one_ethanol():
    r = screen.screen_one("CCO")
    assert r.lipinski
    assert r.veber
    assert r.verdict in ("pass", "review")
    assert not r.pains_hit


def test_screen_batch_summary():
    out = screen.screen_batch(["CCO", "c1ccccc1", "CCCCCCCCCCCCCCCCCCCC"])
    assert out["summary"]["n"] == 3
    assert len(out["results"]) == 3


def test_screen_endpoint_charges_5x(isolated):
    info = keysdb.provision("s@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/screen", json={"smiles": ["CCO", "c1ccccc1"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 10
    assert body["summary"]["n"] == 2
    assert keysdb.month_usage(info.key) == 10


def test_screen_requires_key(isolated):
    client = TestClient(api.app)
    r = client.post("/screen", json={"smiles": ["CCO"]})
    assert r.status_code == 401


# ---------- jobs ----------

def test_jobs_submit_and_run_sync(isolated):
    info = keysdb.provision("j@u.com", "research")
    jid = jobs.submit(info.key, ["CCO", "CCN", "c1ccccc1"])
    assert jid.startswith("job_")
    assert jobs.get(jid).status == "queued"
    n = jobs.run_pending_sync()
    assert n == 1
    done = jobs.get(jid)
    assert done.status == "done"
    assert done.n_processed == 3
    assert Path(done.result_path).exists()
    lines = Path(done.result_path).read_text().strip().splitlines()
    assert len(lines) == 3


def test_jobs_endpoint_flow(isolated):
    info = keysdb.provision("j2@u.com", "research")
    client = TestClient(api.app)

    r = client.post("/jobs", json={"smiles": ["CCO", "CCN"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200
    jid = r.json()["job_id"]
    assert keysdb.month_usage(info.key) == 2  # charged at submit

    # Background worker may have picked it up already; poll briefly.
    import time
    deadline = time.time() + 10
    while time.time() < deadline:
        info2 = jobs.get(jid)
        if info2 and info2.status in ("done", "failed"):
            break
        jobs.run_pending_sync()
        time.sleep(0.2)

    s = client.get(f"/jobs/{jid}", headers={"x-api-key": info.key})
    assert s.status_code == 200
    assert s.json()["status"] == "done"

    res = client.get(f"/jobs/{jid}/result", headers={"x-api-key": info.key})
    assert res.status_code == 200
    text = res.text.strip().splitlines()
    assert len(text) == 2


def test_jobs_ownership_enforced(isolated):
    a = keysdb.provision("a@u.com", "research")
    b = keysdb.provision("b@u.com", "research")
    jid = jobs.submit(a.key, ["CCO"])
    client = TestClient(api.app)
    r = client.get(f"/jobs/{jid}", headers={"x-api-key": b.key})
    assert r.status_code == 404


# ---------- referrals ----------

def test_referral_code_is_stable(isolated):
    info = keysdb.provision("r@u.com", "research")
    c1 = referrals.code_for(info.key)
    c2 = referrals.code_for(info.key)
    assert c1 == c2
    assert referrals.resolve(c1) == info.key


def test_referral_free_signup_gives_bonus(isolated):
    referrer = keysdb.provision("ref@u.com", "research")
    code = referrals.code_for(referrer.key)
    # simulate referrer using up some quota first
    keysdb.record(referrer.key, "/compute/premium", 1000)
    assert keysdb.month_usage(referrer.key) == 1000

    out = referrals.credit(code, "newbie@u.com", "free")
    assert out["credited"]
    assert out["bonus_smiles"] == referrals.REFERRAL_BONUS_FREE
    # negative usage row reduces month_usage
    assert keysdb.month_usage(referrer.key) == 1000 - referrals.REFERRAL_BONUS_FREE


def test_referral_paid_revenue_share(isolated):
    r = keysdb.provision("r2@u.com", "research")
    code = referrals.code_for(r.key)
    out = referrals.credit(code, "buyer@u.com", "commercial")
    assert out["revenue_cents"] == int(299 * 0.20 * 100)
    s = referrals.stats(r.key)
    assert s.paid_purchases == 1
    assert s.earned_cents == out["revenue_cents"]


def test_referral_unknown_code(isolated):
    out = referrals.credit("bogus", "x@y.com", "free")
    assert not out["credited"]


def test_signup_with_ref_credits_referrer(isolated):
    referrer = keysdb.provision("owner@u.com", "research")
    code = referrals.code_for(referrer.key)
    client = TestClient(api.app)
    r = client.post(f"/signup?ref={code}", json={"email": "via-ref@u.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["referral"]["credited"] is True


def test_referral_endpoint(isolated):
    info = keysdb.provision("me@u.com", "research")
    client = TestClient(api.app)
    r = client.get("/referral", headers={"x-api-key": info.key})
    assert r.status_code == 200
    body = r.json()
    assert body["code"]
    assert body["share_url"].startswith("/?ref=")
    assert body["total_referrals"] == 0
    assert body["earned_usd"] == 0.0
