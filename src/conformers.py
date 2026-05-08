"""3D conformer generation + optimization.

RDKit's ETKDG v3 conformer + MMFF94s optimization. Returns the lowest-energy
conformer as either SDF text (drop into PyMOL, Chimera, docking pipelines)
or a plain [[x,y,z], ...] array.

Exposed via POST /conformers. Charges 10 SMILES/molecule (heavier compute).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem import AllChem


@dataclass
class Conformer:
    smiles: str
    n_conformers: int
    energy_kcal_mol: float
    sdf: str
    coords: list[list[float]]

    def to_dict(self) -> dict:
        return asdict(self)


def generate(smiles: str, n_conformers: int = 10,
             max_iters: int = 200) -> Conformer:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")
    mol = Chem.AddHs(mol)

    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    params.numThreads = 0
    cids = AllChem.EmbedMultipleConfs(mol, numConfs=n_conformers, params=params)
    if not cids:
        raise ValueError(f"Failed to embed conformers for {smiles!r}")

    # MMFF94s optimize each, pick lowest-energy
    results = AllChem.MMFFOptimizeMoleculeConfs(
        mol, maxIters=max_iters, mmffVariant="MMFF94s"
    )
    # results = [(not_converged, energy), ...]
    best_idx = min(range(len(results)), key=lambda i: results[i][1])
    best_energy = float(results[best_idx][1])

    # Extract SDF for the best conformer
    writer_buf: list[str] = []
    best_mol = Chem.Mol(mol)
    best_mol.RemoveAllConformers()
    best_mol.AddConformer(mol.GetConformer(cids[best_idx]), assignId=True)
    sdf = Chem.MolToMolBlock(best_mol)

    conf = best_mol.GetConformer()
    coords = [[conf.GetAtomPosition(i).x,
               conf.GetAtomPosition(i).y,
               conf.GetAtomPosition(i).z]
              for i in range(best_mol.GetNumAtoms())]

    return Conformer(
        smiles=smiles,
        n_conformers=len(cids),
        energy_kcal_mol=round(best_energy, 4),
        sdf=sdf,
        coords=coords,
    )
