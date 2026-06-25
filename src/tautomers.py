"""Tautomer enumeration.

``/standardize`` *canonicalizes* tautomers (collapses a molecule to one chosen
form). This module does the opposite: it enumerates the set of plausible
tautomers — what you want when prepping ligands for QM/docking, building
augmented training sets, or auditing which protomeric/tautomeric form a model
actually saw. Uses RDKit's ``rdMolStandardize.TautomerEnumerator``.

Exposed via ``POST /tautomers`` — charges 2 SMILES/molecule (heavier than a flat
descriptor pass, far lighter than conformer generation).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem.MolStandardize import rdMolStandardize

# Reusable enumerator (read-only use; mirrors compute.PAINS_CATALOG singleton).
_ENUM = rdMolStandardize.TautomerEnumerator()


@dataclass
class TautomerResult:
    smiles: str
    canonical: str            # RDKit's canonical tautomer (scoring-based)
    n_tautomers: int
    tautomers: list[str]      # unique canonical-SMILES of each enumerated form

    def to_dict(self) -> dict:
        return asdict(self)


def enumerate_one(smiles: str, max_tautomers: int = 100) -> TautomerResult:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")

    seen: set[str] = set()
    forms: list[str] = []
    for t in _ENUM.Enumerate(mol):
        s = Chem.MolToSmiles(t)
        if s not in seen:
            seen.add(s)
            forms.append(s)
        if len(forms) >= max_tautomers:
            break

    canonical = Chem.MolToSmiles(_ENUM.Canonicalize(mol))
    return TautomerResult(smiles=smiles, canonical=canonical,
                          n_tautomers=len(forms), tautomers=forms)


def enumerate_batch(smiles: List[str], max_tautomers: int = 100) -> list[dict]:
    return [enumerate_one(s, max_tautomers).to_dict() for s in smiles]
