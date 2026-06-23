"""Deduplicate a SMILES list by InChIKey.

A constant data-prep need: collapse a list of SMILES (spelling variants, exact
duplicates, different input forms) to unique structures keyed by InChIKey, and
record which input indices map to each unique structure. Structures whose
InChIKey can't be generated fall back to a canonical-SMILES key.

Exposed via ``POST /dedup`` — charges 1 SMILES/input molecule.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem import inchi as _inchi


@dataclass
class DedupResult:
    n_input: int
    n_unique: int
    n_duplicates: int          # n_valid - n_unique
    invalid: list[int]         # input indices that failed to parse
    groups: list[dict]         # [{inchikey, canonical_smiles, count, input_indices}]

    def to_dict(self) -> dict:
        return asdict(self)


def dedup(smiles: List[str]) -> DedupResult:
    groups: dict[str, dict] = {}
    order: list[str] = []
    invalid: list[int] = []
    n_valid = 0

    for i, s in enumerate(smiles):
        m = Chem.MolFromSmiles(s)
        if m is None:
            invalid.append(i)
            continue
        n_valid += 1
        canon = Chem.MolToSmiles(m)
        try:
            ikey = _inchi.MolToInchiKey(m) or None
        except Exception:  # noqa: BLE001
            ikey = None
        key = ikey if ikey else f"SMI:{canon}"
        if key not in groups:
            groups[key] = {
                "inchikey": ikey,
                "canonical_smiles": canon,
                "count": 0,
                "input_indices": [],
            }
            order.append(key)
        groups[key]["count"] += 1
        groups[key]["input_indices"].append(i)

    out = [groups[k] for k in order]
    return DedupResult(
        n_input=len(smiles), n_unique=len(out),
        n_duplicates=n_valid - len(out), invalid=invalid, groups=out,
    )
