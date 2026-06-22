"""FastAPI server: paid endpoint to compute descriptors for a buyer's SMILES list.

Run locally:
    pip install fastapi uvicorn
    uvicorn api:app --host 0.0.0.0 --port 8000

Endpoints:
    GET  /                    health + row count of public DB
    POST /compute             batch compute (max 500 SMILES/call, free tier)
    POST /compute/premium     batch compute (max 50k, requires API key)

Deploy: render.com web service or fly.io. Reuses the same Docker image.
"""
from __future__ import annotations
import os
import hashlib
from pathlib import Path
from typing import List

from fastapi import FastAPI, Header, HTTPException, Request, UploadFile, File
from fastapi.responses import PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

from src import (compute, storage, keys as keysdb, ratelimit, similarity,
                 metrics, jobs, referrals, screen, predict, status_store,
                 coupons, magic_link, conformers, reactions, standardize,
                 webhooks_out, teams, prom, scaffolds, audit, rotate as rotatelib,
                 invoices, uploads, substructure, exporters,
                 cache as result_cache, diversity, sdf_out,
                 parquet_out, usage_stats, scopes, retro, plans, fingerprints,
                 simmatrix, tautomers, clustering, formula, descriptors)
import config

ADMIN_TOKEN = os.getenv("QMOL_ADMIN_TOKEN", "")

app = FastAPI(
    title="Q-Mol API",
    version="1.2.0",
    description=(
        "Molecular descriptor, similarity search, drug-likeness screen, "
        "and ADMET prediction API.\n\n"
        "Get a free key: `POST /signup`. Upgrade: https://qmol.app/checkout.html\n\n"
        "Postman collection: [qmol-postman.json](/qmol-postman.json)"
    ),
    contact={"name": "Q-Mol support", "email": "hi@qmol.app"},
    license_info={"name": "MIT (free tier) / Commercial (paid tiers)"},
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _uptime_middleware(request: Request, call_next):
    import time as _t
    t0 = _t.time()
    try:
        resp = await call_next(request)
        ok = resp.status_code < 500
        elapsed_ms = int((_t.time() - t0) * 1000)
        status_store.record(ok, elapsed_ms,
                            note=f"{request.method} {request.url.path} -> {resp.status_code}")
        # Structured audit log (fire-and-forget, swallow errors)
        try:
            from src import audit as _audit
            _audit.log_event(
                api_key=request.headers.get("x-api-key"),
                ip=request.client.host if request.client else None,
                method=request.method,
                path=request.url.path,
                status=resp.status_code,
                ms=elapsed_ms,
            )
        except Exception:
            pass
        return resp
    except Exception as e:  # noqa: BLE001
        status_store.record(False, (_t.time() - t0) * 1000,
                            note=f"{request.method} {request.url.path} -> err: {e!s:.80}")
        raise


@app.middleware("http")
async def _scope_middleware(request: Request, call_next):
    """Enforce per-key endpoint scopes (if any)."""
    key = request.headers.get("x-api-key")
    path = request.url.path
    if key and path not in ("/", "/health", "/metrics") \
            and not path.startswith(("/admin", "/badge", "/key")):
        try:
            from src import scopes as _scopes
            if not _scopes.allowed(key, path):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    {"detail": f"API key not permitted for {path}"},
                    status_code=403,
                )
        except Exception:
            pass  # never break the request path on a scope-table error
    return await call_next(request)

FREE_LIMIT = 500
PAID_LIMIT = 50_000
# Legacy env-var keys (still supported for bootstrap / admin):
API_KEYS = {
    k.strip() for k in os.getenv("QMOL_API_KEYS", "").split(",") if k.strip()
}


class ComputeIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1)




class SimilarityIn(BaseModel):
    smiles: str = Field(..., min_length=1)
    top_k: int = Field(20, ge=1, le=200)
    min_similarity: float = Field(0.3, ge=0.0, le=1.0)


class ScreenIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1, max_length=10_000)


class PredictIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1, max_length=10_000)


class ConformerIn(BaseModel):
    smiles: str = Field(..., min_length=1)
    n_conformers: int = Field(10, ge=1, le=50)


class ReactionIn(BaseModel):
    template: str
    reagents: List[List[str]] = Field(..., min_length=1)
    max_products: int = Field(10_000, ge=1, le=100_000)
    unique: bool = True


class StandardizeIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1, max_length=10_000)


class WebhookSubIn(BaseModel):
    url: str = Field(..., min_length=5)
    secret: str | None = None


class TeamCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    tier: str = Field(..., min_length=1)
    monthly_quota: int = Field(..., ge=1)
    owner_email: str | None = None


class TeamMemberIn(BaseModel):
    team_id: str
    api_key: str


class ScaffoldIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1, max_length=50_000)
    top_k: int = Field(20, ge=1, le=1_000)



class ScopesIn(BaseModel):
    scopes: List[str] = Field(..., max_length=50)


