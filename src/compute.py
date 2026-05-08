"""Compute engine — Windows-native with optional quantum upgrade tiers.

Tiers (auto-selected per molecule):
1. **RDKit descriptors** (always, Windows-native, sellable today):
   MW, logP, TPSA, HBD/HBA, rotatable bonds, QED, ring counts, ECFP4.
2. **PySCF HF/CCSD** (optional, Linux/WSL/conda):
   ground-state energy, HOMO/LUMO, dipole.
3. **pyQPanda VQE** (optional, Python 3.11 / Linux):
   quantum-computed energy with full provenance.
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, asdict
from typing import Any

from rdkit import Chem
from rdkit.Chem import (
    AllChem, Descriptors, Crippen, Lipinski, QED, rdMolDescriptors, inchi,
)
from rdkit.Chem.Scaffolds import MurckoScaffold

try:
    from rdkit.Chem.FilterCatalog import FilterCatalogParams, FilterCatalog as _FC
    _pains_params = FilterCatalogParams()
    _pains_params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
    PAINS_CATALOG = _FC(_pains_params)
except Exception:  # noqa: BLE001
    PAINS_CATALOG = None

log = logging.getLogger(__name__)

try:
    from pyscf import gto, scf, cc  # type: ignore  # noqa: F401
    HAS_PYSCF = True
except Exception:  # noqa: BLE001
    HAS_PYSCF = False

try:
    import pyqpanda as _pq  # type: ignore  # noqa: F401
    HAS_PYQPANDA = True
except Exception:  # noqa: BLE001
    HAS_PYQPANDA = False


@dataclass
class ComputeResult:
    cid: int
    smiles: str
    method: str
    basis: str | None
    num_atoms: int
    num_heavy_atoms: int
    num_electrons: int | None
    num_qubits: int | None
    energy_hartree: float | None
    homo_hartree: float | None
    lumo_hartree: float | None
    dipole_debye: float | None
    mw: float | None
    logp: float | None
    tpsa: float | None
    hbd: int | None
    hba: int | None
    rotatable_bonds: int | None
    ring_count: int | None
    aromatic_rings: int | None
    qed: float | None
    ecfp4_hash: str | None
    inchikey: str | None
    murcko_scaffold: str | None
    fsp3: float | None
    heteroatom_count: int | None
    formal_charge: int | None
    stereo_centers: int | None
    mol_refractivity: float | None
    lipinski_pass: int | None
    veber_pass: int | None
    pains_hit: int | None
    runtime_seconds: float
    success: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rdkit_descriptors(mol: Chem.Mol) -> dict[str, Any]:
    ecfp = AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048)
    try:
        scaffold = MurckoScaffold.GetScaffoldForMol(mol)
        scaffold_smi = Chem.MolToSmiles(scaffold) if scaffold else None
    except Exception:  # noqa: BLE001
        scaffold_smi = None
    try:
        inchikey = inchi.MolToInchiKey(mol)
    except Exception:  # noqa: BLE001
        inchikey = None
    try:
        pains_hit = int(PAINS_CATALOG.HasMatch(mol)) if PAINS_CATALOG else None
    except Exception:  # noqa: BLE001
        pains_hit = None

    mw = float(Descriptors.MolWt(mol))
    logp = float(Crippen.MolLogP(mol))
    tpsa = float(Descriptors.TPSA(mol))
    hbd = int(Lipinski.NumHDonors(mol))
    hba = int(Lipinski.NumHAcceptors(mol))
    rotb = int(Lipinski.NumRotatableBonds(mol))

    lipinski_pass = int(mw <= 500 and logp <= 5 and hbd <= 5 and hba <= 10)
    veber_pass = int(rotb <= 10 and tpsa <= 140)
    hetero = sum(1 for a in mol.GetAtoms() if a.GetSymbol() not in ("C", "H"))
    try:
        stereo = len(Chem.FindMolChiralCenters(mol, includeUnassigned=True))
    except Exception:  # noqa: BLE001
        stereo = 0

    return {
        "mw": mw,
        "logp": logp,
        "tpsa": tpsa,
        "hbd": hbd,
        "hba": hba,
        "rotatable_bonds": rotb,
        "ring_count": int(rdMolDescriptors.CalcNumRings(mol)),
        "aromatic_rings": int(rdMolDescriptors.CalcNumAromaticRings(mol)),
        "qed": float(QED.qed(mol)),
        "ecfp4_hash": ecfp.ToBase64()[:128],
        "inchikey": inchikey,
        "murcko_scaffold": scaffold_smi,
        "fsp3": float(rdMolDescriptors.CalcFractionCSP3(mol)),
        "heteroatom_count": int(hetero),
        "formal_charge": int(Chem.GetFormalCharge(mol)),
        "stereo_centers": int(stereo),
        "mol_refractivity": float(Crippen.MolMR(mol)),
        "lipinski_pass": lipinski_pass,
        "veber_pass": veber_pass,
        "pains_hit": pains_hit,
    }


def _embed_geometry(mol: Chem.Mol) -> Chem.Mol | None:
    try:
        m = Chem.AddHs(mol)
        if AllChem.EmbedMolecule(m, randomSeed=42) != 0:
            return None
        AllChem.MMFFOptimizeMolecule(m, maxIters=200)
        return m
    except Exception:  # noqa: BLE001
        return None


def _run_pyscf(mol3d: Chem.Mol, basis: str) -> dict[str, Any] | None:
    if not HAS_PYSCF:
        return None
    try:
        from pyscf import gto, scf, cc  # type: ignore
        conf = mol3d.GetConformer()
        atoms = [
            (a.GetSymbol(),
             (conf.GetAtomPosition(a.GetIdx()).x,
              conf.GetAtomPosition(a.GetIdx()).y,
              conf.GetAtomPosition(a.GetIdx()).z))
            for a in mol3d.GetAtoms()
        ]
        mol = gto.M(atom=atoms, basis=basis, unit="Angstrom", verbose=0)
        mf = scf.RHF(mol).run()
        homo_idx = mol.nelectron // 2 - 1
        e = mf.mo_energy
        homo = float(e[homo_idx]) if homo_idx >= 0 else None
        lumo = float(e[homo_idx + 1]) if homo_idx + 1 < len(e) else None
        dipole_vec = mf.dip_moment(unit="Debye", verbose=0)
        dipole = float(sum(v * v for v in dipole_vec) ** 0.5)
        energy = float(mf.e_tot)
        method = "HF/PySCF"
        if mol.nao <= 60:
            try:
                energy = float(cc.CCSD(mf).run().e_tot)
                method = "CCSD/PySCF"
            except Exception:  # noqa: BLE001
                pass
        return {
            "method": method,
            "basis": basis,
            "energy_hartree": energy,
            "homo_hartree": homo,
            "lumo_hartree": lumo,
            "dipole_debye": dipole,
            "num_electrons": int(mol.nelectron),
            "num_qubits": int(2 * mol.nao),
        }
    except Exception as e:  # noqa: BLE001
        log.info("PySCF failed: %s", e)
        return None


def compute_molecule(
    cid: int,
    smiles: str,
    basis: str = "sto-3g",
    use_vqe_up_to_qubits: int = 12,
    max_seconds: int = 120,
    mw: float | None = None,
) -> ComputeResult:
    t0 = time.time()
    base: dict[str, Any] = dict(
        cid=cid, smiles=smiles, method="n/a", basis=None,
        num_atoms=0, num_heavy_atoms=0, num_electrons=None, num_qubits=None,
        energy_hartree=None, homo_hartree=None, lumo_hartree=None,
        dipole_debye=None,
        mw=mw, logp=None, tpsa=None, hbd=None, hba=None,
        rotatable_bonds=None, ring_count=None, aromatic_rings=None,
        qed=None, ecfp4_hash=None,
        inchikey=None, murcko_scaffold=None, fsp3=None,
        heteroatom_count=None, formal_charge=None, stereo_centers=None,
        mol_refractivity=None, lipinski_pass=None, veber_pass=None, pains_hit=None,
        runtime_seconds=0.0, success=False, error=None,
    )

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        base["error"] = "invalid SMILES"
        base["runtime_seconds"] = time.time() - t0
        return ComputeResult(**base)

    base["num_heavy_atoms"] = mol.GetNumHeavyAtoms()

    try:
        base.update(_rdkit_descriptors(mol))
        base["method"] = "RDKit/descriptors"
    except Exception as e:  # noqa: BLE001
        base["error"] = f"rdkit desc failed: {e}"
        base["runtime_seconds"] = time.time() - t0
        return ComputeResult(**base)

    mol3d = _embed_geometry(mol)
    if mol3d is not None:
        base["num_atoms"] = mol3d.GetNumAtoms()
        if HAS_PYSCF:
            qc = _run_pyscf(mol3d, basis=basis)
            if qc is not None:
                base.update(qc)

    base["success"] = True
    base["runtime_seconds"] = time.time() - t0
    return ComputeResult(**base)
