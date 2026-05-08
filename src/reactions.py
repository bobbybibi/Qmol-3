"""Reaction-based combinatorial library enumeration.

Takes a SMARTS reaction + lists of reagents (one per reactant) and generates
all product SMILES. This is the #1 thing medchem teams build in-house
repeatedly — selling it as a hosted endpoint is pure leverage.

Examples the endpoint supports out of the box (named templates):
  amide        amine + carboxylic acid -> amide
  suzuki       aryl halide + boronic acid -> biaryl
  sn2          amine + alkyl halide -> secondary amine
  click        azide + alkyne -> 1,2,3-triazole
  reductive    amine + aldehyde -> secondary amine
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Sequence

from rdkit import Chem
from rdkit.Chem import AllChem

TEMPLATES = {
    "amide":       "[C:1](=[O:2])[O;H1,-:3].[N;H1,H2,H3;!$(NC=O):4]"
                   ">>[C:1](=[O:2])[N:4]",
    "suzuki":      "[c:1][Br,Cl,I:2].[B:3]([O:4])([O:5])[c:6]"
                   ">>[c:1][c:6]",
    "sn2":         "[N;H1,H2;!$(NC=O):1].[C;X4:2][Br,Cl,I]"
                   ">>[N:1][C:2]",
    "click":       "[C:1]#[C:2].[N-:3]=[N+:4]=[N:5][C:6]"
                   ">>[C:1]1=[C:2][N:5]([C:6])[N:4]=[N:3]1",
    "reductive":   "[C:1](=[O:2])[H].[N;H1,H2;!$(NC=O):3]"
                   ">>[C:1][N:3]",
}


@dataclass
class EnumResult:
    template: str
    n_reactants: int
    n_products: int
    products: list[str]

    def to_dict(self) -> dict:
        return {
            "template": self.template,
            "n_reactants": self.n_reactants,
            "n_products": self.n_products,
            "products": self.products,
        }


def _resolve_smarts(template: str) -> str:
    if template in TEMPLATES:
        return TEMPLATES[template]
    # Otherwise assume caller passed raw SMARTS.
    return template


def enumerate_library(template: str, reagents: Sequence[Sequence[str]],
                      max_products: int = 10_000,
                      unique: bool = True) -> EnumResult:
    """Enumerate products from a SMARTS or named template + reagent lists.

    ``reagents`` must have one list per reactant in the template.
    """
    smarts = _resolve_smarts(template)
    rxn = AllChem.ReactionFromSmarts(smarts)
    if rxn is None:
        raise ValueError(f"Invalid reaction SMARTS / template: {template!r}")

    n_req = rxn.GetNumReactantTemplates()
    if len(reagents) != n_req:
        raise ValueError(f"Template needs {n_req} reactant lists, got {len(reagents)}")

    mol_lists: list[list] = []
    total_combos = 1
    for i, lst in enumerate(reagents):
        mols = []
        for smi in lst:
            m = Chem.MolFromSmiles(smi)
            if m is None:
                raise ValueError(f"Invalid SMILES in reactant {i}: {smi!r}")
            mols.append(m)
        if not mols:
            raise ValueError(f"Empty reagent list at index {i}")
        mol_lists.append(mols)
        total_combos *= len(mols)
    if total_combos > max_products:
        raise ValueError(
            f"Would generate {total_combos:,} products (max_products={max_products})"
        )

    products: list[str] = []
    seen: set[str] = set()

    def _walk(chosen: list):
        if len(chosen) == n_req:
            try:
                outcomes = rxn.RunReactants(tuple(chosen))
            except Exception:
                return
            for combo in outcomes:
                for mol in combo:
                    try:
                        Chem.SanitizeMol(mol)
                    except Exception:
                        continue
                    smi = Chem.MolToSmiles(mol)
                    if unique and smi in seen:
                        continue
                    seen.add(smi)
                    products.append(smi)
            return
        for m in mol_lists[len(chosen)]:
            _walk(chosen + [m])

    _walk([])
    return EnumResult(
        template=template,
        n_reactants=n_req,
        n_products=len(products),
        products=products,
    )
