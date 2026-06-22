"""Command-line interface: lets anyone (free tier buyers included) run Q-Mol locally.

Install (dev):
    pip install -e .
    qmol --help

Or after PyPI publish:
    pip install qmol
    qmol compute "CCO" "c1ccccc1"
    qmol compute-file mols.csv --out descriptors.parquet
"""
from __future__ import annotations
import csv
import sys
from pathlib import Path
from typing import List

import typer

from src import compute as qcompute
from src import screen as qscreen
from src import predict as qpredict
from src import similarity as qsimilarity
from src import conformers as qconformers
from src import fingerprints as qfingerprints
from src import tautomers as qtautomers
from src import clustering as qclustering
from src import formula as qformula
from src import convert as qconvert
from src import descriptors as qdescriptors
from src import storage
import config

cli = typer.Typer(add_completion=False, help="Q-Mol — molecular descriptor CLI")


@cli.command()
def compute(smiles: List[str]):
    """Compute descriptors for one or more SMILES strings."""
    for i, smi in enumerate(smiles):
        r = qcompute.compute_molecule(cid=-(i + 1), smiles=smi)
        if not r.success:
            typer.echo(f"FAIL {smi}: {r.error}")
            continue
        typer.echo(
            f"{smi}\tMW={r.mw:.2f}\tlogP={r.logp:.2f}\tQED={r.qed:.3f}\t"
            f"Lipinski={r.lipinski_pass}\tPAINS={r.pains_hit}"
        )


@cli.command()
def screen(smiles: List[str]):
    """Run drug-likeness filters (Lipinski/Veber/PAINS/etc.)."""
    report = qscreen.screen_batch(list(smiles))
    s = report["summary"]
    typer.echo(f"n={s['n']} pass={s['passed']} review={s['review']} "
               f"reject={s['rejected']} pains={s['pains_hits']}")
    for r in report["results"]:
        typer.echo(f"  {r['verdict']:<7} {r['smiles']}  flags={','.join(r['flags']) or '-'}")


@cli.command()
def predict(smiles: List[str]):
    """ADMET predictions: logS, BBB, hERG, GI, SA."""
    for r in qpredict.predict_batch(list(smiles)):
        typer.echo(
            f"{r['smiles']}  logS={r['aqueous_logs']:+.2f}  "
            f"BBB={r['bbb_probability']:.2f}  hERG={r['herg_risk']}  "
            f"GI={r['gi_absorption']}  SA={r['sa_score_lite']}"
        )


@cli.command()
def similarity(query: str,
               top_k: int = typer.Option(10, "--top-k", "-k"),
               db: Path = typer.Option(None, "--db", help="SQLite path")):
    """Tanimoto search over the local dataset."""
    path = db or config.DB_PATH
    if not Path(path).exists():
        typer.echo(f"No dataset at {path}. Run the worker first.", err=True)
        raise typer.Exit(1)
    conn = storage.connect(Path(path))
    hits = qsimilarity.search(conn, query, top_k=top_k, min_similarity=0.0)
    conn.close()
    for h in hits:
        typer.echo(f"  sim={h.similarity:.3f}  cid={h.cid}  {h.smiles}")


@cli.command()
def conformer(smiles: str,
              out: Path = typer.Option(Path("conformer.sdf"), "--out", "-o"),
              n: int = typer.Option(10, "--n-conformers")):
    """Generate the lowest-energy 3D conformer and write SDF."""
    c = qconformers.generate(smiles, n_conformers=n)
    out.write_text(c.sdf)
    typer.echo(f"Energy {c.energy_kcal_mol:.3f} kcal/mol  atoms={len(c.coords)}  -> {out}")


@cli.command("compute-file")
def compute_file(
    path: Path,
    out: Path = typer.Option(Path("descriptors.csv"), "--out", "-o"),
    smiles_col: str = typer.Option("smiles"),
):
    """Compute descriptors for every SMILES in a CSV file."""
    if not path.exists():
        typer.echo(f"not found: {path}", err=True)
        raise typer.Exit(1)

    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        if smiles_col not in (reader.fieldnames or []):
            typer.echo(f"column {smiles_col!r} not found in {path}", err=True)
            raise typer.Exit(1)
        rows = [r[smiles_col] for r in reader]

    typer.echo(f"Computing {len(rows):,} molecules...")
    results = []
    for i, smi in enumerate(rows):
        r = qcompute.compute_molecule(cid=-(i + 1), smiles=smi)
        results.append(r.to_dict())
        if (i + 1) % 100 == 0:
            typer.echo(f"  {i + 1}/{len(rows)}")

    import pandas as pd
    df = pd.DataFrame(results)
    if out.suffix == ".parquet":
        df.to_parquet(out, index=False)
    else:
        df.to_csv(out, index=False)
    typer.echo(f"Wrote {len(df):,} rows -> {out}")