class RetroIn(BaseModel):
    smiles: str = Field(..., min_length=1)
    max_results: int = Field(20, ge=1, le=100)


class FingerprintIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1, max_length=50_000)
    kind: str = Field("morgan", min_length=1)
    n_bits: int = Field(2048, ge=64, le=8192)
    radius: int = Field(2, ge=1, le=6)
    output: str = Field("bits", min_length=1)


class SimMatrixIn(BaseModel):
    smiles: List[str] = Field(..., min_length=2, max_length=500)


class TautomerIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1, max_length=1000)
    max_tautomers: int = Field(100, ge=1, le=1000)


class ClusterIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1, max_length=2000)
    cutoff: float = Field(0.4, ge=0.0, le=1.0)


class FormulaIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1, max_length=10_000)


class DescriptorsIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1, max_length=5000)
    names: List[str] | None = Field(default=None, max_length=300)

class SubstructureIn(BaseModel):
    smarts: str = Field(..., min_length=1)
    smiles: List[str] = Field(..., min_length=1, max_length=100_000)
    max_hits: int = Field(10_000, ge=1, le=100_000)


class DiversityIn(BaseModel):
    smiles: List[str] = Field(..., min_length=2, max_length=50_000)
    k: int = Field(20, ge=1, le=10_000)
    seed: int = 42


class SdfDownloadIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1, max_length=10_000)
    with_coords: bool = False


class ParquetIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1, max_length=50_000)


class CouponCheckIn(BaseModel):
    code: str
    tier: str


class MagicLinkIn(BaseModel):
    email: EmailStr


class JobSubmitIn(BaseModel):
    smiles: List[str] = Field(..., min_length=1, max_length=200_000)


def _require_admin(x_admin_token: str | None) -> None:
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Admin token required")
class SignupIn(BaseModel):
    email: EmailStr


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rl(key: str, limit: int, window: float) -> None:
    try:
        ratelimit.check(key, limit, window)
    except ratelimit.RateLimited as e:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Retry after {e.retry_after:.1f}s",
            headers={"Retry-After": str(int(e.retry_after) + 1)},
        )


def _run(smiles_list: list[str]) -> list[dict]:
    out = []
    for i, smi in enumerate(smiles_list):
        d = result_cache.memoize(
            "compute", smi,
            lambda i=i, smi=smi: compute.compute_molecule(
                cid=-(i + 1), smiles=smi).to_dict(),
        )
        out.append(d)
    return out


@app.get("/")
def root():
    try:
        conn = storage.connect(config.DB_PATH)
        n = storage.row_count(conn)
        conn.close()
    except Exception:
        n = 0
    return {"status": "ok", "public_rows": n, "docs": "/docs"}


@app.post("/compute")
def compute_free(body: ComputeIn, request: Request):
    ip = _client_ip(request)
    _rl(f"free:{ip}", limit=60, window=60.0)  # 60 calls/min per IP
    if len(body.smiles) > FREE_LIMIT:
        raise HTTPException(
            status_code=413,
            detail=f"Free tier limit {FREE_LIMIT}. Use /compute/premium with API key.",
        )
    return {"results": _run(body.smiles)}


@app.post("/signup")
def signup(body: SignupIn, request: Request, ref: str | None = None):
    """Self-service free-tier API key. Rate-limited to 1/min per IP.

    Signing up with the same email twice returns the existing key.
    Optional ?ref=<code> credits the referrer with bonus quota.
    """
    ip = _client_ip(request)
    _rl(f"signup:{ip}", limit=1, window=60.0)
    info = keysdb.provision(str(body.email), tier="free")
    referral = None
    if ref:
        referral = referrals.credit(ref, str(body.email), "free")
    return {
        "api_key": info.key,
        "tier": info.tier,
        "monthly_quota": info.monthly_quota,
        "referral": referral,
        "note": "Save this key. To upgrade, buy a license at /checkout.html",
    }


