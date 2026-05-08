"""Tests for teams, Prometheus /metrics, scaffolds, packaging artifacts."""
from __future__ import annotations
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from src import teams, prom, scaffolds, keys as keysdb, ratelimit


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(api, "API_KEYS", set())
    monkeypatch.setattr(api, "ADMIN_TOKEN", "admintok")
    yield
    ratelimit.reset()


# ---------- teams ----------

def test_team_create_and_member_pool():
    k1 = keysdb.provision("a@x.com", "research").key
    k2 = keysdb.provision("b@x.com", "research").key
    t = teams.create("Acme", "enterprise", 1_000_000, owner_email="acme@x.com")
    teams.add_member(t.id, k1)
    teams.add_member(t.id, k2)

    # Both keys resolve to the same team
    assert teams.team_for_key(k1).id == t.id
    assert teams.team_for_key(k2).id == t.id

    # Usage pooled
    keysdb.record(k1, "/compute", 100)
    keysdb.record(k2, "/compute", 200)
    assert teams.month_usage(t.id) == 300

    used, quota = teams.effective_quota(k1)
    assert used == 300
    assert quota == 1_000_000


def test_team_remove_member():
    k = keysdb.provision("c@x.com", "research").key
    t = teams.create("T", "research", 50_000)
    teams.add_member(t.id, k)
    assert teams.team_for_key(k) is not None
    teams.remove_member(t.id, k)
    assert teams.team_for_key(k) is None


def test_effective_quota_falls_back_to_key():
    k = keysdb.provision("solo@x.com", "research").key
    used, quota = teams.effective_quota(k)
    assert used == 0
    assert quota > 0


def test_team_endpoints_require_admin():
    client = TestClient(api.app)
    r = client.post("/teams", json={"name": "X", "tier": "research",
                                    "monthly_quota": 1000})
    assert r.status_code == 401

    r = client.post("/teams", json={"name": "X", "tier": "research",
                                    "monthly_quota": 1000},
                    headers={"x-admin-token": "admintok"})
    assert r.status_code == 200
    team_id = r.json()["id"]

    k = keysdb.provision("d@x.com", "research").key
    r = client.post("/teams/members",
                    json={"team_id": team_id, "api_key": k},
                    headers={"x-admin-token": "admintok"})
    assert r.status_code == 200

    r = client.get(f"/teams/{team_id}",
                   headers={"x-admin-token": "admintok"})
    assert r.status_code == 200
    body = r.json()
    assert body["member_count"] >= 1
    assert k in body["members"]


def test_team_quota_gates_endpoint():
    """When a member key hits the team pool limit, scaffolds endpoint 402s."""
    k = keysdb.provision("poolcap@x.com", "research").key
    t = teams.create("Small", "research", 5)
    teams.add_member(t.id, k)
    client = TestClient(api.app)
    r = client.post("/scaffolds",
                    json={"smiles": ["CCO", "c1ccccc1", "CCCC",
                                     "CCN", "CCOCC", "c1ccncc1"]},
                    headers={"x-api-key": k})
    assert r.status_code == 402


# ---------- Prometheus ----------

def test_prom_render_contains_expected_metrics():
    keysdb.provision("p1@x.com", "research")
    keysdb.provision("p2@x.com", "commercial")
    text = prom.render()
    assert "qmol_api_keys_active" in text
    assert 'qmol_api_keys_by_tier{tier="research"}' in text
    assert "qmol_uptime_seconds" in text


def test_metrics_endpoint():
    client = TestClient(api.app)
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "qmol_api_keys_active" in r.text
    assert r.headers["content-type"].startswith("text/plain")


# ---------- scaffolds ----------

def test_scaffold_of_benzene():
    s = scaffolds.scaffold_of("c1ccccc1C")
    # Scaffold of toluene = benzene
    assert s == "c1ccccc1"


def test_scaffold_analyze_groups():
    rows = scaffolds.analyze(
        ["c1ccccc1C", "c1ccccc1CC", "c1ccccc1CCC", "CCO", "CCCO"],
        top_k=10,
    )
    # Benzene scaffold should lead with 3 members
    top = rows[0]
    assert top.scaffold == "c1ccccc1"
    assert top.count == 3


def test_scaffold_invalid_skipped():
    rows = scaffolds.analyze(["CCO", "not-a-mol", "CCO"], top_k=5)
    # invalid is silently skipped
    assert sum(r.count for r in rows) == 2


def test_scaffolds_endpoint_charges_quota():
    k = keysdb.provision("scaf@x.com", "research").key
    client = TestClient(api.app)
    smis = ["c1ccccc1C", "c1ccccc1CC", "CCO"]
    r = client.post("/scaffolds", json={"smiles": smis},
                    headers={"x-api-key": k})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quota_charged"] == 3
    assert body["n_unique_scaffolds"] >= 2
    assert keysdb.month_usage(k) == 3


# ---------- packaging ----------

def test_client_pyproject_valid():
    root = Path(__file__).resolve().parents[1]
    pp = root / "packaging" / "qmol-client" / "pyproject.toml"
    assert pp.exists()
    text = pp.read_text()
    assert 'name = "qmol-client"' in text
    assert "qmol = \"qmol_client:_cli_main\"" in text


def test_qmol_client_has_cli_main():
    import qmol_client
    assert hasattr(qmol_client, "_cli_main")
    assert hasattr(qmol_client, "QMolClient")


def test_qmol_client_cli_parser_accepts_compute():
    """Smoke: argparse accepts the `compute` subcommand and SMILES args.
    We don't actually hit the network — we monkeypatch Client.compute."""
    import qmol_client
    import sys
    called = {}
    class FakeClient:
        def __init__(self, *a, **k): pass
        def compute(self, s): called["s"] = list(s); return [{"smiles": s[0]}]
    orig = qmol_client.Client
    qmol_client.Client = FakeClient
    try:
        old_argv = sys.argv[:]
        sys.argv = ["qmol", "compute", "CCO"]
        qmol_client._cli_main()
        sys.argv = old_argv
    finally:
        qmol_client.Client = orig
    assert called["s"] == ["CCO"]
