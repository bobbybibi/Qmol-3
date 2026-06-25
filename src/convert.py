"""Identifier / format conversion.

The registration / dedup / cross-reference utility: turn a structure into its
canonical SMILES (dedupes input variants), InChI, InChIKey (the standard key for
matching a structure across databases), and optionally a MolBlock. Accepts
SMILES by default; set ``input_format="inchi"`` to convert *from* InChI.

Exposed via ``POST /convert`` — charges 1 SMILES/molecule.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem import inchi as _inchi

INPUT_FORMATS = ("smiles", "inchi")


@dataclass
class Conversion:
    input: str
    canonical_smiles: str
    inchi: str | None
    inchikey: str | None
    molblock: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _parse(value: str, input_format: str):
    if input_format == "smiles":
        return Chem.MolFromSmiles(value)
    return _inchi.MolFromInchi(value)


def convert_one(value: str, input_format: str = "smiles",
                with_molblock: bool = False) -> Conversion:
    input_format = input_format.lower()
    if input_format not in INPUT_FORMATS:
        raise ValueError(
            f"unknown input_format {input_format!r}; choose from {list(INPUT_FORMATS)}")
    mol = _parse(value, input_format)
    if mol is None:
        raise ValueError(f"could not parse {input_format}: {value!r}")
    try:
        ich = _inchi.MolToInchi(mol) or None
    except Exception:  # noqa: BLE001
        ich = None
    try:
        ikey = _inchi.MolToInchiKey(mol) or None
    except Exception:  # noqa: BLE001
        ikey = None
    return Conversion(
        input=value,
        canonical_smiles=Chem.MolToSmiles(mol),
        inchi=ich,
        inchikey=ikey,
        molblock=Chem.MolToMolBlock(mol) if with_molblock else None,
    )


def convert_batch(values: List[str], input_format: str = "smiles",
                  with_molblock: bool = False) -> list[dict]:
    return [convert_one(v, input_format, with_molblock).to_dict() for v in values]
