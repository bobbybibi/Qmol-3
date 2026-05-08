"""Molecule standardization + salt stripping + tautomer canonicalization.

Real-world SMILES from customers are messy: salts, solvates, tautomers,
aromatic ambiguity. This module cleans them before downstream compute.

Exposed via POST /standardize — free (small charge) because good data hygiene
makes everything else we sell more accurate, so we want everyone using it.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem.MolStandardize import rdMolStandardize


@dataclass
class StandardizeResult:
    input: str
    output: str
    changed: bool
    largest_fragment: str
    canonical_tautomer: str
    inchi: str
    inchikey: str
    neutral: str

    def to_dict(self) -> dict:
        return asdict(self)


_TAUTOMERIZER = rdMolStandardize.TautomerEnumerator()
_UNCHARGER = rdMolStandardize.Uncharger()
_LARGEST_FRAG_CHOOSER = rdMolStandardize.LargestFragmentChooser()


def standardize_one(smiles: str) -> StandardizeResult:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")

    # 1) Standardize (normalize functional groups)
    mol = rdMolStandardize.Cleanup(mol)

    # 2) Largest organic fragment (strips counter-ions)
    largest = _LARGEST_FRAG_CHOOSER.choose(mol)
    largest_smi = Chem.MolToSmiles(largest)

    # 3) Neutralize charges
    neutral = _UNCHARGER.uncharge(Chem.Mol(largest))
    neutral_smi = Chem.MolToSmiles(neutral)

    # 4) Canonical tautomer
    taut = _TAUTOMERIZER.Canonicalize(Chem.Mol(neutral))
    taut_smi = Chem.MolToSmiles(taut)

    inchi = Chem.MolToInchi(taut) or ""
    ikey = Chem.MolToInchiKey(taut) or ""

    return StandardizeResult(
        input=smiles,
        output=taut_smi,
        changed=(taut_smi != smiles),
        largest_fragment=largest_smi,
        canonical_tautomer=taut_smi,
        inchi=inchi,
        inchikey=ikey,
        neutral=neutral_smi,
    )


def standardize_batch(smiles: List[str]) -> list[dict]:
    return [standardize_one(s).to_dict() for s in smiles]