@app.post("/compute/premium")
def compute_paid(body: ComputeIn, request: Request,
                 x_api_key: str | None = Header(default=None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")

    _rl(f"paid:{x_api_key}", limit=600, window=60.0)  # 600/min per key

    # Env-var keys bypass DB (admin bootstrap)
    if x_api_key in API_KEYS:
        if len(body.smiles) > PAID_LIMIT:
            raise HTTPException(status_code=413, detail=f"Max {PAID_LIMIT} SMILES per call")
        return {"results": _run(body.smiles)}

    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    used = keysdb.month_usage(x_api_key)
    if used + len(body.smiles) > info.monthly_quota:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly quota exceeded ({used}/{info.monthly_quota}). "
                   f"Upgrade tier at /checkout.",
        )
    if len(body.smiles) > PAID_LIMIT:
        raise HTTPException(status_code=413, detail=f"Max {PAID_LIMIT} SMILES per call")

    results = _run(body.smiles)
    keysdb.record(x_api_key, "/compute/premium", len(body.smiles))
    return {
        "results": results,
        "quota": {"used_this_month": used + len(body.smiles),
                  "monthly_quota": info.monthly_quota,
                  "tier": info.tier},
    }


@app.post("/similarity")
def similarity_search(body: SimilarityIn, request: Request,
                      x_api_key: str | None = Header(default=None)):
    """Tanimoto search over the public dataset. Paid-only product.

    Charges 100 SMILES against monthly quota per call (flat rate).
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    _rl(f"sim:{x_api_key}", limit=60, window=60.0)

    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    CHARGE = 100
    used = keysdb.month_usage(x_api_key)
    if used + CHARGE > info.monthly_quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{info.monthly_quota})")

    conn = storage.connect(config.DB_PATH)
    try:
        hits = similarity.search(conn, body.smiles, top_k=body.top_k,
                                 min_similarity=body.min_similarity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

    keysdb.record(x_api_key, "/similarity", CHARGE)
    return {"query": body.smiles, "hits": [h.to_dict() for h in hits],
            "quota_charged": CHARGE}


@app.post("/similarity/matrix")
def similarity_matrix(body: SimMatrixIn,
                      x_api_key: str | None = Header(default=None)):
    """Pairwise ECFP4 Tanimoto matrix among the supplied SMILES (2..500).

    Returns the symmetric N×N matrix plus each row's nearest neighbor — the
    primitive for clustering/dedup/SAR. Charges 1 SMILES/input molecule.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"simmatrix:{x_api_key}", limit=20, window=60.0)
    n = len(body.smiles)
    used, quota = teams.effective_quota(x_api_key)
    if used + n > quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{quota})")
    try:
        res = simmatrix.compute(body.smiles)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keysdb.record(x_api_key, "/similarity/matrix", n)
    return {**res.to_dict(), "quota_charged": n}


# ---------------- admin endpoints (token-gated) ----------------

