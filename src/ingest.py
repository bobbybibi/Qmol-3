"""Approved-source molecular ingestion pipeline."""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

import requests
from rdkit import Chem

import config

log = logging.getLogger(__name__)

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class MoleculeRecord:
    cid: int
    smiles: str
    name: str | None
    formula: str | None
    mw: float | None
    source_name: str = "pubchem"
    source_record_id: str | None = None
    source_license: str = "CC0-1.0"
    ingested_at: str = field(default_factory=_now_iso)
    raw_smiles: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: dict[str, Any] | None = None

    def to_source_row(self) -> dict[str, Any]:
        return {
            "cid": self.cid,
            "source_name": self.source_name,
            "source_record_id": self.source_record_id or str(self.cid),
            "canonical_smiles": self.smiles,
            "source_license": self.source_license,
            "metadata_json": self.metadata,
            "provenance_json": self.provenance,
            "ingested_at": self.ingested_at,
            "raw_smiles": self.raw_smiles or self.smiles,
        }


@dataclass
class FetchBatch:
    source_name: str
    start_cursor: int
    next_cursor: int
    requested: int
    records: list[MoleculeRecord]


class SourceCollector:
    source_name = ""

    def fetch_batch(self, start_cursor: int, batch_size: int) -> FetchBatch:
        raise NotImplementedError


def _get(url: str, retries: int = 3, backoff: float = 1.5) -> dict | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("PubChem fetch failed (%s): %s", attempt, e)
            time.sleep(backoff ** attempt)
    return None


def normalize_record(record: MoleculeRecord) -> MoleculeRecord | None:
    source_cfg = config.APPROVED_SOURCES.get(record.source_name, {})
    allowed = source_cfg.get("license") in config.MOLECULAR_DATA_SPEC["accepted_licenses"]
    if not allowed:
        log.warning("skip source=%s unsupported license=%s",
                    record.source_name, source_cfg.get("license"))
        return None
    raw_smiles = record.raw_smiles or record.smiles
    mol = Chem.MolFromSmiles(raw_smiles)
    if mol is None:
        return None
    canonical = Chem.MolToSmiles(mol, canonical=True)
    record.raw_smiles = raw_smiles
    record.smiles = canonical
    record.source_record_id = record.source_record_id or str(record.cid)
    record.source_license = str(source_cfg.get("license", record.source_license))
    record.metadata = {
        **record.metadata,
        "record_id_field": source_cfg.get("record_id_field", "cid"),
        "data_types": source_cfg.get("data_types", []),
        "approved_for_sale": bool(source_cfg.get("approved_for_sale", False)),
    }
    record.provenance.append(
        {
            "step": "normalize",
            "at": _now_iso(),
            "source": record.source_name,
            "raw_smiles": raw_smiles,
            "canonical_smiles": canonical,
            "license": record.source_license,
        }
    )
    return record


def source_catalog() -> list[dict[str, Any]]:
    out = []
    for source_name, details in config.APPROVED_SOURCES.items():
        out.append({
            "source_name": source_name,
            **details,
            "collector_available": source_name in SOURCE_COLLECTORS,
        })
    return out


class PubChemCollector(SourceCollector):
    source_name = "pubchem"

    def fetch_cid(self, cid: int) -> MoleculeRecord | None:
        url = (
            f"{PUBCHEM_BASE}/compound/cid/{cid}/property/"
            f"ConnectivitySMILES,SMILES,IUPACName,MolecularFormula,MolecularWeight/JSON"
        )
        data = _get(url)
        if not data:
            return None
        try:
            props = data["PropertyTable"]["Properties"][0]
        except (KeyError, IndexError):
            return None
        smiles = (
            props.get("SMILES")
            or props.get("ConnectivitySMILES")
            or props.get("CanonicalSMILES")
        )
        if not smiles:
            return None
        rec = MoleculeRecord(
            cid=cid,
            smiles=smiles,
            name=props.get("IUPACName"),
            formula=props.get("MolecularFormula"),
            mw=float(props["MolecularWeight"]) if props.get("MolecularWeight") else None,
            source_name=self.source_name,
            source_record_id=str(cid),
            raw_smiles=smiles,
            metadata={"iupac_name": props.get("IUPACName")},
            raw_payload=data,
        )
        return normalize_record(rec)

    def fetch_batch(self, start_cursor: int, batch_size: int) -> FetchBatch:
        records: list[MoleculeRecord] = []
        cursor = start_cursor
        batch_end = start_cursor + batch_size
        while cursor < batch_end:
            rec = self.fetch_cid(cursor)
            if rec is not None:
                records.append(rec)
            cursor += 1
            time.sleep(0.25)
        return FetchBatch(
            source_name=self.source_name,
            start_cursor=start_cursor,
            next_cursor=batch_end,
            requested=batch_size,
            records=records,
        )


SOURCE_COLLECTORS: dict[str, SourceCollector] = {
    "pubchem": PubChemCollector(),
}


def fetch_batch(source_name: str, start_cursor: int, batch_size: int) -> FetchBatch:
    collector = SOURCE_COLLECTORS.get(source_name)
    if collector is None:
        raise ValueError(f"no collector registered for source {source_name!r}")
    return collector.fetch_batch(start_cursor, batch_size)


def fetch_cid(cid: int) -> MoleculeRecord | None:
    return SOURCE_COLLECTORS["pubchem"].fetch_cid(cid)  # type: ignore[attr-defined]


def iter_source_records(source_name: str, start_cursor: int,
                        batch_size: int = 50) -> Iterator[MoleculeRecord]:
    cursor = start_cursor
    while True:
        batch = fetch_batch(source_name, cursor, batch_size=batch_size)
        cursor = batch.next_cursor
        for rec in batch.records:
            yield rec


def iter_cids(start_cid: int, batch_size: int = 50) -> Iterator[MoleculeRecord]:
    """Yield normalized PubChem records starting at ``start_cid``."""
    yield from iter_source_records("pubchem", start_cid, batch_size=batch_size)


def describe_record(record: MoleculeRecord) -> dict[str, Any]:
    return asdict(record)
