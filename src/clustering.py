"""Butina clustering over a caller-supplied SMILES set.

Groups molecules by ECFP4 Tanimoto *distance* (1 − similarity) using the Butina
"sphere exclusion" algorithm — the standard cheminformatics clusterer for
picking representatives, deduplicating libraries, or summarizing a screen.
Builds directly on the same fingerprints used by /fingerprints and
/similarity/matrix.

Clusters come back largest-first; each cluster's first member is its centroid.

Exposed via ``POST /cluster`` — charges 1 SMILES/input molecule.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List

from rdkit import Chem
from rdkit.Chem import rdFingerprintGenerator, DataStructs
from rdkit.ML.Cluster import Butina

_GEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


@dataclass
class Cluster:
    cluster_id: int
    size: int
    centroid: str             # representative SMILES (first member)
    members: list[int]        # indices into the valid-SMILES list
    member_smiles: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ClusterResult:
    n_input: int
    n_valid: int
    invalid: list[int]        # indices in the *input* that failed to parse
    cutoff: float             # distance cutoff used (1 - Tanimoto)
    n_clusters: int
    smiles: list[str]         # valid SMILES, in index order
    clusters: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


def cluster(smiles: List[str], cutoff: float = 0.4) -> ClusterResult:
    """Cluster ``smiles`` at distance ``cutoff`` (smaller = tighter clusters)."""
    fps, valid_idx, invalid = [], [], []
    for i, s in enumerate(smiles):
        m = Chem.MolFromSmiles(s)
        if m is None:
            invalid.append(i)
            continue
        fps.append(_GEN.GetFingerprint(m))
        valid_idx.append(i)
    if not fps:
        raise ValueError("no valid SMILES to cluster")
    valid_smiles = [smiles[i] for i in valid_idx]
    n = len(fps)

    # Condensed lower-triangle distance list expected by Butina.
    dists: list[float] = []
    for i in range(1, n):
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
        dists.extend(1.0 - x for x in sims)

    raw = Butina.ClusterData(dists, n, cutoff, isDistData=True)
    clusters = []
    for cid, members in enumerate(raw):
        members = list(members)
        clusters.append(Cluster(
            cluster_id=cid,
            size=len(members),
            centroid=valid_smiles[members[0]],
            members=members,
            member_smiles=[valid_smiles[m] for m in members],
        ).to_dict())

    return ClusterResult(
        n_input=len(smiles), n_valid=n, invalid=invalid,
        cutoff=cutoff, n_clusters=len(clusters),
        smiles=valid_smiles, clusters=clusters,
    )
