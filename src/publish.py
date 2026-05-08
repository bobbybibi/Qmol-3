"""Auto-upload the Parquet snapshot to HuggingFace Datasets."""
from __future__ import annotations
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def publish_to_hf(parquet_path: Path, repo_id: str, token: str, private: bool = True) -> bool:
    if not token or not repo_id:
        log.warning("HF_TOKEN or HF_REPO_ID not set — skipping upload")
        return False
    try:
        from huggingface_hub import HfApi, create_repo
    except ImportError:
        log.error("huggingface_hub not installed")
        return False

    api = HfApi(token=token)
    try:
        create_repo(repo_id, repo_type="dataset", private=private, token=token, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        log.info("create_repo: %s", e)

    try:
        api.upload_file(
            path_or_fileobj=str(parquet_path),
            path_in_repo="qmol.parquet",
            repo_id=repo_id,
            repo_type="dataset",
            token=token,
            commit_message="Update Q-Mol dataset snapshot",
        )
        log.info("Uploaded %s to HF dataset %s", parquet_path.name, repo_id)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("HF upload failed: %s", e)
        return False


def write_dataset_card(parquet_path: Path, repo_id: str, token: str, stats: dict) -> None:
    """Publish a README.md to the HF dataset repo with stats + sales pitch."""
    if not token or not repo_id:
        return
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return
    md = _dataset_card_md(stats)
    tmp = parquet_path.parent / "README.md"
    tmp.write_text(md, encoding="utf-8")
    try:
        HfApi(token=token).upload_file(
            path_or_fileobj=str(tmp),
            path_in_repo="README.md",
            repo_id=repo_id,
            repo_type="dataset",
            token=token,
            commit_message="Update dataset card",
        )
    except Exception as e:  # noqa: BLE001
        log.error("README upload failed: %s", e)


def _dataset_card_md(stats: dict) -> str:
    n = stats.get("row_count", 0)
    methods = stats.get("methods", {})
    return f"""---
license: cc-by-nc-4.0
tags:
- chemistry
- quantum
- vqe
- molecular-properties
- drug-discovery
size_categories:
- 10K<n<100K
---

# Q-Mol Dataset

Continuously updated dataset of quantum-verified molecular properties.

**Rows:** {n}
**Methods:** {methods}

## Columns

| Column | Description |
|---|---|
| `cid` | PubChem Compound ID |
| `smiles` | Canonical SMILES |
| `method` | Compute method (VQE / CCSD / HF) |
| `basis` | Basis set (e.g. sto-3g) |
| `num_atoms`, `num_heavy_atoms`, `num_electrons`, `num_qubits` | Molecule size |
| `energy_hartree` | Total electronic energy |
| `homo_hartree`, `lumo_hartree` | Frontier orbital energies |
| `dipole_debye` | Dipole moment magnitude |
| `mw` | Molecular weight |
| `runtime_seconds` | Compute time |

## License

CC BY-NC 4.0 — free for research. Commercial use: contact for license.

## Commercial access

For bulk downloads, custom columns, weekly updates, or commercial licensing:
open an issue on this repo or contact via HF profile.
"""
