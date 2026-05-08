"""Quick ML-free property predictions from RDKit descriptors.

These are well-established *heuristic* models used in early medchem filtering
(not deep-learning regressors). They're valuable because:
- Zero training data / model weights needed
- Deterministic, explainable, cheap
- Good enough for "which of these 10k should I look at first"

Predictions:
- aqueous_logS (ESOL, Delaney 2004)
- BBB probability (MW/TPSA heuristic from Clark 2003)
- hERG risk flag (basic amine + high logP heuristic)
- GI absorption category (TPSA + logP, Daina/Zoete 2017 SwissADME rules)
- Synthetic accessibility score (SA_Score-lite — fragment + ring complexity)
"""
from __future__ import annotations
from dataclasses import dataclass, asdict

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors


@dataclass
class Prediction:
    smiles: str
    aqueous_logs: float         # log10(mol/L); more negative = less soluble
    bbb_probability: float      # 0..1
    herg_risk: str              # low / medium / high
    gi_absorption: str          # high / low
    sa_score_lite: float        # 1 (easy) .. 10 (hard)
    drug_like: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _esol(mol) -> float:
    """Delaney ESOL 2004: logS = 0.16 - 0.63*logP - 0.0062*MW + 0.066*RB - 0.74*AP"""
    logp = Crippen.MolLogP(mol)
    mw = Descriptors.MolWt(mol)
    rotb = Lipinski.NumRotatableBonds(mol)
    n_arom = rdMolDescriptors.CalcNumAromaticRings(mol)
    n_heavy = mol.GetNumHeavyAtoms() or 1
    aromatic_proportion = len([a for a in mol.GetAtoms() if a.GetIsAromatic()]) / n_heavy
    return 0.16 - 0.63 * logp - 0.0062 * mw + 0.066 * rotb - 0.74 * aromatic_proportion


def _bbb(mol) -> float:
    """Clark 2003-ish: MW<=400 and TPSA<=90 strongly predicts BBB+."""
    mw = Descriptors.MolWt(mol)
    tpsa = Descriptors.TPSA(mol)
    # Sigmoid on a composite score; gives 0..1.
    score = (400 - mw) / 400 * 0.5 + (90 - tpsa) / 90 * 0.5
    import math
    return max(0.0, min(1.0, 1 / (1 + math.exp(-4 * score))))


def _herg(mol) -> str:
    """hERG risk heuristic: basic N + logP>=3.7 + MW>=250 raises risk (Aronov 2005)."""
    has_basic_n = any(
        a.GetSymbol() == "N" and a.GetFormalCharge() == 0 and a.GetTotalNumHs() >= 1
        and not a.GetIsAromatic()
        for a in mol.GetAtoms()
    )
    logp = Crippen.MolLogP(mol)
    mw = Descriptors.MolWt(mol)
    score = 0
    if has_basic_n: score += 1
    if logp >= 3.7: score += 1
    if mw >= 250: score += 1
    return ["low", "low", "medium", "high"][score]


def _gi_absorption(mol) -> str:
    """SwissADME BOILED-Egg simplification: TPSA<=131.6 + logP<=5.88 -> high."""
    tpsa = Descriptors.TPSA(mol)
    logp = Crippen.MolLogP(mol)
    return "high" if (tpsa <= 131.6 and logp <= 5.88) else "low"


def _sa_score_lite(mol) -> float:
    """Not Ertl/Schuffenhauer SA; a cheap 1..10 complexity proxy."""
    rings = rdMolDescriptors.CalcNumRings(mol)
    fused = rdMolDescriptors.CalcNumAromaticRings(mol)
    stereo = sum(1 for a in mol.GetAtoms() if a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED)
    heavy = mol.GetNumHeavyAtoms()
    raw = 1 + 0.3 * rings + 0.2 * fused + 0.5 * stereo + max(0, (heavy - 25) * 0.05)
    return round(min(10.0, max(1.0, raw)), 2)


def predict_one(smiles: str) -> Prediction:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")
    bbb = _bbb(mol)
    mw = Descriptors.MolWt(mol)
    logp = Crippen.MolLogP(mol)
    hbd = Lipinski.NumHDonors(mol)
    hba = Lipinski.NumHAcceptors(mol)
    drug_like = (mw <= 500 and logp <= 5 and hbd <= 5 and hba <= 10)
    return Prediction(
        smiles=smiles,
        aqueous_logs=round(_esol(mol), 3),
        bbb_probability=round(bbb, 3),
        herg_risk=_herg(mol),
        gi_absorption=_gi_absorption(mol),
        sa_score_lite=_sa_score_lite(mol),
        drug_like=drug_like,
    )


def predict_batch(smiles: list[str]) -> list[dict]:
    return [predict_one(s).to_dict() for s in smiles]
