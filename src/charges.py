"""Gasteiger partial atomic charges.

RDKit's Gasteiger-Marsili (PEOE) partial charges per atom — a fast,
deterministic estimate of charge distribution for reactivity intuition,
electrostatic descriptors, and QM/docking input prep. Charges are computed on
the explicit-H structure (so the total conserves to ~the formal charge); by
default only heavy atoms are reported, set ``include_hs`` to include hydrogens.

Charges that come back undefined (NaN/inf for a few atom types) are reported as
null.

Exposed via ``POST /charges`` — charges 1 SMILES/molecule.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem import AllChem


@dataclass
class ChargeResult:
    smiles: str
    atoms: list[dict]        # [{idx, symbol, charge}] in molecule-atom order
    total_charge: float      # sum over ALL atoms (~ formal charge)

    def to_dict(self) -> dict:
        return asdict(self)


def _charge(atom) -> float | None:
    try:
        q = float(atom.GetProp("_GasteigerCharge"))
    except Exception:  # noqa: BLE001
        return None
    if math.isnan(q) or math.isinf(q):
        return None
    return q


def compute_one(smiles: str, include_hs: bool = False) -> ChargeResult:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")
    molh = Chem.AddHs(mol)
    AllChem.ComputeGasteigerCharges(molh)

    total = 0.0
    atoms = []
    for a in molh.GetAtoms():
        q = _charge(a)
        if q is not None:
            total += q
        if include_hs or a.GetSymbol() != "H":
            atoms.append({
                "idx": a.GetIdx(),
                "symbol": a.GetSymbol(),
                "charge": round(q, 5) if q is not None else None,
            })
    return ChargeResult(smiles=smiles, atoms=atoms, total_charge=round(total, 5))


def compute_batch(smiles: List[str], include_hs: bool = False) -> list[dict]:
    return [compute_one(s, include_hs).to_dict() for s in smiles]
