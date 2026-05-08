"""Tests for audit log, key rotation, invoices, Dockerfile/compose presence."""
from __future__ import annotations
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from src import audit, rotate as rotatelib, invoices, teams, keys as keysdb, ratelimit


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(api, "API_KEYS", set())
    monkeypatch.setattr(audit, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(audit, "LOG_FILE", tmp_path / "logs" / "api.jsonl")
    yield
    ratelimit.reset()


# ---------- audit ----------

def test_audit_log_writes_file_and_sqlite():
    audit.log_event("qmol_test", "127.0.0.1", "GET", "/health", 200, 4)
    lf = audit.LOG_FILE
    assert lf.exists()
    rec = json.loads(lf.read_text().splitlines()[0])
    assert rec["path"] == "/health"
    assert rec["status"] == 200
    # SQLite has it too
    events = audit.recent("qmol_test", limit=5)
    assert len(events) == 1
    assert events[0]["path"] == "/health"


def test_audit_middleware_records_on_request():
    client = TestClient(api.app)
    r = client.get("/health")
    assert r.status_code == 200
    # /health has no api_key so we can't query recent() directly — check DB
    c = keysdb._connect()
    c.executescript(audit._SCHEMA)
    row = c.execute(
        "SELECT path, status FROM audit ORDER BY id DESC LIMIT 1"
    ).fetchone()
    c.close()
    assert row == ("/health", 200)


def test_audit_endpoint_returns_own_events():
    info = keysdb.provision("auditor@u.com", "research")
    client = TestClient(api.app)
    client.get("/usage", headers={"x-api-key": info.key})
    client.get("/usage", headers={"x-api-key": info.key})
    r = client.get("/audit", headers={"x-api-key": info.key})
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) >= 2
    assert all(e["path"] for e in events)


# ---------- rotation ----------

def test_rotate_issues_new_key_same_email_tier():
    old = keysdb.provision("rot@u.com", "research")
    res = rotatelib.rotate(old.key)
    assert res.new_key != old.key
    assert res.email == "rot@u.com"
    assert res.tier == "research"

    # Old key is now inactive, new one works
    assert keysdb.lookup(old.key).active is False
    assert keysdb.lookup(res.new_key).active is True


def test_rotate_preserves_team_membership():
    old = keysdb.provision("team-rot@u.com", "research")
    t = teams.create("TeamRot", "research", 50_000)
    teams.add_member(t.id, old.key)

    res = rotatelib.rotate(old.key)
    assert teams.team_for_key(res.new_key).id == t.id
    assert teams.team_for_key(old.key) is None


def test_rotate_unknown_key_raises():
    with pytest.raises(ValueError):
        rotatelib.rotate("qmol_not_real")


def test_rotate_endpoint_roundtrip():
    info = keysdb.provision("rotep@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/auth/rotate", headers={"x-api-key": info.key})
    assert r.status_code == 200
    body = r.json()
    new_key = body["new_key"]
    assert new_key != info.key
    # Old key is marked inactive
    r2 = client.get("/usage", headers={"x-api-key": info.key})
    assert r2.status_code == 200
    assert r2.json()["active"] is False
    # New key is active
    r3 = client.get("/usage", headers={"x-api-key": new_key})
    assert r3.status_code == 200
    assert r3.json()["active"] is True


# ---------- invoices ----------

def test_invoice_aggregates_usage():
    info = keysdb.provision("invoice@u.com", "commercial")
    keysdb.record(info.key, "/compute", 100)
    keysdb.record(info.key, "/compute", 50)
    keysdb.record(info.key, "/similarity", 25)

    inv = invoices.generate(info.key)
    assert inv.email == "invoice@u.com"
    assert inv.tier == "commercial"
    assert inv.total_smiles == 175
    assert inv.total_calls == 3
    assert inv.subtotal_cents == 29900

    # One line per endpoint
    eps = {l.endpoint for l in inv.lines}
    assert "/compute" in eps and "/similarity" in eps
    compute_line = next(l for l in inv.lines if l.endpoint == "/compute")
    assert compute_line.calls == 2
    assert compute_line.smiles == 150


def test_invoice_markdown_contains_totals():
    info = keysdb.provision("inv2@u.com", "research")
    keysdb.record(info.key, "/compute", 10)
    inv = invoices.generate(info.key)
    md = inv.to_markdown()
    assert "Q-Mol Invoice" in md
    assert inv.period in md
    assert "10" in md
    assert "$29.00" in md  # research tier


def test_invoice_empty_period_zero_usage():
    info = keysdb.provision("empty@u.com", "research")
    inv = invoices.generate(info.key, year_month="2020-01")
    assert inv.total_smiles == 0
    assert inv.total_calls == 0
    assert inv.lines == []


def test_invoice_endpoint():
    info = keysdb.provision("invep@u.com", "research")
    keysdb.record(info.key, "/compute", 7)
    client = TestClient(api.app)
    r = client.get("/invoice", headers={"x-api-key": info.key})
    assert r.status_code == 200
    body = r.json()
    assert body["total_smiles"] == 7
    assert "markdown" in body
    assert "Q-Mol Invoice" in body["markdown"]


def test_invoice_requires_auth():
    client = TestClient(api.app)
    r = client.get("/invoice")
    assert r.status_code == 401
    r2 = client.get("/invoice", headers={"x-api-key": "qmol_garbage"})
    assert r2.status_code == 401


# ---------- Docker artifacts ----------

def test_dockerfile_shape():
    root = Path(__file__).resolve().parents[1]
    df = (root / "Dockerfile").read_text()
    assert "FROM python:3.12" in df
    assert "uvicorn api:app" in df
    assert "HEALTHCHECK" in df
    assert "VOLUME" in df


def test_docker_compose_shape():
    root = Path(__file__).resolve().parents[1]
    dc = (root / "docker-compose.yml").read_text()
    assert "qmol-api:latest" in dc or "qmol-api" in dc
    assert "8000:8000" in dc
    assert "QMOL_ADMIN_TOKEN" in dc
