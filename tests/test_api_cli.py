"""Tests for FastAPI endpoints and CLI."""
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import api
from cli import cli as qmol_cli


client = TestClient(api.app)
runner = CliRunner()


def test_root_ok():
    r = client.get("/")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    assert "public_rows" in j


def test_compute_free_small():
    r = client.post("/compute", json={"smiles": ["CCO", "c1ccccc1"]})
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 2
    assert results[0]["success"]
    assert results[0]["mw"] > 0


def test_compute_free_limit_exceeded():
    r = client.post("/compute", json={"smiles": ["CCO"] * 501})
    assert r.status_code == 413


def test_compute_premium_requires_key(monkeypatch):
    monkeypatch.setattr(api, "API_KEYS", {"secret-test-key"})
    r = client.post("/compute/premium", json={"smiles": ["CCO"]})
    assert r.status_code == 401
    r = client.post(
        "/compute/premium",
        json={"smiles": ["CCO"]},
        headers={"x-api-key": "secret-test-key"},
    )
    assert r.status_code == 200


def test_cli_compute():
    result = runner.invoke(qmol_cli, ["compute", "CCO"])
    assert result.exit_code == 0
    assert "MW=" in result.output
    assert "QED=" in result.output


def test_cli_compute_file(tmp_path: Path):
    inp = tmp_path / "mols.csv"
    inp.write_text("smiles\nCCO\nc1ccccc1\n")
    out = tmp_path / "out.csv"
    result = runner.invoke(qmol_cli, ["compute-file", str(inp), "--out", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    content = out.read_text()
    assert "mw" in content.lower()
    assert content.count("\n") >= 3


def test_make_api_key_deterministic():
    k1 = api.make_api_key("a@b.com", "sec")
    k2 = api.make_api_key("a@b.com", "sec")
    k3 = api.make_api_key("c@d.com", "sec")
    assert k1 == k2
    assert k1 != k3
    assert k1.startswith("qmol_")
