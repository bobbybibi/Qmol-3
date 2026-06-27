"""Stereoisomer enumeration.

Expands undefined stereocenters and double-bond geometries into the set of
distinct stereoisomers — for prepping enantiomer/diastereomer/E-Z sets before
docking or QM, or auditing how many stereo forms a flat 2D structure implies.
The stereochemistry complement to ``/tautomers``; uses RDKit's
``EnumerateStereoisomers``.

By default only *unassigned* centers are expanded (existing stereo is kept);
set ``only_unassigned=False`` to also flip already-specified centers. The
``max_isomers`` cap bounds the 2^n blow-up.

Exposed via ``POST /stereoisomers`` — charges 2 SMILES/molecule.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem.EnumerateStereoisomers import (
    EnumerateStereoisomers, StereoEnumerationOptions,
)


@dataclass
class StereoResult:
    smiles: str
    n_isomers: int
    isomers: list[str]        # distinct canonical SMILES
    truncated: bool           # True if the result was capped at max_isomers

    def to_dict(self) -> dict:
        return asdict(self)


def enumerate_one(smiles: str, max_isomers: int = 64,
                  only_unassigned: bool = True) -> StereoResult:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")
    # Ask for one extra so we can tell whether we actually hit the cap.
    opts = StereoEnumerationOptions(maxIsomers=max_isomers + 1,
                                    onlyUnassigned=only_unassigned)
    seen: set[str] = set()
    out: list[str] = []
    for iso in EnumerateStereoisomers(mol, options=opts):
        s = Chem.MolToSmiles(iso)
        if s not in seen:
            seen.add(s)
            out.append(s)
    truncated = len(out) > max_isomers
    if truncated:
        out = out[:max_isomers]
    return StereoResult(smiles=smiles, n_isomers=len(out), isomers=out,
                        truncated=truncated)


def enumerate_batch(smiles: List[str], max_isomers: int = 64,
                    only_unassigned: bool = True) -> list[dict]:
    return [enumerate_one(s, max_isomers, only_unassigned).to_dict() for s in smiles]