@app.get("/admin/stats")
def admin_stats(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    try:
        conn = storage.connect(config.DB_PATH)
        n = storage.row_count(conn)
        conn.close()
    except Exception:
        n = 0
    return metrics.metrics_today(n)


@app.get("/admin/top-users")
def admin_top_users(x_admin_token: str | None = Header(default=None),
                    limit: int = 20):
    _require_admin(x_admin_token)
    c = keysdb._connect()
    rows = c.execute(
        "SELECT u.key, k.email, k.tier, SUM(u.smiles_count) AS n "
        "FROM usage u JOIN api_keys k ON k.key=u.key "
        "WHERE u.ts >= datetime('now','start of month') "
        "GROUP BY u.key ORDER BY n DESC LIMIT ?", (limit,),
    ).fetchall()
    c.close()
    return {"users": [
        {"email": r[1], "tier": r[2], "smiles_count": int(r[3] or 0)}
        for r in rows
    ]}


@app.get("/admin/history")
def admin_history(x_admin_token: str | None = Header(default=None),
                  days: int = 30):
    _require_admin(x_admin_token)
    return {"history": metrics.history(limit=days)}


@app.get("/usage")
def usage(x_api_key: str | None = Header(default=None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key")
    info = keysdb.lookup(x_api_key)
    if not info:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {
        "tier": info.tier,
        "used_this_month": keysdb.month_usage(x_api_key),
        "monthly_quota": info.monthly_quota,
        "active": info.active,
    }


@app.get("/status")
def status_page():
    """Public uptime summary (24h + 7d). No auth."""
    return {
        "24h": status_store.summary(window_seconds=24 * 3600),
        "7d": status_store.summary(window_seconds=7 * 24 * 3600),
        "recent": status_store.recent(limit=30),
    }


# ---------------- ADMET prediction ----------------

@app.post("/predict")
def predict_endpoint(body: PredictIn, x_api_key: str | None = Header(default=None)):
    """ADMET predictions: logS, BBB, hERG, GI, SA-score. Charges 3 SMILES/molecule."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    _rl(f"predict:{x_api_key}", limit=60, window=60.0)
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    charge = 3 * len(body.smiles)
    used = keysdb.month_usage(x_api_key)
    if used + charge > info.monthly_quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{info.monthly_quota})")
    try:
        results = predict.predict_batch(body.smiles)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keysdb.record(x_api_key, "/predict", charge)
    return {"results": results, "quota_charged": charge}


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------- screening report ----------------

@app.post("/screen")
def screen_endpoint(body: ScreenIn, x_api_key: str | None = Header(default=None)):
    """Drug-likeness screening. Charges 5 SMILES/molecule against quota."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    _rl(f"screen:{x_api_key}", limit=60, window=60.0)
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    charge = 5 * len(body.smiles)
    used = keysdb.month_usage(x_api_key)
    if used + charge > info.monthly_quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{info.monthly_quota})")
    report = screen.screen_batch(body.smiles)
    keysdb.record(x_api_key, "/screen", charge)
    return {**report, "quota_charged": charge}


# ---------------- molecular formula / exact mass ----------------

@app.post("/formula")
def formula_endpoint(body: FormulaIn,
                     x_api_key: str | None = Header(default=None)):
    """Molecular formula, exact (monoisotopic) + average mass, elemental
    composition, and ring/double-bond equivalents. Charges 1 SMILES/molecule."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"formula:{x_api_key}", limit=120, window=60.0)
    n = len(body.smiles)
    used, quota = teams.effective_quota(x_api_key)
    if used + n > quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{quota})")
    try:
        results = formula.compute_batch(body.smiles)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keysdb.record(x_api_key, "/formula", n)
    return {"results": results, "quota_charged": n}


# ---------------- full QSAR descriptor panel ----------------

@app.get("/descriptors/names")
def descriptor_names():
    """Public: list every available RDKit 2D descriptor name (no auth)."""
    return {"n": len(descriptors.ALL_NAMES), "names": list(descriptors.ALL_NAMES)}


@app.post("/descriptors")
def descriptors_endpoint(body: DescriptorsIn,
                         x_api_key: str | None = Header(default=None)):
    """Full RDKit 2D descriptor panel (~200 features) per molecule, or just the
    requested `names` subset. NaN/inf come back as null. Charges 2 SMILES/molecule."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"desc:{x_api_key}", limit=60, window=60.0)
    charge = 2 * len(body.smiles)
    used, quota = teams.effective_quota(x_api_key)
    if used + charge > quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{quota})")
    try:
        results = descriptors.compute_batch(body.smiles, names=body.names)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keysdb.record(x_api_key, "/descriptors", charge)
    return {"n": len(body.smiles), "results": results, "quota_charged": charge}


# ---------------- async jobs ----------------

@app.post("/jobs")
def job_submit(body: JobSubmitIn, x_api_key: str | None = Header(default=None)):
    """Submit a large batch. Returns job_id; poll /jobs/{id}."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    n = len(body.smiles)
    used = keysdb.month_usage(x_api_key)
    if used + n > info.monthly_quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{info.monthly_quota})")
    keysdb.record(x_api_key, "/jobs", n)
    job_id = jobs.submit(x_api_key, body.smiles)
    jobs.start_worker()
    return {"job_id": job_id, "status": "queued", "n_smiles": n}


@app.get("/jobs/{job_id}")
def job_status(job_id: str, x_api_key: str | None = Header(default=None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    if jobs.owner(job_id) != x_api_key:
        raise HTTPException(status_code=404, detail="Job not found")
    info = jobs.get(job_id)
    if not info:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": info.id, "status": info.status,
        "n_smiles": info.n_smiles, "n_processed": info.n_processed,
        "error": info.error,
        "result_url": f"/jobs/{info.id}/result" if info.status == "done" else None,
    }


@app.get("/jobs/{job_id}/result")
def job_result(job_id: str, x_api_key: str | None = Header(default=None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    if jobs.owner(job_id) != x_api_key:
        raise HTTPException(status_code=404, detail="Job not found")
    info = jobs.get(job_id)
    if not info or info.status != "done" or not info.result_path:
        raise HTTPException(status_code=409, detail=f"Job not ready (status={info.status if info else 'missing'})")
    from fastapi.responses import FileResponse
    return FileResponse(info.result_path, media_type="application/x-jsonlines",
                        filename=f"{job_id}.jsonl")


# ---------------- referral program ----------------

@app.get("/referral")
def referral_get(x_api_key: str | None = Header(default=None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info:
        raise HTTPException(status_code=401, detail="Invalid API key")
    code = referrals.code_for(x_api_key)
    s = referrals.stats(x_api_key)
    return {
        "code": code,
        "share_url": f"/?ref={code}",
        "total_referrals": s.total_referrals,
        "free_signups": s.free_signups,
        "paid_purchases": s.paid_purchases,
        "earned_usd": round(s.earned_cents / 100, 2),
        "bonus_smiles": s.bonus_smiles,
    }


# ---------------- 3D conformer generation ----------------

@app.post("/conformers")
def conformers_endpoint(body: ConformerIn,
                        x_api_key: str | None = Header(default=None)):
    """Generate ETKDG v3 + MMFF94s-optimized 3D conformer. Charges 10 SMILES/call."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    _rl(f"conf:{x_api_key}", limit=30, window=60.0)
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    CHARGE = 10
    used = keysdb.month_usage(x_api_key)
    if used + CHARGE > info.monthly_quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{info.monthly_quota})")
    try:
        conf = conformers.generate(body.smiles, n_conformers=body.n_conformers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keysdb.record(x_api_key, "/conformers", CHARGE)
    return {**conf.to_dict(), "quota_charged": CHARGE}


# ---------------- reaction enumeration ----------------

@app.post("/react")
def react_endpoint(body: ReactionIn,
                   x_api_key: str | None = Header(default=None)):
    """Enumerate a combinatorial library from a SMARTS template + reagents.

    Charges 1 SMILES per generated product.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    _rl(f"react:{x_api_key}", limit=30, window=60.0)
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    try:
        result = reactions.enumerate_library(
            body.template, body.reagents,
            max_products=body.max_products, unique=body.unique,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    used = keysdb.month_usage(x_api_key)
    if used + result.n_products > info.monthly_quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{info.monthly_quota})")
    keysdb.record(x_api_key, "/react", result.n_products)
    return {**result.to_dict(), "quota_charged": result.n_products}


@app.get("/react/templates")
def react_templates():
    """Public: list built-in reaction templates (no auth required)."""
    return {"templates": {k: v for k, v in reactions.TEMPLATES.items()}}


# ---------------- standardization ----------------

@app.post("/standardize")
def standardize_endpoint(body: StandardizeIn,
                         x_api_key: str | None = Header(default=None)):
    """Salt strip + charge neutralize + canonical tautomer. Charges 1 SMILES/molecule."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    _rl(f"std:{x_api_key}", limit=120, window=60.0)
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    n = len(body.smiles)
    used = keysdb.month_usage(x_api_key)
    if used + n > info.monthly_quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{info.monthly_quota})")
    try:
        results = standardize.standardize_batch(body.smiles)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keysdb.record(x_api_key, "/standardize", n)
    return {"results": results, "quota_charged": n}


