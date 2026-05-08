"""Demo: load Q-Mol, filter drug-like molecules, build a tiny QSAR baseline.

Run: python demo.py
Produces: demo_output.png (scatter plot) + prints summary stats.
Designed as both a buyer-facing example AND a sanity check.
"""
from __future__ import annotations
from pathlib import Path

import pandas as pd

PARQUET = Path("release/qmol_full.parquet")
if not PARQUET.exists():
    PARQUET = Path("data/qmol.parquet")

print(f"Loading {PARQUET} ...")
df = pd.read_parquet(PARQUET)
print(f"Rows: {len(df):,}   Columns: {len(df.columns)}")
print()

print("=== Descriptor coverage ===")
print(df[["mw", "logp", "tpsa", "qed", "fsp3"]].describe().round(3))
print()

print("=== Drug-likeness filtering ===")
druglike = df[(df["lipinski_pass"] == 1) & (df["veber_pass"] == 1) & (df["pains_hit"] == 0)]
print(f"Molecules passing Lipinski + Veber + not PAINS: {len(druglike):,} / {len(df):,}")
print()

print("=== Top 10 by QED ===")
cols = ["cid", "smiles", "mw", "logp", "qed", "lipinski_pass"]
print(df.nlargest(10, "qed")[cols].to_string(index=False))
print()

print("=== Scaffold diversity ===")
uniq_scaffolds = df["murcko_scaffold"].dropna().nunique()
print(f"Unique Murcko scaffolds: {uniq_scaffolds:,}")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 5))
    sc = ax.scatter(df["mw"], df["logp"], c=df["qed"], cmap="viridis",
                    s=8, alpha=0.7)
    ax.set_xlabel("MW (Da)")
    ax.set_ylabel("logP")
    ax.set_title("Q-Mol: chemical space coloured by QED")
    plt.colorbar(sc, label="QED")
    fig.tight_layout()
    fig.savefig("demo_output.png", dpi=120)
    print("\nSaved demo_output.png")
except ImportError:
    print("\n(install matplotlib for the scatter plot)")
