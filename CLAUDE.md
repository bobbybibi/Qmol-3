# CLAUDE.md — Q-Mol orientation

Guidance for working in this repo. Read this first; it captures the parts that
aren't obvious from any single file.

## What this is

Q-Mol is **two products sharing one RDKit compute core**:

1. **Dataset factory** (`worker.py`) — a 24/7 loop: ingest molecules from
   PubChem → compute properties → store in SQLite/Parquet → auto-publish to
   HuggingFace / Kaggle / Gumroad.
2. **Molecular-informatics SaaS API** (`api.py`) — a key-gated FastAPI service
   (~30 endpoints) with quotas, billing, teams, async jobs, webhooks, and audit.

The science is **RDKit descriptors** (always available). PySCF (quantum
chemistry) is an *optional* tier that auto-engages only if installed; pyQPanda
VQE is an unimplemented upgrade hook. The "quantum-verified" branding is
aspirational — the shipping compute path is classical RDKit + optional PySCF HF/CCSD.

## Repo map

| Path | Role |
|---|---|
| `api.py` | FastAPI app — every customer endpoint. The center of gravity (~1.2k lines). |
| `worker.py` | Dataset-factory loop (ingest→compute→store→publish). |
| `cli.py` | Local Typer CLI (`qmol compute/screen/predict/similarity/conformer`). |
| `config.py` | Env-driven config (loads `.env`); defines `data/` paths. |
| `src/compute.py` | **The shared core.** `compute_molecule(smiles) -> ComputeResult`. |
| `src/ingest.py` | PubChem fetcher (`iter_cids`, `fetch_cid`). |
| `src/storage.py` | SQLite schema + Parquet/CSV export for the factory dataset. |
| `src/keys.py` | API keys + per-month usage (SQLite at `data/keys.sqlite`). |
| `src/*.py` | One module per feature/endpoint (see "Module groups" below). |
| `stripe_webhook.py` | On payment → `keys.provision()` + email the key (Mailgun). |
| `landing/*.html` | Static marketing/docs/dashboard/checkout pages. |
| `tests/` | 15 pytest files covering the SaaS surface. |
| `render.yaml` / `Dockerfile` | Deploy: a Render worker + a Render web service. |

### Module groups in `src/`
- **Science:** `compute`, `descriptors` (full RDKit 2D panel), `predict`
  (ADMET heuristics), `screen` (drug-likeness), `formula` (mass/composition),
  `convert` (SMILES/InChI/InChIKey), `similarity` (Tanimoto search),
  `simmatrix` (pairwise Tanimoto matrix), `clustering` (Butina),
  `fingerprints` (ECFP/MACCS/…), `tautomers`, `conformers`, `reactions`,
  `substructure`, `diversity`, `scaffolds`, `retro`, `standardize`, `sdf_out`,
  `parquet_out`, `exporters`.
- **Billing/accounts:** `keys`, `teams`, `plans`, `coupons`, `invoices`,
  `referrals`, `rotate`, `magic_link`, `scopes`.
- **Ops:** `ratelimit`, `cache`, `audit`, `status_store`, `metrics`, `prom`,
  `usage_stats`, `jobs` (async), `webhooks_out`, `uploads`.
- **Publishing (factory):** `publish` (HF), `kaggle_publish`, `gumroad_publish`.

## The compute core — read `src/compute.py` before touching science code

`compute_molecule(cid, smiles, basis, ...)` runs a 3-tier ladder and returns a
flat `ComputeResult` dataclass (`.to_dict()` → the row shape used everywhere):

1. **RDKit descriptors** (always): MW, logP, TPSA, HBD/HBA, rotatable bonds, QED,
   ring counts, ECFP4 hash, InChIKey, Murcko scaffold, fsp3, Lipinski/Veber pass,
   PAINS hit.
2. **PySCF HF/CCSD** (if `HAS_PYSCF`): embeds 3D geometry, returns energy,
   HOMO/LUMO, dipole. Upgrades HF→CCSD when `nao <= 60`.
3. **pyQPanda VQE** (hook only, not implemented).

Failures degrade gracefully: invalid SMILES → `success=False` with an `error`;
missing PySCF → RDKit-only result. The `ComputeResult` field list, the
`storage.py` `SCHEMA`, and `storage.upsert()` `cols` must stay in sync.

## Request lifecycle (trace: `POST /compute/premium`)

1. **Two HTTP middlewares run first** (`api.py`):
   `_uptime_middleware` records latency/up-down into `status_store` + `audit`;
   `_scope_middleware` enforces per-key endpoint allowlists via `scopes.allowed()`.
2. **Rate limit:** `_rl("paid:<key>", 600, 60s)` → `ratelimit.check()`, an
   in-memory rolling-window token bucket (per-process; swap for Redis if scaled).