# ---------------- tautomer enumeration ----------------

@app.post("/tautomers")
def tautomers_endpoint(body: TautomerIn,
                       x_api_key: str | None = Header(default=None)):
    """Enumerate a molecule's plausible tautomers + RDKit's canonical form.

    The complement of /standardize (which collapses to one form). Charges 2
    SMILES/molecule.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"taut:{x_api_key}", limit=30, window=60.0)
    charge = 2 * len(body.smiles)
    used, quota = teams.effective_quota(x_api_key)
    if used + charge > quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{quota})")
    try:
        results = tautomers.enumerate_batch(body.smiles,
                                            max_tautomers=body.max_tautomers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keysdb.record(x_api_key, "/tautomers", charge)
    return {"results": results, "quota_charged": charge}


# ---------------- outbound webhooks ----------------

@app.post("/webhooks/subscribe")
def webhook_subscribe(body: WebhookSubIn,
                      x_api_key: str | None = Header(default=None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    if not keysdb.lookup(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    sub = webhooks_out.subscribe(x_api_key, body.url, body.secret)
    return {"url": sub.url, "has_secret": bool(sub.secret)}


@app.delete("/webhooks/subscribe")
def webhook_unsubscribe(x_api_key: str | None = Header(default=None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    webhooks_out.unsubscribe(x_api_key)
    return {"unsubscribed": True}


# ---------------- team accounts ----------------

@app.post("/teams")
def team_create(body: TeamCreateIn,
                x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    t = teams.create(body.name, body.tier, body.monthly_quota, body.owner_email)
    return t.to_dict()


@app.post("/teams/members")
def team_add_member(body: TeamMemberIn,
                    x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    if teams.get(body.team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    if keysdb.lookup(body.api_key) is None:
        raise HTTPException(status_code=404, detail="API key not found")
    teams.add_member(body.team_id, body.api_key)
    return {"added": True}


@app.delete("/teams/members")
def team_remove_member(body: TeamMemberIn,
                       x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    teams.remove_member(body.team_id, body.api_key)
    return {"removed": True}


@app.get("/teams/{team_id}")
def team_get(team_id: str,
             x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    t = teams.get(team_id)
    if not t:
        raise HTTPException(status_code=404, detail="Team not found")
    used = teams.month_usage(team_id)
    return {**t.to_dict(), "used_this_month": used,
            "members": teams.members(team_id)}


# ---------------- Prometheus ----------------

@app.get("/metrics")
def prometheus_metrics():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(prom.render(),
                             media_type="text/plain; version=0.0.4")


# ---------------- scaffold analysis ----------------

@app.post("/scaffolds")
def scaffolds_endpoint(body: ScaffoldIn,
                       x_api_key: str | None = Header(default=None)):
    """Bemis-Murcko scaffold clustering. Charges 1 SMILES/input molecule."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    _rl(f"scaf:{x_api_key}", limit=30, window=60.0)
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    n = len(body.smiles)
    used, quota = teams.effective_quota(x_api_key)
    if used + n > quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{quota})")
    rows = scaffolds.analyze(body.smiles, top_k=body.top_k)
    keysdb.record(x_api_key, "/scaffolds", n)
    return {"n_unique_scaffolds": len(rows),
            "scaffolds": [r.to_dict() for r in rows],
            "quota_charged": n}


# ---------------- molecular fingerprints ----------------

@app.get("/fingerprints/kinds")
def fingerprint_kinds():
    """Public: list supported fingerprint kinds + defaults (no auth required)."""
    return {
        "kinds": list(fingerprints.KINDS),
        "outputs": list(fingerprints.OUTPUTS),
        "defaults": {"kind": "morgan", "n_bits": 2048, "radius": 2,
                     "output": "bits"},
        "notes": {
            "morgan": "ECFP-style circular; radius 2 == ECFP4",
            "maccs": "fixed 167-bit structural keys; n_bits/radius ignored",
        },
    }


