"""Fetch SMILES + basic metadata from PubChem (public, free)."""
from __future__ import annotations
import time
import logging
from dataclasses import dataclass
from typing import Iterator

import requests

log = logging.getLogger(__name__)

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


@dataclass
class MoleculeRecord:
    cid: int
    smiles: str
    name: str | None
    formula: str | None
    mw: float | None


def _get(url: str, retries: int = 3, backoff: float = 1.5) -> dict | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("PubChem fetch failed (%s): %s", attempt, e)
            time.sleep(backoff ** attempt)
    return None


def fetch_cid(cid: int) -> MoleculeRecord | None:
    url = (
        f"{PUBCHEM_BASE}/compound/cid/{cid}/property/"
        f"ConnectivitySMILES,SMILES,IUPACName,MolecularFormula,MolecularWeight/JSON"
    )
    data = _get(url)
    if not data:
        return None
    try:
        props = data["PropertyTable"]["Properties"][0]
    except (KeyError, IndexError):
        return None
    smiles = (
        props.get("SMILES")
        or props.get("ConnectivitySMILES")
        or props.get("CanonicalSMILES")
    )
    if not smiles:
        return None
    return MoleculeRecord(
        cid=cid,
        smiles=smiles,
        name=props.get("IUPACName"),
        formula=props.get("MolecularFormula"),
        mw=float(props["MolecularWeight"]) if props.get("MolecularWeight") else None,
    )


def iter_cids(start_cid: int, batch_size: int = 50) -> Iterator[MoleculeRecord]:
    """Yield molecule records starting at ``start_cid``, sequentially."""
    cid = start_cid
    while True:
        batch_end = cid + batch_size
        while cid < batch_end:
            rec = fetch_cid(cid)
            cid += 1
            if rec is not None:
                yield rec
            time.sleep(0.25)  # respect PubChem rate limit (~5 req/sec)