3. **Auth:** env-var keys in `QMOL_API_KEYS` bypass the DB (admin bootstrap);
   otherwise `keys.lookup(key)` must return an active `KeyInfo`.
4. **Quota:** `keys.month_usage(key)` vs `info.monthly_quota`. (Endpoints that
   support team pools use `teams.effective_quota(key)` instead — it routes the
   check through the shared team quota when the key is a team member.)
5. **Compute:** `_run()` maps each SMILES through `cache.memoize("compute", smi, …)`
   — the cache key is the **InChIKey**, so tautomer/duplicate SMILES are cache hits.
6. **Meter:** `keys.record(key, "/compute/premium", n)` writes a `usage` row.
   This is what later quota checks, invoices, and `/usage` read back.

Most endpoints follow this same shape: rate-limit → lookup → quota → do work →
`keys.record()`. The "charge" varies per endpoint (e.g. `/predict` charges 3×,
`/screen` 5×, `/similarity` a flat 100, `/react` 1 per product, `/tautomers` 2×,
and `/fingerprints` `/similarity/matrix` `/cluster` 1 per input molecule).
Newer per-molecule endpoints route the quota check through
`teams.effective_quota()` so team pools work; add new scopes to
`scopes.KNOWN_SCOPES` and regenerate `landing/openapi.json`
(`python scripts/dump_openapi.py`) when adding an endpoint.

## Worker publish pipeline (`worker.py::publish_snapshot`)

Triggered every `PUBLISH_EVERY_N_MOLECULES` (default 100) or
`SNAPSHOT_EVERY_HOURS` (default 6):
1. `storage.export_parquet()` → `data/qmol.parquet` (success rows only).
2. `publish.publish_to_hf()` + `write_dataset_card()` (no-op without `HF_TOKEN`).
3. `build_release.main()` → `release/qmol_full.{parquet,csv}` + sample.
4. `kaggle_publish` + `gumroad_publish` (no-ops without creds).
5. `metrics.snapshot()` for the admin dashboard trend chart.

The main loop also **dedups** by InChIKey and skips molecules with
`> MAX_HEAVY_ATOMS`. Resume state lives in `data/state.json` (`next_cid`).

## Data stores (all SQLite under `data/`, created on demand)

| File | Owner | Contents |
|---|---|---|
| `data/qmol.sqlite` | `storage.py` | factory dataset (`molecules` table). |
| `data/keys.sqlite` | `keys.py` (+ `teams`, others piggyback) | `api_keys`, `usage`, `teams`, `team_members`. |
| `data/jobs.sqlite` + `data/jobs/` | `jobs.py` | async job rows + input/result files. |
| `data/state.json` | worker | ingest resume cursor. |

Note: most billing modules call `keys._connect()` and add their own tables to
`keys.sqlite` (e.g. `teams`, `scopes`, `referrals`). Each call opens/closes its
own connection — fine at current scale, the obvious first bottleneck if scaled.

## Running it

```bash
# Deps (the test/runtime set):
pip install -r requirements.txt
pip install "fastapi>=0.110" "uvicorn>=0.27" "email-validator>=2" python-multipart pytest

# API (local):
QMOL_ADMIN_TOKEN=dev uvicorn api:app --reload          # http://127.0.0.1:8000/docs

# CLI:
pip install -e . && qmol compute "CCO" "c1ccccc1"

# Worker (needs PubChem network + optionally HF creds in .env):
python worker.py

# Tests (CI sets QMOL_ADMIN_TOKEN=test-admin):
QMOL_ADMIN_TOKEN=test-admin pytest -q
```

CI (`.github/workflows/ci.yml`): pytest → dump OpenAPI → docker build → smoke
`/health`. `scripts/dump_openapi.py` regenerates `landing/openapi.json`.

## Conventions & gotchas

- **Env config only** — no config files beyond `.env`. See `config.py` and the
  `os.getenv` calls in `keys.py`, `api.py`, `stripe_webhook.py`.
- **Quota math is centralized in `keys.record`/`month_usage`** (calendar-month
  window via `datetime('now','start of month')`). Don't invent parallel meters.
- **Charges are per-endpoint multipliers** — keep them consistent with the
  docstring on each route and with `tests/`.
- **Admin endpoints** require the `x-admin-token` header == `QMOL_ADMIN_TOKEN`
  env (via `_require_admin`). With no env set, admin routes 401.
- **Dead code exists** in `api.py` (unreachable block after the `return` in
  `/predict`, ~lines 457–464) — leftover from fast iteration; safe to remove.
- **The README describes only the factory**; the SaaS API (the larger half) is
  undocumented there. `pyproject.toml`'s description ("RDKit QSAR featurizer")
  is the honest core.
- **Tests can be slow** — many call real RDKit 3D embedding/MMFF; a couple touch
  PubChem-shaped paths. Prefer running a single file while iterating.
</content>
