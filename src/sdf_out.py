"""Convert a list of SMILES to a single SDF string.

Symmetry with /upload/compute: customers ship SDF in, ship SDF back out.
"""
from __future__ import annotations
from io import StringIO
from typing import Sequence

from rdkit import Chem


def smiles_to_sdf(smiles: Sequence[str], with_coords: bool = False) -> str:
    """Return an SDF string. Molecules with invalid SMILES are skipped."""
    buf = StringIO()
    writer = Chem.SDWriter(buf)
    for i, smi in enumerate(smiles):
        m = Chem.MolFromSmiles(smi)
        if m is None:
            continue
        if with_coords:
            from rdkit.Chem import AllChem
            mh = Chem.AddHs(m)
            AllChem.EmbedMolecule(mh, randomSeed=42)
            m = mh
        m.SetProp("_Name", f"mol_{i}")
        m.SetProp("SMILES", smi)
        writer.write(m)
    writer.close()
    return buf.getvalue()
