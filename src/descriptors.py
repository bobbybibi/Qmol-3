"""Full RDKit 2D descriptor panel for QSAR / ML featurization.

``/compute`` returns the ~20 medchem descriptors Q-Mol stores in its dataset.
This module exposes the *entire* RDKit 2D descriptor set (~200 named features)
as a flat dict — the "RDKit-based QSAR featurizer" pyproject.toml advertises —
with an optional ``names`` subset for callers who only want specific columns.

Some descriptors are undefined for some molecules and come back as NaN/inf;
those are converted to ``None`` so the payload is always valid JSON.

Exposed via ``POST /descriptors`` — charges 2 SMILES/molecule.
"""
from __future__ import annotations
import math
from typing import List

from rdkit import Chem
from rdkit.Chem import Descriptors

# Authoritative name set = exactly what CalcMolDescriptors emits (computed once
# from a trivial reference molecule so it can't drift from the live output).
_REF = Descriptors.CalcMolDescriptors(Chem.MolFromSmiles("C"))
ALL_NAMES = tuple(_REF.keys())
_NAME_SET = frozenset(ALL_NAMES)


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def compute_one(smiles: str, names: List[str] | None = None) -> dict:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")
    if names:
        unknown = [n for n in names if n not in _NAME_SET]
        if unknown:
            raise ValueError(f"unknown descriptors: {unknown[:10]}")
    d = Descriptors.CalcMolDescriptors(mol)
    if names:
        d = {n: d[n] for n in names}
    return {"smiles": smiles, "descriptors": {k: _clean(v) for k, v in d.items()}}


def compute_batch(smiles: List[str], names: List[str] | None = None) -> list[dict]:
    return [compute_one(s, names) for s in smiles]
