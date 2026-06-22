# Q-Mol Dataset Factory

Autonomous worker that continuously builds a quantum-verified molecular
properties dataset and auto-publishes it to HuggingFace. Runs 24/7 on
Windows with zero babysitting.

## Two products in this repo

Q-Mol ships two things on one RDKit compute core (`src/compute.py`):

- **Dataset factory** (`worker.py`) — the 24/7 ingest → compute → store →
  publish loop described below.
- **Molecular-informatics API + CLI** (`api.py`, `cli.py`) — a key-gated
  FastAPI service (~50 endpoints: descriptors, full QSAR panel, fingerprints,
  similarity + pairwise matrix, Butina clustering, drug-likeness screening,
  ADMET heuristics, formula/exact-mass, identifier conversion, tautomers,
  conformers, reactions, scaffolds, diversity, async jobs, …) plus a local Typer
  CLI. Run `uvicorn api:app` and open `/docs`, or `qmol --help`.
  **Quickstart: [`docs/API.md`](docs/API.md)** · architecture tour: **`CLAUDE.md`**.

## What it does

1. **Ingests** SMILES from PubChem (public, free).
2. **Computes** molecular properties:
   - PySCF HF/CCSD (primary, reliable)
   - pyQPanda VQE hook available (upgrade path)
   - Returns: ground-state energy, HOMO/LUMO, dipole moment, geometry metadata.
3. **Stores** results in SQLite + exports clean Parquet snapshots.
4. **Publishes** snapshots to HuggingFace Datasets (gated for paid access)
   on a schedule (every N molecules or every N hours, whichever first).

## Monetization

- **HuggingFace gated dataset** — paid access tier, instant payouts
- **Gumroad CSV sales** — one-time purchases ($29–$199)
- **AWS Data Exchange** — list when you have >10k rows (enterprise buyers)
- **Custom jobs** — landing page CTA for pharma "compute this molecule" asks

## Setup (Windows)

```powershell
cd c:\qua\qua
.\setup.ps1          # creates .venv and installs deps
# Edit .env:
#   HF_TOKEN=hf_...        (write-scope token from huggingface.co/settings/tokens)
#   HF_REPO_ID=you/q-mol-dataset
.\run_worker.bat     # starts the worker
```

## Run it forever (Task Scheduler)

```powershell
# Run at logon
schtasks /Create /TN "QMolWorker" /TR "c:\qua\qua\run_worker.bat" /SC ONLOGON /RL HIGHEST
```

## Config (.env)

| Var | Purpose |
|---|---|
| `HF_TOKEN` | HuggingFace write token |
| `HF_REPO_ID` | e.g. `yourname/q-mol-dataset` |
| `HF_PRIVATE` | `true` for gated/paid dataset |
| `PUBCHEM_START_CID` | starting PubChem Compound ID |
| `MAX_HEAVY_ATOMS` | skip molecules bigger than this |
| `BASIS_SET` | `sto-3g` (fast) or `6-31g` (accurate) |
| `PUBLISH_EVERY_N_MOLECULES` | snapshot trigger |
| `SNAPSHOT_EVERY_HOURS` | snapshot trigger |

## Files

- `worker.py` — main loop
- `src/ingest.py` — PubChem fetcher
- `src/compute.py` — PySCF + pyQPanda compute
- `src/storage.py` — SQLite + Parquet
- `src/publish.py` — HuggingFace uploader

## Upgrade paths

- Replace PySCF-returned energy with a real pyQPanda VQE loop in
  `src/compute.py::_run_vqe_pyqpanda` for true quantum provenance.
- Add Gumroad auto-publish (CSV snapshot -> Gumroad API).
- Add AWS Data Exchange listing once row count > 10k.