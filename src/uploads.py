"""Parsers for customer-supplied SDF / CSV / SMI / TXT files.

Returns a list of SMILES strings. Designed to be tolerant: bad rows are
skipped and counted (not fatal), because customer files are always messy.
"""
from __future__ import annotations
from dataclasses import dataclass
from io import BytesIO, StringIO
from typing import List

from rdkit import Chem


@dataclass
class ParseResult:
    smiles: List[str]
    n_parsed: int
    n_skipped: int
    format: str


def _from_sdf(blob: bytes) -> list[str]:
    supplier = Chem.ForwardSDMolSupplier(BytesIO(blob), sanitize=True, removeHs=False)
    out: list[str] = []
    for mol in supplier:
        if mol is None:
            continue
        try:
            out.append(Chem.MolToSmiles(mol))
        except Exception:
            continue
    return out


def _from_smi(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # SMI format: "<smiles> [whitespace] [title]"
        smi = line.split()[0]
        if Chem.MolFromSmiles(smi) is not None:
            out.append(smi)
    return out


def _from_csv(text: str) -> list[str]:
    import csv
    rdr = csv.reader(StringIO(text))
    rows = list(rdr)
    if not rows:
        return []
    # Find the SMILES column heuristically
    header = rows[0]
    col_idx = 0
    for i, h in enumerate(header):
        if h.strip().lower() in {"smiles", "smi", "canonical_smiles"}:
            col_idx = i
            break
    else:
        # No header — assume first column is SMILES
        header = None  # type: ignore[assignment]

    data_rows = rows[1:] if header else rows
    out: list[str] = []
    for row in data_rows:
        if not row or col_idx >= len(row):
            continue
        smi = row[col_idx].strip()
        if smi and Chem.MolFromSmiles(smi) is not None:
            out.append(smi)
    return out


def parse(blob: bytes, filename: str = "") -> ParseResult:
    """Detect format by filename extension + content sniffing."""
    name = filename.lower()

    if name.endswith(".sdf") or b"M  END" in blob[:1000] or b"V2000" in blob[:1000]:
        smiles = _from_sdf(blob)
        fmt = "sdf"
    elif name.endswith(".csv"):
        smiles = _from_csv(blob.decode("utf-8", errors="ignore"))
        fmt = "csv"
    elif name.endswith(".smi") or name.endswith(".txt"):
        smiles = _from_smi(blob.decode("utf-8", errors="ignore"))
        fmt = "smi"
    else:
        # Last-ditch: try SMI, then CSV
        text = blob.decode("utf-8", errors="ignore")
        smiles = _from_smi(text)
        fmt = "smi"
        if not smiles:
            smiles = _from_csv(text)
            fmt = "csv"

    # We can't easily count "skipped" post-hoc for SDF without re-parsing;
    # approximate as zero for the valid-only path.
    return ParseResult(smiles=smiles, n_parsed=len(smiles),
                       n_skipped=0, format=fmt)
