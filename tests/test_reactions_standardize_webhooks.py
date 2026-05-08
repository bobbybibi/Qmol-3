"""Tests for reactions, standardization, webhooks_out, openapi dump, jobs-hook."""
from __future__ import annotations
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api
from src import (reactions, standardize, webhooks_out, keys as keysdb,
                 ratelimit, jobs)


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(keysdb, "DEFAULT_DB", tmp_path / "k.sqlite")
    monkeypatch.setattr(api, "API_KEYS", set())
    yield
    ratelimit.reset()


# ---------- reactions ----------

def test_amide_template():
    acids = ["CC(=O)O", "c1ccccc1C(=O)O"]
    amines = ["CN", "NCC"]
    res = reactions.enumerate_library("amide", [acids, amines])
    assert res.n_products >= 4
    assert all("C(=O)N" in p or "N" in p for p in res.products)


def test_suzuki_template():
    aryl_halides = ["Brc1ccccc1"]
    boronics = ["OB(O)c1ccncc1"]
    res = reactions.enumerate_library("suzuki", [aryl_halides, boronics])
    assert res.n_products >= 1


def test_reaction_invalid_smarts():
    with pytest.raises(ValueError):
        reactions.enumerate_library("not_a_template", [["CCO"]])


def test_reaction_invalid_reagent_smiles():
    with pytest.raises(ValueError):
        reactions.enumerate_library("amide", [["CC(=O)O"], ["not-a-mol"]])


def test_reaction_max_products_guard():
    with pytest.raises(ValueError):
        reactions.enumerate_library(
            "amide",
            [["CC(=O)O"] * 50, ["CN"] * 50],
            max_products=10,
        )


def test_react_endpoint():
    info = keysdb.provision("rxn@u.com", "commercial")
    client = TestClient(api.app)
    r = client.post("/react", json={
        "template": "amide",
        "reagents": [["CC(=O)O"], ["CN", "NCC"]],
    }, headers={"x-api-key": info.key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_products"] >= 2
    assert body["quota_charged"] == body["n_products"]


def test_react_templates_public():
    client = TestClient(api.app)
    r = client.get("/react/templates")
    assert r.status_code == 200
    assert "amide" in r.json()["templates"]


# ---------- standardization ----------

def test_standardize_salt_strip():
    r = standardize.standardize_one("CC(=O)[O-].[Na+]")
    # Sodium counter-ion dropped
    assert "Na" not in r.output
    assert r.changed


def test_standardize_tautomer():
    # 2-hydroxypyridine <-> 2-pyridone canonicalization
    r = standardize.standardize_one("Oc1ccccn1")
    assert r.inchikey  # valid inchikey produced
    assert r.canonical_tautomer


def test_standardize_invalid():
    with pytest.raises(ValueError):
        standardize.standardize_one("totally-not-smiles")


def test_standardize_endpoint():
    info = keysdb.provision("std@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/standardize",
                    json={"smiles": ["CC(=O)[O-].[Na+]", "CCO"]},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200
    body = r.json()
    assert body["quota_charged"] == 2
    assert len(body["results"]) == 2
    assert keysdb.month_usage(info.key) == 2


# ---------- webhooks out ----------

def test_webhook_subscribe_roundtrip():
    info = keysdb.provision("wh@u.com", "research")
    client = TestClient(api.app)
    r = client.post("/webhooks/subscribe",
                    json={"url": "https://example.com/hook", "secret": "s"},
                    headers={"x-api-key": info.key})
    assert r.status_code == 200
    sub = webhooks_out.get(info.key)
    assert sub and sub.url == "https://example.com/hook"
    r2 = client.delete("/webhooks/subscribe",
                       headers={"x-api-key": info.key})
    assert r2.status_code == 200
    assert webhooks_out.get(info.key) is None


def test_webhook_deliver_success(monkeypatch):
    info = keysdb.provision("wh2@u.com", "research")
    webhooks_out.subscribe(info.key, "https://x/hook", secret="topsecret")
    calls = []

    class R:
        status_code = 200
        text = "ok"

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append((url, data, headers))
        return R()

    monkeypatch.setattr(webhooks_out, "requests",
                        type("M", (), {"post": staticmethod(fake_post)}))
    ok = webhooks_out.deliver(info.key, "job.done", {"job_id": "abc"})
    assert ok
    assert len(calls) == 1
    _, _, hdrs = calls[0]
    assert hdrs["x-qmol-signature"].startswith("sha256=")


def test_webhook_deliver_retries(monkeypatch):
    info = keysdb.provision("wh3@u.com", "research")
    webhooks_out.subscribe(info.key, "https://x/hook")

    attempts = {"n": 0}

    def fake_post(*a, **k):
        attempts["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(webhooks_out, "MAX_ATTEMPTS", 3)
    monkeypatch.setattr(webhooks_out, "BACKOFF_BASE", 1.0)  # 1^n = 1s -> still 2s total, ok
    # actually set to 0 wait via monkeypatching time.sleep
    monkeypatch.setattr(webhooks_out.time, "sleep", lambda s: None)
    monkeypatch.setattr(webhooks_out, "requests",
                        type("M", (), {"post": staticmethod(fake_post)}))
    ok = webhooks_out.deliver(info.key, "job.failed", {"job_id": "z"})
    assert not ok
    assert attempts["n"] == 3


def test_webhook_none_when_no_sub():
    info = keysdb.provision("wh4@u.com", "research")
    assert webhooks_out.get(info.key) is None
    assert not webhooks_out.deliver(info.key, "x", {})


# ---------- openapi dump ----------

def test_openapi_spec_generated():
    spec = api.app.openapi()
    assert spec["openapi"].startswith("3.")
    paths = spec["paths"]
    for p in ["/compute", "/react", "/standardize", "/conformers",
              "/webhooks/subscribe", "/auth/magic-link", "/coupon/check"]:
        assert p in paths, f"missing {p}"


def test_dump_openapi_script(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import dump_openapi
    monkeypatch.chdir(tmp_path)
    # Point script's ROOT at tmp to avoid polluting landing/
    monkeypatch.setattr(dump_openapi, "ROOT", tmp_path)
    out = dump_openapi.main()
    assert out.exists()
    data = json.loads(out.read_text())
    assert "paths" in data
