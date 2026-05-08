"""Auto-publish the latest release Parquet to Kaggle Datasets.

Requires `kaggle` package and credentials:
    pip install kaggle
    set KAGGLE_USERNAME=your-username
    set KAGGLE_KEY=your-api-key
or place ~/.kaggle/kaggle.json with both fields.

First run creates the dataset; subsequent runs version-bump it.

Usage:
    python -m src.kaggle_publish              # uses release/qmol_full.parquet
    python -m src.kaggle_publish path/to.parquet
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

DATASET_SLUG_DEFAULT = "qmol-molecular-descriptors"


def publish_to_kaggle(parquet_path: Path, slug: str | None = None,
                      title: str = "Q-Mol — Molecular Descriptors") -> bool:
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        print("[kaggle] package not installed. pip install kaggle")
        return False

    user = os.getenv("KAGGLE_USERNAME")
    if not user:
        print("[kaggle] KAGGLE_USERNAME not set; skipping")
        return False

    slug = slug or os.getenv("KAGGLE_DATASET_SLUG", DATASET_SLUG_DEFAULT)
    full_id = f"{user}/{slug}"

    staging = parquet_path.parent / "kaggle_stage"
    staging.mkdir(exist_ok=True)
    target = staging / parquet_path.name
    target.write_bytes(parquet_path.read_bytes())

    meta = {
        "title": title,
        "id": full_id,
        "licenses": [{"name": "CC-BY-NC-SA-4.0"}],
        "resources": [
            {"path": parquet_path.name,
             "description": "RDKit descriptors for PubChem molecules"}
        ],
    }
    (staging / "dataset-metadata.json").write_text(json.dumps(meta, indent=2))

    api = KaggleApi()
    api.authenticate()

    try:
        api.dataset_status(full_id)
        exists = True
    except Exception:
        exists = False

    if exists:
        print(f"[kaggle] versioning {full_id}")
        api.dataset_create_version(
            folder=str(staging),
            version_notes="Automated update",
            quiet=False,
        )
    else:
        print(f"[kaggle] creating {full_id}")
        api.dataset_create_new(
            folder=str(staging),
            public=True,
            quiet=False,
        )
    return True


if __name__ == "__main__":
    pq = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("release/qmol_full.parquet")
    if not pq.exists():
        print(f"Not found: {pq}. Run build_release.py first.")
        sys.exit(1)
    ok = publish_to_kaggle(pq)
    sys.exit(0 if ok else 1)