@app.post("/fingerprints")
def fingerprints_endpoint(body: FingerprintIn,
                          x_api_key: str | None = Header(default=None)):
    """Molecular fingerprints (morgan/rdkit/atompair/torsion/maccs) returned as
    on-bit indices and/or a base64 bit vector. Charges 1 SMILES/molecule."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"fp:{x_api_key}", limit=60, window=60.0)
    n = len(body.smiles)
    used, quota = teams.effective_quota(x_api_key)
    if used + n > quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{quota})")
    try:
        results = fingerprints.compute_batch(
            body.smiles, kind=body.kind, n_bits=body.n_bits,
            radius=body.radius, output=body.output,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keysdb.record(x_api_key, "/fingerprints", n)
    return {"kind": body.kind.lower(), "n": n, "results": results,
            "quota_charged": n}


# ---------------- API key rotation ----------------

@app.post("/auth/rotate")
def auth_rotate(x_api_key: str | None = Header(default=None)):
    """Burn the current key, issue a new one for the same email+tier.

    Caller authenticates with the key they want to rotate; the new key is
    returned exactly once (cannot be retrieved again).
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    _rl(f"rotate:{x_api_key}", limit=5, window=3600.0)
    try:
        res = rotatelib.rotate(x_api_key)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {
        "old_key_last12": res.old_key[-12:],
        "new_key": res.new_key,
        "email": res.email,
        "tier": res.tier,
    }


# ---------------- invoices ----------------

@app.get("/invoice")
def invoice_current(x_api_key: str | None = Header(default=None),
                    period: str | None = None):
    """Invoice for the current (or requested YYYY-MM) period.

    Returns both structured JSON and a markdown rendering.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    if not keysdb.lookup(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    try:
        inv = invoices.generate(x_api_key, period)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {**inv.to_dict(), "markdown": inv.to_markdown()}


# ---------------- audit trail ----------------

@app.get("/audit")
def audit_recent(x_api_key: str | None = Header(default=None),
                 limit: int = 100):
    """Return the last N requests made with this API key."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    if not keysdb.lookup(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    limit = max(1, min(limit, 1000))
    return {"events": audit.recent(x_api_key, limit=limit)}


@app.get("/audit.csv")
def audit_csv(x_api_key: str | None = Header(default=None), limit: int = 1000):
    if not x_api_key or not keysdb.lookup(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    rows = audit.recent(x_api_key, limit=max(1, min(limit, 10_000)))
    body = exporters.to_csv(rows, columns=["ts", "method", "path",
                                           "status", "ms", "n_smiles"])
    return PlainTextResponse(body, media_type="text/csv")


@app.get("/invoice.csv")
def invoice_csv(x_api_key: str | None = Header(default=None),
                period: str | None = None):
    if not x_api_key or not keysdb.lookup(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    try:
        inv = invoices.generate(x_api_key, period)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    body = exporters.to_csv([l.to_dict() for l in inv.lines],
                            columns=["endpoint", "calls", "smiles"])
    return PlainTextResponse(body, media_type="text/csv")


# ---------------- file upload (SDF / CSV / SMI) ----------------

@app.post("/upload/compute")
async def upload_compute(file: UploadFile = File(...),
                         x_api_key: str | None = Header(default=None)):
    """Accept an SDF/CSV/SMI file, return descriptors for each molecule.

    Charges 1 SMILES per parsed molecule against the team pool (if any).
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"upload:{x_api_key}", limit=10, window=60.0)
    blob = await file.read()
    if len(blob) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (>50MB)")
    parsed = uploads.parse(blob, filename=file.filename or "")
    if not parsed.smiles:
        raise HTTPException(status_code=400, detail="No valid molecules parsed")
    used, quota = teams.effective_quota(x_api_key)
    n = len(parsed.smiles)
    if used + n > quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{quota})")
    results = [compute.compute_molecule(cid=-(i + 1), smiles=s).to_dict()
               for i, s in enumerate(parsed.smiles)]
    keysdb.record(x_api_key, "/upload/compute", n)
    return {"format": parsed.format, "n_parsed": parsed.n_parsed,
            "results": results, "quota_charged": n}


# ---------------- SMARTS substructure filter ----------------

@app.post("/substructure")
def substructure_endpoint(body: SubstructureIn,
                          x_api_key: str | None = Header(default=None)):
    """Find molecules in `smiles` matching the given SMARTS pattern.

    Charges 1 per input SMILES (not per hit).
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"sub:{x_api_key}", limit=30, window=60.0)
    n = len(body.smiles)
    used, quota = teams.effective_quota(x_api_key)
    if used + n > quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{quota})")
    try:
        hits = substructure.filter_smarts(body.smarts, body.smiles,
                                          max_hits=body.max_hits)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keysdb.record(x_api_key, "/substructure", n)
    return {
        "n_input": n,
        "n_hits": len(hits),
        "hits": [{"smiles": h.smiles, "match_atoms": h.match_atoms}
                 for h in hits],
        "quota_charged": n,
    }


