"""Bemis–Murcko scaffold analysis: cluster a library by shared skeleton.

Sells as: "Give me the 10 most common scaffolds in my 50k hit list" —
standard medchem triage. Charges 1 SMILES/molecule.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from typing import List

from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold


@dataclass
class ScaffoldRow:
    scaffold: str
    count: int
    members: list[str]

    def to_dict(self) -> dict:
        return {"scaffold": self.scaffold, "count": self.count,
                "members": self.members}


def scaffold_of(smiles: str) -> str:
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")
    scaf = MurckoScaffold.GetScaffoldForMol(m)
    return Chem.MolToSmiles(scaf)


def analyze(smiles_list: List[str], top_k: int = 20) -> list[ScaffoldRow]:
    groups: dict[str, list[str]] = {}
    for smi in smiles_list:
        try:
            s = scaffold_of(smi)
        except ValueError:
            continue
        groups.setdefault(s, []).append(smi)
    rows = [ScaffoldRow(scaffold=s, count=len(v), members=v)
            for s, v in groups.items()]
    rows.sort(key=lambda r: r.count, reverse=True)
    return rows[:top_k]
