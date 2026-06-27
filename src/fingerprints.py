"""Molecular fingerprint generation for ML / similarity pipelines.

Q-Mol already computes ECFP/Morgan internally (for ``/similarity`` and the
dataset's ``ecfp4_hash``), but customers building their own models want the raw
bit vectors in standard formats. This module exposes the RDKit fingerprint
families they ask for, via the modern ``rdFingerprintGenerator`` API (no
deprecation warnings):

  morgan    ECFP-style circular fingerprint (radius configurable; radius 2 == ECFP4)
  rdkit     RDKit topological / path-based fingerprint
  atompair  Atom-pair fingerprint
  torsion   Topological-torsion fingerprint
  maccs     166 MACCS structural keys (fixed 167-bit width; n_bits/radius ignored)

Each molecule returns the on-bit indices (sparse) and/or a base64-encoded bit
vector (dense, fixed width). The base64 form round-trips through
``DataStructs.ExplicitBitVect`` / ``CreateFromBitString`` on the client side.

Exposed via ``POST /fingerprints`` — charges 1 SMILES/molecule against quota.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem import rdFingerprintGenerator, MACCSkeys

# Supported fingerprint kinds and output encodings.
KINDS = ("morgan", "rdkit", "atompair", "torsion", "maccs")
OUTPUTS = ("bits", "base64", "both")

# MACCS keys are a fixed-width structural key set; radius/n_bits don't apply.
_MACCS = "maccs"


@dataclass
class Fingerprint:
    smiles: str
    kind: str
    n_bits: int          # actual width of the returned vector
    n_on_bits: int
    bits: list[int] | None      # sorted on-bit indices (when requested)
    base64: str | None          # base64 ExplicitBitVect (when requested)

    def to_dict(self) -> dict:
        return asdict(self)


def _generator(kind: str, n_bits: int, radius: int):
    if kind == "morgan":
        return rdFingerprintGenerator.GetMorganGenerator(radius=radius, fpSize=n_bits)
    if kind == "rdkit":
        return rdFingerprintGenerator.GetRDKitFPGenerator(fpSize=n_bits)
    if kind == "atompair":
        return rdFingerprintGenerator.GetAtomPairGenerator(fpSize=n_bits)
    if kind == "torsion":
        return rdFingerprintGenerator.GetTopologicalTorsionGenerator(fpSize=n_bits)
    raise ValueError(f"unknown fingerprint kind: {kind!r}")


def _bitvect(mol: Chem.Mol, kind: str, n_bits: int, radius: int):
    if kind == _MACCS:
        return MACCSkeys.GenMACCSKeys(mol)
    return _generator(kind, n_bits, radius).GetFingerprint(mol)


def compute_one(smiles: str, kind: str = "morgan", n_bits: int = 2048,
                radius: int = 2, output: str = "bits") -> Fingerprint:
    kind = kind.lower()
    output = output.lower()
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; choose from {list(KINDS)}")
    if output not in OUTPUTS:
        raise ValueError(f"unknown output {output!r}; choose from {list(OUTPUTS)}")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")

    fp = _bitvect(mol, kind, n_bits, radius)
    on = list(fp.GetOnBits())
    want_bits = output in ("bits", "both")
    want_b64 = output in ("base64", "both")
    return Fingerprint(
        smiles=smiles,
        kind=kind,
        n_bits=fp.GetNumBits(),
        n_on_bits=len(on),
        bits=[int(b) for b in on] if want_bits else None,
        base64=fp.ToBase64() if want_b64 else None,
    )


def compute_batch(smiles: List[str], kind: str = "morgan", n_bits: int = 2048,
                  radius: int = 2, output: str = "bits") -> list[dict]:
    return [compute_one(s, kind, n_bits, radius, output).to_dict() for s in smiles]