# ---------------- diversity picker ----------------

@app.post("/diversity")
def diversity_endpoint(body: DiversityIn,
                       x_api_key: str | None = Header(default=None)):
    """MaxMin Tanimoto-diversity pick: return K maximally diverse SMILES."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"div:{x_api_key}", limit=20, window=60.0)
    n = len(body.smiles)
    used, quota = teams.effective_quota(x_api_key)
    if used + n > quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{quota})")
    try:
        res = diversity.pick(body.smiles, k=body.k, seed=body.seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keysdb.record(x_api_key, "/diversity", n)
    return {**res.to_dict(), "quota_charged": n}


# ---------------- Butina clustering ----------------

@app.post("/cluster")
def cluster_endpoint(body: ClusterIn,
                     x_api_key: str | None = Header(default=None)):
    """Butina clustering by ECFP4 Tanimoto distance (N<=2000).

    `cutoff` is a DISTANCE threshold (1 - similarity); smaller = tighter
    clusters. Returns clusters largest-first, each with a centroid. Charges 1
    SMILES/input molecule.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"cluster:{x_api_key}", limit=20, window=60.0)
    n = len(body.smiles)
    used, quota = teams.effective_quota(x_api_key)
    if used + n > quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{quota})")
    try:
        res = clustering.cluster(body.smiles, cutoff=body.cutoff)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keysdb.record(x_api_key, "/cluster", n)
    return {**res.to_dict(), "quota_charged": n}


# ---------------- SDF download ----------------

@app.post("/download/sdf")
def download_sdf(body: SdfDownloadIn,
                 x_api_key: str | None = Header(default=None)):
    """Return a single SDF file containing the provided SMILES."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"sdf:{x_api_key}", limit=10, window=60.0)
    sdf = sdf_out.smiles_to_sdf(body.smiles, with_coords=body.with_coords)
    keysdb.record(x_api_key, "/download/sdf", len(body.smiles))
    return PlainTextResponse(
        sdf, media_type="chemical/x-mdl-sdfile",
        headers={"Content-Disposition": 'attachment; filename="qmol.sdf"'},
    )


# ---------------- Parquet bulk export ----------------

@app.post("/export/parquet")
def export_parquet(body: ParquetIn,
                   x_api_key: str | None = Header(default=None)):
    """Compute descriptors for `smiles` and return a Parquet file."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"parq:{x_api_key}", limit=10, window=60.0)
    n = len(body.smiles)
    used, quota = teams.effective_quota(x_api_key)
    if used + n > quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{quota})")
    rows = _run(body.smiles)
    blob = parquet_out.to_parquet_bytes(rows)
    keysdb.record(x_api_key, "/export/parquet", n)
    return Response(
        content=blob, media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="qmol.parquet"'},
    )


# ---------------- usage history (per-day + per-endpoint) ----------------

@app.get("/usage/history")
def usage_history(x_api_key: str | None = Header(default=None),
                  days: int = 30):
    if not x_api_key or not keysdb.lookup(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    days = max(1, min(days, 365))
    return {
        "days": days,
        "daily": usage_stats.daily_counts(x_api_key, days=days),
        "by_endpoint": usage_stats.endpoint_breakdown(x_api_key, days=days),
    }


# ---------------- key self-rotation ----------------

@app.post("/key/rotate")
def key_rotate(x_api_key: str | None = Header(default=None)):
    """Rotate the caller's own API key. Old key is deactivated immediately."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"keyrot:{x_api_key}", limit=3, window=3600.0)
    try:
        res = rotatelib.rotate(x_api_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"old_key_suffix": res.old_key[-6:], "new_key": res.new_key,
            "email": res.email, "tier": res.tier}


# ---------------- public SLO / uptime badge ----------------

@app.get("/badge/uptime")
def uptime_badge(days: int = 7):
    """Public: shields.io-compatible JSON + raw SLO numbers."""
    days = max(1, min(days, 90))
    s = usage_stats.global_slo(days=days)
    pct = s["slo"] * 100.0
    color = ("brightgreen" if pct >= 99.9 else
             "green" if pct >= 99.5 else
             "yellow" if pct >= 99.0 else "red")
    return {"schemaVersion": 1, "label": f"uptime {days}d",
            "message": f"{pct:.3f}%", "color": color, **s}


# ---------------- scopes ----------------

@app.get("/key/scopes")
def get_key_scopes(x_api_key: str | None = Header(default=None)):
    if not x_api_key or not keysdb.lookup(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    sc = scopes.get_scopes(x_api_key)
    return {"scopes": sc, "unrestricted": sc is None,
            "known": sorted(scopes.KNOWN_SCOPES)}


@app.put("/key/scopes")
def set_key_scopes(body: ScopesIn,
                   x_api_key: str | None = Header(default=None)):
    if not x_api_key or not keysdb.lookup(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    try:
        saved = scopes.set_scopes(x_api_key, body.scopes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"scopes": saved}


@app.delete("/key/scopes")
def clear_key_scopes(x_api_key: str | None = Header(default=None)):
    if not x_api_key or not keysdb.lookup(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    scopes.clear_scopes(x_api_key)
    return {"scopes": None, "unrestricted": True}


# ---------------- retrosynthesis (1-step, template-based) ----------------

@app.post("/retro")
def retro_endpoint(body: RetroIn,
                   x_api_key: str | None = Header(default=None)):
    """Return plausible 1-step disconnections (amide, ester, Suzuki, etc.)."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing x-api-key header")
    info = keysdb.lookup(x_api_key)
    if not info or not info.active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    _rl(f"retro:{x_api_key}", limit=30, window=60.0)
    used, quota = teams.effective_quota(x_api_key)
    if used + 1 > quota:
        raise HTTPException(status_code=402,
                            detail=f"Quota would be exceeded ({used}/{quota})")
    try:
        steps = retro.one_step(body.smiles, max_results=body.max_results)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    keysdb.record(x_api_key, "/retro", 1)
    return {"smiles": body.smiles, "n": len(steps),
            "steps": [s.to_dict() for s in steps], "quota_charged": 1}