@cli.command()
def fingerprint(smiles: List[str],
                kind: str = typer.Option("morgan", "--kind", "-k",
                                         help="morgan|rdkit|atompair|torsion|maccs"),
                bits: int = typer.Option(2048, "--bits"),
                radius: int = typer.Option(2, "--radius")):
    """Compute molecular fingerprints; prints width + on-bit count per molecule."""
    for smi in smiles:
        try:
            fp = qfingerprints.compute_one(smi, kind=kind, n_bits=bits, radius=radius)
        except ValueError as e:
            typer.echo(f"FAIL {smi}: {e}")
            continue
        typer.echo(f"{smi}\t{fp.kind}\tn_bits={fp.n_bits}\ton_bits={fp.n_on_bits}")


@cli.command()
def tautomers(smiles: List[str],
              max_tautomers: int = typer.Option(100, "--max")):
    """Enumerate tautomers and print the canonical form for each molecule."""
    for smi in smiles:
        try:
            r = qtautomers.enumerate_one(smi, max_tautomers=max_tautomers)
        except ValueError as e:
            typer.echo(f"FAIL {smi}: {e}")
            continue
        typer.echo(f"{smi}  canonical={r.canonical}  n={r.n_tautomers}")
        for t in r.tautomers:
            typer.echo(f"    {t}")


@cli.command()
def cluster(smiles: List[str],
            cutoff: float = typer.Option(0.4, "--cutoff", "-c",
                                         help="Tanimoto DISTANCE cutoff (1 - similarity)")):
    """Butina-cluster molecules by ECFP4 distance; prints each cluster centroid."""
    try:
        res = qclustering.cluster(list(smiles), cutoff=cutoff)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    typer.echo(f"{res.n_valid} molecules -> {res.n_clusters} clusters (cutoff={cutoff})")
    for c in res.clusters:
        typer.echo(f"  cluster {c['cluster_id']} (n={c['size']}) "
                   f"centroid={c['centroid']}")


@cli.command()
def formula(smiles: List[str]):
    """Molecular formula, exact + average mass, and RDBE per molecule."""
    for smi in smiles:
        try:
            f = qformula.compute_one(smi)
        except ValueError as e:
            typer.echo(f"FAIL {smi}: {e}")
            continue
        typer.echo(f"{smi}\t{f.formula}\texact={f.exact_mass:.4f}\t"
                   f"avg={f.average_mass:.3f}\tRDBE={f.rdbe:g}")


@cli.command()
def convert(smiles: List[str],
            input_format: str = typer.Option("smiles", "--from",
                                             help="input format: smiles|inchi")):
    """Convert to canonical SMILES + InChIKey (tab-separated)."""
    for v in smiles:
        try:
            c = qconvert.convert_one(v, input_format=input_format)
        except ValueError as e:
            typer.echo(f"FAIL {v}: {e}")
            continue
        typer.echo(f"{c.canonical_smiles}\t{c.inchikey}")


@cli.command()
def descriptors(smiles: List[str],
                names: str = typer.Option("", "--names",
                                          help="comma-separated subset")):
    """Full RDKit 2D descriptor panel, or a --names subset."""
    sel = [n.strip() for n in names.split(",") if n.strip()] or None
    for smi in smiles:
        try:
            r = qdescriptors.compute_one(smi, names=sel)
        except ValueError as e:
            typer.echo(f"FAIL {smi}: {e}")
            continue
        d = r["descriptors"]
        if sel:
            typer.echo(f"{smi}  " + "  ".join(f"{k}={d[k]}" for k in sel))
        else:
            typer.echo(f"{smi}  n_descriptors={len(d)}  (use --names to filter)")


@cli.command()
def version():
    """Print package version."""
    typer.echo("qmol 1.0.0")


def main():
    cli()


if __name__ == "__main__":
    main()
