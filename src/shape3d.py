"""3D shape descriptors from a generated conformer.

Embeds an ETKDG conformer (MMFF-optimized) and computes the normalized shape
descriptors used in shape-based virtual screening and rod/disc/sphere triage:
NPR1/NPR2 (the normalized PMI-ratio axes of the classic shape plot),
asphericity, radius of gyration, eccentricity, spherocity, inertial shape
factor, and the raw principal moments PMI1/2/3.

Embedding can fail for some inputs (degrades gracefully to success=False);
invalid SMILES raise ValueError.

Exposed via ``POST /shape3d`` — charges 5 SMILES/molecule (conformer generation
is heavier than a 2D pass).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Callable, List

from rdkit import Chem
from rdkit.Chem import AllChem, Descriptors3D


@dataclass
class Shape3D:
    smiles: str
    success: bool
    npr1: float | None
    npr2: float | None
    asphericity: float | None
    radius_of_gyration: float | None
    eccentricity: float | None
    spherocity: float | None
    inertial_shape_factor: float | None
    pmi1: float | None
    pmi2: float | None
    pmi3: float | None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _embed(mol: Chem.Mol, seed: int = 42) -> Chem.Mol | None:
    m = Chem.AddHs(mol)
    if AllChem.EmbedMolecule(m, randomSeed=seed) != 0:
        params = AllChem.ETKDGv3()
        params.randomSeed = seed
        params.useRandomCoords = True
        if AllChem.EmbedMolecule(m, params) != 0:
            return None
    try:
        AllChem.MMFFOptimizeMolecule(m, maxIters=200)
    except Exception:  # noqa: BLE001
        pass
    return m


def _fail(smiles: str, err: str) -> Shape3D:
    return Shape3D(smiles=smiles, success=False, npr1=None, npr2=None,
                   asphericity=None, radius_of_gyration=None, eccentricity=None,
                   spherocity=None, inertial_shape_factor=None,
                   pmi1=None, pmi2=None, pmi3=None, error=err)


def compute_one(smiles: str, seed: int = 42) -> Shape3D:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")
    m3d = _embed(mol, seed)
    if m3d is None:
        return _fail(smiles, "3D embedding failed")

    def r5(fn: Callable) -> float:
        return round(float(fn(m3d)), 5)

    return Shape3D(
        smiles=smiles, success=True,
        npr1=r5(Descriptors3D.NPR1), npr2=r5(Descriptors3D.NPR2),
        asphericity=r5(Descriptors3D.Asphericity),
        radius_of_gyration=r5(Descriptors3D.RadiusOfGyration),
        eccentricity=r5(Descriptors3D.Eccentricity),
        spherocity=r5(Descriptors3D.SpherocityIndex),
        inertial_shape_factor=r5(Descriptors3D.InertialShapeFactor),
        pmi1=round(float(Descriptors3D.PMI1(m3d)), 4),
        pmi2=round(float(Descriptors3D.PMI2(m3d)), 4),
        pmi3=round(float(Descriptors3D.PMI3(m3d)), 4),
    )


def compute_batch(smiles: List[str], seed: int = 42) -> list[dict]:
    return [compute_one(s, seed).to_dict() for s in smiles]
