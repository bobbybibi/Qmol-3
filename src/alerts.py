"""Structural-alert screening across multiple catalogs.

Flags problematic substructures — assay-interference (PAINS), toxicophores and
reactive/unstable groups (BRENK), and vendor reactive-compound filters (NIH,
ZINC) — using RDKit's FilterCatalogs. ``/screen`` returns a single PAINS
boolean; this reports exactly WHICH alerts fire and from which catalog, the
detail medchem triage actually wants.

Exposed via ``POST /alerts`` — charges 1 SMILES/molecule.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem import FilterCatalog
from rdkit.Chem.FilterCatalog import FilterCatalogParams

_FC = FilterCatalogParams.FilterCatalogs
_CATALOG_TYPES = {
    "PAINS_A": _FC.PAINS_A, "PAINS_B": _FC.PAINS_B, "PAINS_C": _FC.PAINS_C,
    "BRENK": _FC.BRENK, "NIH": _FC.NIH, "ZINC": _FC.ZINC,
}


def _build(catalog_type) -> "FilterCatalog.FilterCatalog":
    p = FilterCatalogParams()
    p.AddCatalog(catalog_type)
    return FilterCatalog.FilterCatalog(p)


# One catalog per set so we can attribute each hit to a named catalog.
_CATALOGS = {name: _build(c) for name, c in _CATALOG_TYPES.items()}
CATALOG_NAMES = tuple(_CATALOG_TYPES.keys())


@dataclass
class AlertResult:
    smiles: str
    n_alerts: int
    alerts: list[dict]        # [{catalog, description}]
    catalogs_hit: list[str]   # distinct catalogs that fired
    clean: bool               # True if nothing fired

    def to_dict(self) -> dict:
        return asdict(self)


def screen_one(smiles: str) -> AlertResult:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")
    alerts: list[dict] = []
    hit: set[str] = set()
    for name, cat in _CATALOGS.items():
        for entry in cat.GetMatches(mol):
            alerts.append({"catalog": name, "description": entry.GetDescription()})
            hit.add(name)
    return AlertResult(
        smiles=smiles, n_alerts=len(alerts), alerts=alerts,
        catalogs_hit=sorted(hit), clean=not alerts,
    )


def screen_batch(smiles: List[str]) -> list[dict]:
    return [screen_one(s).to_dict() for s in smiles]
