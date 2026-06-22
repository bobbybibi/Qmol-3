"""Pairwise Tanimoto similarity matrix over a caller-supplied SMILES set.

Distinct from ``similarity.search`` (which scans the *public* dataset for hits):
this computes the full N×N Morgan/ECFP4 Tanimoto matrix among the SMILES the
caller sends — the primitive behind clustering, dedup, diversity analysis, and
SAR heatmaps.

O(N²) in fingerprint comparisons (done with RDKit's BulkTanimotoSimilarity, so
the inner loop is C++); the endpoint caps N to keep responses bounded.

Exposed via ``POST /similarity/matrix`` — charges 1 SMILES/input molecule.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem import rdFingerprintGenerator, DataStructs

# ECFP4 (radius 2, 2048 bits) — same family Q-Mol uses everywhere else.
_GEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


@dataclass
class SimMatrix:
    n: int                       # number of valid molecules in the matrix
    smiles: list[str]            # the valid SMILES (matrix row/col order)
    invalid: list[int]           # indices in the *input* that failed to parse
    matrix: list[list[float]]    # n×n symmetric; diagonal = 1.0
    nearest: list[dict]          # per row: nearest neighbor {i, nearest_j, similarity}

    def to_dict(self) -> dict:
        return asdict(self)


def _fingerprints(smiles: List[str]):
    fps, valid_idx, invalid = [], [], []
    for i, s in enumerate(smiles):
        m = Chem.MolFromSmiles(s)
        if m is None:
            invalid.append(i)
            continue
        fps.append(_GEN.GetFingerprint(m))
        valid_idx.append(i)
    return fps, valid_idx, invalid


def compute(smiles: List[str], round_to: int = 4) -> SimMatrix:
    fps, valid_idx, invalid = _fingerprints(smiles)
    if not fps:
        raise ValueError("no valid SMILES to compare")
    valid_smiles = [smiles[i] for i in valid_idx]
    n = len(fps)

    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        matrix[i][i] = 1.0
        if i + 1 < n:
            sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[i + 1:])
            for off, sim in enumerate(sims):
                j = i + 1 + off
                v = round(float(sim), round_to)
                matrix[i][j] = matrix[j][i] = v

    nearest = []
    for i in range(n):
        best_j, best = None, -1.0
        for j in range(n):
            if j != i and matrix[i][j] > best:
                best, best_j = matrix[i][j], j
        nearest.append({
            "i": i,
            "nearest_j": best_j,
            "similarity": (best if best_j is not None else None),
        })

    return SimMatrix(n=n, smiles=valid_smiles, invalid=invalid,
                     matrix=matrix, nearest=nearest)
