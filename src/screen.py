"""Drug-likeness screening report.

Takes a list of SMILES and produces a single structured report that medchem
teams actually want: pass/fail on Lipinski, Veber, PAINS, lead-likeness,
fragment-likeness, Ghose, Egan. Higher perceived value than raw descriptors.

Exposed via POST /screen — charges 5 SMILES/molecule against paid quota.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from src import compute


@dataclass
class ScreenResult:
    smiles: str
    mw: float
    logp: float
    tpsa: float
    hbd: int
    hba: int
    rotb: int
    qed: float
    lipinski: bool
    veber: bool
    ghose: bool
    egan: bool
    lead_like: bool
    fragment_like: bool
    pains_hit: bool
    verdict: str
    flags: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _rules(mw, logp, tpsa, hbd, hba, rotb) -> dict:
    return {
        # Lipinski: MW<=500, logP<=5, HBD<=5, HBA<=10
        "lipinski": (mw <= 500 and logp <= 5 and hbd <= 5 and hba <= 10),
        # Veber: rotb<=10, TPSA<=140
        "veber": (rotb <= 10 and tpsa <= 140),
        # Ghose: 160<=MW<=480, -0.4<=logP<=5.6
        "ghose": (160 <= mw <= 480 and -0.4 <= logp <= 5.6),
        # Egan: logP<=5.88, TPSA<=131.6
        "egan": (logp <= 5.88 and tpsa <= 131.6),
        # Lead-likeness (Oprea): MW<=450, -3.5<=logP<=4.5, rotb<=10
        "lead_like": (mw <= 450 and -3.5 <= logp <= 4.5 and rotb <= 10),
        # Fragment-likeness (Rule of 3): MW<=300, logP<=3, HBD<=3, HBA<=3
        "fragment_like": (mw <= 300 and logp <= 3 and hbd <= 3 and hba <= 3),
    }


def screen_one(smi: str) -> ScreenResult:
    r = compute.compute_molecule(cid=-1, smiles=smi).to_dict()
    rules = _rules(r["mw"], r["logp"], r["tpsa"], r["hbd"], r["hba"],
                   r["rotatable_bonds"])
    pains = bool(r.get("pains_hit"))
    flags: list[str] = []
    if not rules["lipinski"]: flags.append("violates_lipinski")
    if not rules["veber"]: flags.append("violates_veber")
    if pains: flags.append("pains_alert")
    if r["mw"] > 600: flags.append("high_mw")
    if r["logp"] > 6: flags.append("high_logp")

    # Verdict: any PAINS = reject; pass Lipinski+Veber = pass; else review.
    if pains:
        verdict = "reject"
    elif rules["lipinski"] and rules["veber"]:
        verdict = "pass"
    else:
        verdict = "review"

    return ScreenResult(
        smiles=smi, mw=r["mw"], logp=r["logp"], tpsa=r["tpsa"],
        hbd=r["hbd"], hba=r["hba"], rotb=r["rotatable_bonds"],
        qed=r["qed"],
        lipinski=rules["lipinski"], veber=rules["veber"],
        ghose=rules["ghose"], egan=rules["egan"],
        lead_like=rules["lead_like"], fragment_like=rules["fragment_like"],
        pains_hit=pains, verdict=verdict, flags=flags,
    )


def screen_batch(smiles: List[str]) -> dict:
    results = [screen_one(s).to_dict() for s in smiles]
    summary = {
        "n": len(results),
        "passed": sum(1 for r in results if r["verdict"] == "pass"),
        "review": sum(1 for r in results if r["verdict"] == "review"),
        "rejected": sum(1 for r in results if r["verdict"] == "reject"),
        "pains_hits": sum(1 for r in results if r["pains_hit"]),
        "fragment_like": sum(1 for r in results if r["fragment_like"]),
        "lead_like": sum(1 for r in results if r["lead_like"]),
    }
    return {"summary": summary, "results": results}
