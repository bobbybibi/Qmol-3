"""CLI parity tests for the newer science commands."""
from __future__ import annotations

from typer.testing import CliRunner

from cli import cli as qmol_cli

runner = CliRunner()


def test_cli_fingerprint_morgan():
    r = runner.invoke(qmol_cli, ["fingerprint", "CCO", "c1ccccc1"])
    assert r.exit_code == 0
    assert "morgan" in r.output
    assert "on_bits=" in r.output


def test_cli_fingerprint_maccs_width():
    r = runner.invoke(qmol_cli, ["fingerprint", "CCO", "--kind", "maccs"])
    assert r.exit_code == 0
    assert "n_bits=167" in r.output


def test_cli_fingerprint_bad_smiles():
    r = runner.invoke(qmol_cli, ["fingerprint", "not-a-smiles"])
    assert r.exit_code == 0
    assert "FAIL" in r.output


def test_cli_tautomers():
    r = runner.invoke(qmol_cli, ["tautomers", "O=C1CCCCC1"])
    assert r.exit_code == 0
    assert "canonical=" in r.output


def test_cli_cluster():
    r = runner.invoke(qmol_cli, ["cluster", "CCO", "CCO", "c1ccccc1",
                                 "--cutoff", "0.3"])
    assert r.exit_code == 0
    assert "clusters" in r.output
    assert "centroid=" in r.output


def test_cli_cluster_all_invalid_exits_nonzero():
    r = runner.invoke(qmol_cli, ["cluster", "nope", "bad"])
    assert r.exit_code == 1


def test_cli_formula():
    r = runner.invoke(qmol_cli, ["formula", "CC(=O)Oc1ccccc1C(=O)O"])
    assert r.exit_code == 0
    assert "C9H8O4" in r.output
    assert "RDBE=6" in r.output


def test_cli_convert():
    r = runner.invoke(qmol_cli, ["convert", "CC(=O)Oc1ccccc1C(=O)O"])
    assert r.exit_code == 0
    assert "BSYNRYMUTXBXSQ-UHFFFAOYSA-N" in r.output


def test_cli_descriptors_subset():
    r = runner.invoke(qmol_cli, ["descriptors", "CCO", "--names", "MolWt,TPSA"])
    assert r.exit_code == 0
    assert "MolWt=" in r.output and "TPSA=" in r.output


def test_cli_descriptors_full_count():
    r = runner.invoke(qmol_cli, ["descriptors", "CCO"])
    assert r.exit_code == 0
    assert "n_descriptors=" in r.output


def test_cli_mcs():
    r = runner.invoke(qmol_cli, ["mcs", "c1ccccc1C(=O)O", "c1ccccc1C(=O)N"])
    assert r.exit_code == 0
    assert "SMARTS:" in r.output
    assert "atoms=" in r.output


def test_cli_mcs_needs_two_exits_nonzero():
    r = runner.invoke(qmol_cli, ["mcs", "c1ccccc1"])
    assert r.exit_code == 1


def test_cli_charges():
    r = runner.invoke(qmol_cli, ["charges", "CCO"])
    assert r.exit_code == 0
    assert "total=" in r.output
    assert " O " in r.output           # oxygen atom row


def test_cli_alerts_clean():
    r = runner.invoke(qmol_cli, ["alerts", "CCO"])
    assert r.exit_code == 0
    assert "CLEAN" in r.output


def test_cli_alerts_flagged():
    r = runner.invoke(qmol_cli, ["alerts", "O=[N+]([O-])c1ccccc1"])
    assert r.exit_code == 0
    assert "BRENK" in r.output


def test_cli_stereoisomers():
    r = runner.invoke(qmol_cli, ["stereoisomers", "CC(O)C(N)C(=O)O"])
    assert r.exit_code == 0
    assert "n=4" in r.output


def test_cli_shape3d():
    r = runner.invoke(qmol_cli, ["shape3d", "c1ccccc1"])
    assert r.exit_code == 0
    assert "NPR1=" in r.output and "NPR2=" in r.output
