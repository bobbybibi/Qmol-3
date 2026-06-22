"""Maximum Common Substructure (MCS) across a set of molecules.

``rdFMCS`` finds the largest substructure shared by *all* input molecules — the
data-driven common scaffold. Useful for SAR-series analysis, setting up R-group
decomposition, and answering "what do these hits have in common?".

Returns the MCS as SMARTS (always) and as canonical SMILES when convertible,
plus atom/bond counts and whether the search completed within the timeout.

Exposed via ``POST /mcs`` — charges 1 SMILES/input molecule.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem import rdFMCS


@dataclass
class MCSResult:
    n_input: int
    n_valid: int
    invalid: list[int]
    smarts: str | None
    smiles: str | None        # MCS as canonical SMILES when convertible
    num_atoms: int
    num_bonds: int
    completed: bool           # False if the FMCS search hit the timeout

    def to_dict(self) -> dict:
        return asdict(self)


def find(smiles: List[str], complete_rings_only: bool = False,
         ring_matches_ring_only: bool = False, timeout: int = 10) -> MCSResult:
    mols, invalid = [], []
    for i, s in enumerate(smiles):
        m = Chem.MolFromSmiles(s)
        if m is None:
            invalid.append(i)
            continue
        mols.append(m)
    if len(mols) < 2:
        raise ValueError("need at least 2 valid molecules for MCS")

    res = rdFMCS.FindMCS(
        mols, timeout=timeout,
        completeRingsOnly=complete_rings_only,
        ringMatchesRingOnly=ring_matches_ring_only,
    )
    smarts = res.smartsString or None
    smi = None
    if smarts:
        q = Chem.MolFromSmarts(smarts)
        if q is not None:
            try:
                smi = Chem.MolToSmiles(q)
            except Exception:  # noqa: BLE001
                smi = None
    return MCSResult(
        n_input=len(smiles), n_valid=len(mols), invalid=invalid,
        smarts=smarts, smiles=smi,
        num_atoms=res.numAtoms, num_bonds=res.numBonds,
        completed=not res.canceled,
    )