# ---------------- plans / pricing ----------------

@app.get("/plans")
def list_plans():
    """Public pricing catalog."""
    return {"plans": plans.PLANS}


# ---------------- customer dashboard ----------------

@app.get("/dashboard", include_in_schema=False)
def dashboard_page():
    from fastapi.responses import FileResponse
    p = Path(__file__).parent / "landing" / "dashboard.html"
    if p.exists():
        return FileResponse(p, media_type="text/html")
    raise HTTPException(status_code=404, detail="not found")


# ---------------- cache stats (admin) ----------------

@app.get("/admin/cache")
def admin_cache_stats(x_admin_token: str | None = Header(default=None)):
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return result_cache.COMPUTE_CACHE.stats()


# ---------------- landing / docs HTML ----------------

@app.get("/app", include_in_schema=False)
def landing_app():
    from fastapi.responses import FileResponse
    p = Path(__file__).parent / "landing" / "index.html"
    if p.exists():
        return FileResponse(p, media_type="text/html")
    raise HTTPException(status_code=404, detail="not found")


@app.get("/reference", include_in_schema=False)
def reference_page():
    from fastapi.responses import FileResponse
    p = Path(__file__).parent / "landing" / "docs.html"
    if p.exists():
        return FileResponse(p, media_type="text/html")
    raise HTTPException(status_code=404, detail="not found")


@app.get("/openapi-static.json", include_in_schema=False)
def openapi_static():
    from fastapi.responses import FileResponse
    p = Path(__file__).parent / "landing" / "openapi.json"
    if p.exists():
        return FileResponse(p, media_type="application/json")
    raise HTTPException(status_code=404, detail="not found")


# ---------------- coupons (checkout helper) ----------------

@app.post("/coupon/check")
def coupon_check(body: CouponCheckIn):
    """Used by checkout.html before creating a Stripe session."""
    _PRICE_CENTS = {"research": 2900, "commercial": 29900,
                    "redistribution": 99900, "enterprise": 500000}
    base = _PRICE_CENTS.get(body.tier, 0)
    if base == 0:
        raise HTTPException(status_code=400, detail="Unknown tier")
    return coupons.apply(body.code, body.tier, base)


# ---------------- magic-link key recovery ----------------

@app.post("/auth/magic-link")
def magic_link_request(body: MagicLinkIn, request: Request):
    """Send a magic link to the email's inbox. Rate-limited to prevent spam."""
    ip = _client_ip(request)
    _rl(f"magic:{ip}", limit=3, window=300.0)  # 3 per 5 min per IP
    token = magic_link.issue(str(body.email))
    base = os.getenv("QMOL_PUBLIC_URL", "https://qmol.app").rstrip("/")
    link = f"{base}/auth/redeem?token={token}"
    # Best-effort email send (prod); dev returns token for manual test
    _sent = False
    try:
        from stripe_webhook import _send_mailgun  # type: ignore
        _sent = _send_mailgun(str(body.email), "Your Q-Mol login link",
                              f"Click to retrieve your API key: {link}\n\n"
                              f"Link expires in 15 minutes.")
    except Exception:
        _sent = False
    return {"sent": _sent, "dev_token": None if _sent else token}


@app.get("/auth/redeem")
def magic_link_redeem(token: str):
    api_key = magic_link.consume(token)
    if not api_key:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    return {"api_key": api_key}


def make_api_key(email: str, secret: str) -> str:
    """Deterministic API key generator used by the Stripe webhook delivery path."""
    h = hashlib.sha256(f"{email}|{secret}".encode()).hexdigest()
    return f"qmol_{h[:32]}"
