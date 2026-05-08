"""SMARTS substructure filter against a SMILES list.

Given a SMARTS query and a list of SMILES, return which molecules match.
Complements /similarity (fuzzy Tanimoto) with exact pattern matching:
"find all my molecules containing a sulfonamide" etc.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List

from rdkit import Chem


@dataclass
class SubstructureHit:
    smiles: str
    match_atoms: list[int]


def filter_smarts(smarts: str, smiles: List[str],
                  max_hits: int = 10_000) -> list[SubstructureHit]:
    patt = Chem.MolFromSmarts(smarts)
    if patt is None:
        raise ValueError(f"Invalid SMARTS: {smarts!r}")
    hits: list[SubstructureHit] = []
    for smi in smiles:
        m = Chem.MolFromSmiles(smi)
        if m is None:
            continue
        match = m.GetSubstructMatch(patt)
        if match:
            hits.append(SubstructureHit(smiles=smi, match_atoms=list(match)))
            if len(hits) >= max_hits:
                break
    return hits
