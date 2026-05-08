"""Tanimoto similarity search over the public molecule database.

Given a query SMILES, returns the top-K most similar molecules from the
already-computed dataset using ECFP4 Morgan fingerprints.

This is a whole new product angle: virtual-screening-as-a-service.
Researchers pay to find "molecules similar to my lead from public chem space".
"""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from typing import List

from rdkit import Chem
from rdkit.Chem import AllChem, DataStructs


@dataclass
class Hit:
    cid: int
    smiles: str
    similarity: float
    mw: float
    logp: float
    qed: float

    def to_dict(self) -> dict:
        return {
            "cid": self.cid,
            "smiles": self.smiles,
            "similarity": round(self.similarity, 4),
            "mw": self.mw,
            "logp": self.logp,
            "qed": self.qed,
        }


def _fp(smiles: str):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048)


def search(conn: sqlite3.Connection, query_smiles: str, top_k: int = 20,
           min_similarity: float = 0.3) -> List[Hit]:
    """Brute-force Tanimoto search. O(N) in DB rows.

    For up to ~100k molecules this is fast enough; beyond that, pre-cluster
    fingerprints or move to FAISS/Annoy.
    """
    q_fp = _fp(query_smiles)
    if q_fp is None:
        raise ValueError(f"Invalid SMILES: {query_smiles!r}")

    hits: list[Hit] = []
    cur = conn.execute(
        "SELECT cid, smiles, mw, logp, qed FROM molecules WHERE smiles IS NOT NULL"
    )
    for cid, smi, mw, logp, qed in cur:
        fp = _fp(smi)
        if fp is None:
            continue
        sim = DataStructs.TanimotoSimilarity(q_fp, fp)
        if sim >= min_similarity:
            hits.append(Hit(cid=cid, smiles=smi, similarity=sim,
                            mw=mw or 0.0, logp=logp or 0.0, qed=qed or 0.0))

    hits.sort(key=lambda h: h.similarity, reverse=True)
    return hits[:top_k]
