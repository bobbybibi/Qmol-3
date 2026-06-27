# Q-Mol API — quickstart

The Q-Mol API is a key-gated molecular-informatics service. Interactive docs
(Swagger) live at `/docs`; the raw spec is `/openapi-static.json`. This page is
a copy-paste quickstart for the most-used endpoints.

Base URL (hosted): `https://qua-22p1.onrender.com` — or run locally with
`uvicorn api:app`.

## 1. Get a free API key

```bash
curl -s -X POST "$BASE/signup" \
  -H 'content-type: application/json' \
  -d '{"email":"you@example.com"}'
# -> {"api_key":"qmol_...", "tier":"free", "monthly_quota":500, ...}
```

Save the key. Send it as the `x-api-key` header on every paid endpoint. Check
remaining quota any time:

```bash
curl -s "$BASE/usage" -H "x-api-key: $KEY"
```

Most endpoints meter usage against your monthly SMILES quota; the per-call
"charge" is noted below. Pricing/plans: `GET /plans`.

## 2. Descriptors & properties

```bash
# ~20 medchem descriptors (free tier, no key needed; max 500/call)
curl -s -X POST "$BASE/compute" \
  -H 'content-type: application/json' \
  -d '{"smiles":["CCO","c1ccccc1"]}'

# Full RDKit 2D descriptor panel (~217 features). charge: 2/mol
curl -s -X POST "$BASE/descriptors" -H "x-api-key: $KEY" \
  -H 'content-type: application/json' \
  -d '{"smiles":["CCO"], "names":["MolWt","TPSA","qed"]}'   # omit names for all
curl -s "$BASE/descriptors/names"        # list every available descriptor

# Formula, exact (monoisotopic) + average mass, composition, RDBE. charge: 1/mol
curl -s -X POST "$BASE/formula" -H "x-api-key: $KEY" \
  -H 'content-type: application/json' \
  -d '{"smiles":["CC(=O)Oc1ccccc1C(=O)O"]}'

# Drug-likeness screen (Lipinski/Veber/Ghose/Egan/PAINS). charge: 5/mol
curl -s -X POST "$BASE/screen" -H "x-api-key: $KEY" \
  -H 'content-type: application/json' -d '{"smiles":["CCO"]}'

# ADMET heuristics (logS/BBB/hERG/GI/SA). charge: 3/mol
curl -s -X POST "$BASE/predict" -H "x-api-key: $KEY" \
  -H 'content-type: application/json' -d '{"smiles":["CCO"]}'
```

## 3. Fingerprints, similarity, clustering

```bash
# Fingerprints: morgan|rdkit|atompair|torsion|maccs. charge: 1/mol
curl -s -X POST "$BASE/fingerprints" -H "x-api-key: $KEY" \
  -H 'content-type: application/json' \
  -d '{"smiles":["CCO"], "kind":"morgan", "n_bits":2048, "output":"both"}'

# Pairwise Tanimoto matrix among your SMILES (2..500). charge: 1/mol
curl -s -X POST "$BASE/similarity/matrix" -H "x-api-key: $KEY" \
  -H 'content-type: application/json' \
  -d '{"smiles":["CCO","CCN","c1ccccc1"]}'

# Butina clustering; cutoff is DISTANCE (1 - similarity). charge: 1/mol
curl -s -X POST "$BASE/cluster" -H "x-api-key: $KEY" \
  -H 'content-type: application/json' \
  -d '{"smiles":["CCO","CCO","c1ccccc1"], "cutoff":0.3}'

# Tanimoto search over the public dataset. charge: flat 100
curl -s -X POST "$BASE/similarity" -H "x-api-key: $KEY" \
  -H 'content-type: application/json' \
  -d '{"smiles":"CCO", "top_k":10}'
```

## 4. Standardize / convert / tautomers

```bash
# Canonical SMILES + InChI + InChIKey (+ optional molblock). charge: 1/mol
curl -s -X POST "$BASE/convert" -H "x-api-key: $KEY" \
  -H 'content-type: application/json' \
  -d '{"smiles":["C1=CC=CC=C1"]}'

# Enumerate tautomers + canonical form. charge: 2/mol
curl -s -X POST "$BASE/tautomers" -H "x-api-key: $KEY" \
  -H 'content-type: application/json' -d '{"smiles":["O=C1CCCCC1"]}'

# Salt-strip + neutralize + canonical tautomer. charge: 1/mol
curl -s -X POST "$BASE/standardize" -H "x-api-key: $KEY" \
  -H 'content-type: application/json' -d '{"smiles":["CC(=O)[O-].[Na+]"]}'
```

## 5. Large batches (async jobs)

```bash
JOB=$(curl -s -X POST "$BASE/jobs" -H "x-api-key: $KEY" \
  -H 'content-type: application/json' -d '{"smiles":["CCO","c1ccccc1"]}' \
  | python -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
curl -s "$BASE/jobs/$JOB" -H "x-api-key: $KEY"             # poll status
curl -s "$BASE/jobs/$JOB/result" -H "x-api-key: $KEY"      # download JSONL when done
```

## Same thing locally — the CLI

```bash
pip install -e .
qmol compute "CCO" "c1ccccc1"
qmol descriptors CCO --names MolWt,TPSA,qed
qmol fingerprint CCO --kind maccs
qmol formula "CC(=O)Oc1ccccc1C(=O)O"
qmol convert c1ccccc1
qmol tautomers "O=C1CCCCC1"
qmol cluster CCO CCO c1ccccc1 --cutoff 0.3
qmol screen CCO ; qmol predict CCO
```

## Notes

- **Scopes**: a key can be restricted to specific endpoints — see `GET/PUT /key/scopes`.
- **Teams**: members share one quota pool (`effective_quota`); admin manages via `/teams`.
- **Errors**: `401` missing/invalid key · `402` quota exceeded · `403` out of scope ·
  `400` bad input (e.g. unparseable SMILES) · `429` rate-limited (see `Retry-After`).
- Invalid SMILES in a batch are reported (by index or a per-row error) rather than
  failing the whole request, except where the endpoint computes a joint result.
