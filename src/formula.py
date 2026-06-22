"""Molecular formula, masses, elemental composition, and ring/double-bond
equivalents — the formula-validation / mass-spec utility.

`exact_mass` is the monoisotopic mass (what you match against an LC-MS peak);
`average_mass` is the natural-abundance-weighted molecular weight. `rdbe` is the
standard degree of unsaturation (ring + double-bond equivalents) computed from
the CHNX atom counts: (2·C + 2 + N − H − halogens) / 2 — divalent O/S don't
affect it.

Exposed via ``POST /formula`` — charges 1 SMILES/molecule.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors

_HALOGENS = ("F", "Cl", "Br", "I", "At")


@dataclass
class Formula:
    smiles: str
    formula: str                 # Hill-system formula, e.g. "C9H8O4"
    exact_mass: float            # monoisotopic
    average_mass: float          # natural-abundance weighted
    composition: dict[str, int]  # element -> count (explicit H included)
    heavy_atoms: int
    rdbe: float                  # ring + double-bond equivalents
    num_rings: int

    def to_dict(self) -> dict:
        return asdict(self)


def compute_one(smiles: str) -> Formula:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")
    molh = Chem.AddHs(mol)
    comp = Counter(a.GetSymbol() for a in molh.GetAtoms())
    c = comp.get("C", 0)
    h = comp.get("H", 0)
    n = comp.get("N", 0)
    x = sum(comp.get(sym, 0) for sym in _HALOGENS)
    rdbe = (2 * c + 2 + n - h - x) / 2.0
    return Formula(
        smiles=smiles,
        formula=rdMolDescriptors.CalcMolFormula(mol),
        exact_mass=round(Descriptors.ExactMolWt(mol), 5),
        average_mass=round(Descriptors.MolWt(mol), 4),
        composition=dict(sorted(comp.items())),
        heavy_atoms=mol.GetNumHeavyAtoms(),
        rdbe=rdbe,
        num_rings=rdMolDescriptors.CalcNumRings(mol),
    )


def compute_batch(smiles: List[str]) -> list[dict]:
    return [compute_one(s).to_dict() for s in smiles]
