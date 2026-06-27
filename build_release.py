"""Build a sellable release bundle from the current SQLite DB.

Outputs (to ./release/):
  qmol_full.parquet    - full dataset, compressed
  qmol_full.csv        - full dataset, CSV for non-technical buyers
  qmol_sample_100.csv  - free sample/preview (first 100 rows)
  STATS.md             - row counts, descriptor coverage, license summary
  LICENSE.txt          - CC BY-NC 4.0 for free tier
  LICENSE_COMMERCIAL.txt - commercial license template

Run: python build_release.py
Upload qmol_full.parquet + qmol_full.csv to Gumroad as the paid product.
Upload qmol_sample_100.csv as the free sample / lead magnet.
"""
from __future__ import annotations
import os
from pathlib import Path
import shutil

import config
from src import storage

RELEASE_DIR = Path("release")
RELEASE_DIR.mkdir(exist_ok=True)


def main() -> None:
    conn = storage.connect(config.DB_PATH)
    n = storage.row_count(conn)
    print(f"Rows available: {n}")
    if n == 0:
        print("No data yet. Run worker.py first.")
        return

    pq = RELEASE_DIR / "qmol_full.parquet"
    csv = RELEASE_DIR / "qmol_full.csv"
    sample = RELEASE_DIR / "qmol_sample_100.csv"
    sdf = RELEASE_DIR / "qmol_full.sdf"
    jsonl = RELEASE_DIR / "qmol_full.jsonl"

    storage.export_parquet(conn, pq)
    storage.export_csv(conn, csv)
    storage.export_sample(conn, sample, n=100)

    try:
        from src import exports
        exports.export_sdf(conn, sdf)
        exports.export_jsonl(conn, jsonl)
    except Exception as e:  # noqa: BLE001
        print(f"[release] SDF/JSONL failed (non-fatal): {e}")

    (RELEASE_DIR / "LICENSE.txt").write_text(
        "Creative Commons Attribution-NonCommercial 4.0 (CC BY-NC 4.0)\n"
        "https://creativecommons.org/licenses/by-nc/4.0/\n\n"
        "You may use this dataset for research and non-commercial purposes "
        "with attribution. For commercial use, see LICENSE_COMMERCIAL.txt.\n"
    )
    (RELEASE_DIR / "LICENSE_COMMERCIAL.txt").write_text(
        "Q-Mol Commercial License\n"
        "========================\n\n"
        "Purchase of this product grants the buyer a perpetual, non-transferable "
        "license to use the dataset in commercial products (ML training, "
        "screening pipelines, internal R&D). Redistribution of the raw dataset "
        "is not permitted.\n\n"
        "Contact: <" + os.getenv("QMOL_CONTACT_EMAIL", "hi@qmol.app") + "> for enterprise/redistribution terms.\n"
    )

    pq_mb = pq.stat().st_size / 1024 / 1024
    csv_mb = csv.stat().st_size / 1024 / 1024
    (RELEASE_DIR / "STATS.md").write_text(
        f"# Q-Mol Dataset Release\n\n"
        f"- **Molecules:** {n:,}\n"
        f"- **Parquet size:** {pq_mb:.2f} MB\n"
        f"- **CSV size:** {csv_mb:.2f} MB\n"
        f"- **Source:** PubChem (public domain structures)\n"
        f"- **Descriptors:** MW, logP, TPSA, HBD, HBA, rotatable bonds, "
        f"ring count, aromatic rings, QED, ECFP4 fingerprint hash\n"
        f"- **Format:** Parquet (primary) + CSV (compatibility)\n"
        f"- **License (free tier):** CC BY-NC 4.0\n"
        f"- **License (commercial):** Per-seat, see LICENSE_COMMERCIAL.txt\n\n"
        f"## Use cases\n"
        f"- ML featurization for QSAR / ADMET\n"
        f"- Virtual screening pre-filters\n"
        f"- Drug-likeness scoring datasets\n"
        f"- Teaching / reproducible benchmarks\n"
    )

    print(f"\nBuilt release in {RELEASE_DIR.resolve()}")
    for f in sorted(RELEASE_DIR.iterdir()):
        print(f"  {f.name:30s} {f.stat().st_size:>12,} bytes")


if __name__ == "__main__":
    main()
