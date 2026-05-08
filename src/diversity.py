"""MaxMin diversity picker.

Given N SMILES, return K that are maximally diverse (Morgan Tanimoto).
Standard medchem triage: "narrow my 10k hit list to 200 diverse leads
for plate selection". Sells as the DIVERSE endpoint.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Sequence

from rdkit import Chem
from rdkit.Chem import AllChem, DataStructs
from rdkit.SimDivFilters.rdSimDivPickers import MaxMinPicker


@dataclass
class DiversityResult:
    picked_indices: list[int]
    picked_smiles: list[str]
    n_input: int
    k: int

    def to_dict(self) -> dict:
        return {"picked_indices": self.picked_indices,
                "picked_smiles": self.picked_smiles,
                "n_input": self.n_input, "k": self.k}


def _fp(smi: str):
    m = Chem.MolFromSmiles(smi)
    if m is None:
        return None
    return AllChem.GetMorganFingerprintAsBitVect(m, radius=2, nBits=2048)


def pick(smiles: Sequence[str], k: int = 20, seed: int = 42) -> DiversityResult:
    fps: list = []
    valid_idx: list[int] = []
    for i, s in enumerate(smiles):
        fp = _fp(s)
        if fp is not None:
            fps.append(fp)
            valid_idx.append(i)
    n = len(fps)
    if n == 0:
        raise ValueError("No valid SMILES")
    if k >= n:
        return DiversityResult(picked_indices=valid_idx,
                               picked_smiles=[smiles[i] for i in valid_idx],
                               n_input=len(smiles), k=n)

    def dist_fn(i: int, j: int) -> float:
        return 1.0 - DataStructs.TanimotoSimilarity(fps[i], fps[j])

    picker = MaxMinPicker()
    picks = list(picker.LazyPick(dist_fn, n, k, seed=seed))
    idx = [valid_idx[p] for p in picks]
    return DiversityResult(picked_indices=idx,
                           picked_smiles=[smiles[i] for i in idx],
                           n_input=len(smiles), k=k)
