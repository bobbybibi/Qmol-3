"""Simple 1-step retrosynthesis by template matching.

We don't ship a trained neural net here — instead we apply a small
hand-curated library of SMARTS-based disconnection rules (amide, ester,
Suzuki, reductive amination, SN2 halide displacement, ether, urea, sulfonamide).

This is good enough for the "give me ideas" use case that is 80% of what
medchem retro tools are asked for. Customers who want AiZynthFinder-class
output can bring their own model behind our API later.

Each rule returns `(reactants_smiles, confidence, reaction_name)`.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

from rdkit import Chem
from rdkit.Chem import AllChem


# Each template is written in retro direction: product >> precursors.
# Atom constraints are intentionally a little loose (N not NH1) to match
# real drug-like fragments that may have aromatic or substituted nitrogens.
# (template_smirks, name, confidence_0_1)
_TEMPLATES: list[tuple[str, str, float]] = [
    # Amide: R-C(=O)-N(-R')- <- R-COOH + R'-NH
    ("[C:1](=[O:2])[N:3][C,c:4]>>[C:1](=[O:2])[OH].[N:3][C,c:4]",
     "amide_coupling", 0.9),
    # Ester: R-C(=O)-O-R' <- R-COOH + R'-OH
    ("[C:1](=[O:2])[O:3][C,c:4]>>[C:1](=[O:2])[OH].[O:3][C,c:4]",
     "esterification", 0.85),
    # Aryl ether: Ar-O-C <- Ar-OH + Cl-C
    ("[c:1][O:2][C:3]>>[c:1][OH].[Cl][C:3]", "williamson_ether", 0.7),
    # Suzuki: aryl-aryl <- aryl-B(OH)2 + aryl-Br
    ("[c:1]-[c:2]>>[c:1]B(O)O.[Br][c:2]", "suzuki_coupling", 0.75),
    # Reductive amination: R-CH2-N(-R')- <- R-CHO + R'-NH
    ("[CH2:1][N:2][C,c:3]>>[CH:1]=O.[N:2][C,c:3]",
     "reductive_amination", 0.8),
    # Sulfonamide: R-S(=O)(=O)-N(-R')- <- R-S(=O)(=O)-Cl + R'-NH
    ("[S:1](=[O:2])(=[O:3])[N:4][C,c:5]>>"
     "[S:1](=[O:2])(=[O:3])[Cl].[N:4][C,c:5]",
     "sulfonamide_formation", 0.85),
]


@dataclass
class RetroStep:
    name: str
    confidence: float
    reactants: list[str]

    def to_dict(self) -> dict:
        return {"name": self.name, "confidence": self.confidence,
                "reactants": self.reactants}


def _split_components(smi: str) -> list[str]:
    return [s for s in smi.split(".") if s]


def one_step(smiles: str, max_results: int = 20) -> list[RetroStep]:
    """Return up to `max_results` plausible precursor sets for `smiles`."""
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise ValueError(f"Invalid SMILES: {smiles}")
    out: list[RetroStep] = []
    seen: set[tuple[str, ...]] = set()
    for smirks, name, conf in _TEMPLATES:
        rxn = AllChem.ReactionFromSmarts(smirks)
        if rxn is None:
            continue
        try:
            outcomes = rxn.RunReactants((m,))
        except Exception:
            continue
        for outcome in outcomes:
            reactants: list[str] = []
            bad = False
            for r in outcome:
                try:
                    Chem.SanitizeMol(r)
                except Exception:
                    bad = True
                    break
                s = Chem.MolToSmiles(r)
                if not s:
                    bad = True
                    break
                reactants.extend(_split_components(s))
            if bad or not reactants:
                continue
            key = tuple(sorted(reactants) + [name])
            if key in seen:
                continue
            seen.add(key)
            out.append(RetroStep(name=name, confidence=conf,
                                 reactants=sorted(reactants)))
            if len(out) >= max_results:
                return out
    return out
