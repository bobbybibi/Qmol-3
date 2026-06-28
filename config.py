"""Global config loaded from .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.resolve()
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

load_dotenv(ROOT / ".env")

HF_TOKEN = os.getenv("HF_TOKEN", "")
HF_REPO_ID = os.getenv("HF_REPO_ID", "")
HF_PRIVATE = os.getenv("HF_PRIVATE", "true").lower() == "true"

PUBCHEM_START_CID = int(os.getenv("PUBCHEM_START_CID", "1"))
PUBCHEM_BATCH_SIZE = int(os.getenv("PUBCHEM_BATCH_SIZE", "50"))
MAX_HEAVY_ATOMS = int(os.getenv("MAX_HEAVY_ATOMS", "8"))

BASIS_SET = os.getenv("BASIS_SET", "sto-3g")
USE_VQE_UP_TO_QUBITS = int(os.getenv("USE_VQE_UP_TO_QUBITS", "12"))
MAX_CPU_SECONDS_PER_MOL = int(os.getenv("MAX_CPU_SECONDS_PER_MOL", "120"))

PUBLISH_EVERY_N_MOLECULES = int(os.getenv("PUBLISH_EVERY_N_MOLECULES", "100"))
SNAPSHOT_EVERY_HOURS = int(os.getenv("SNAPSHOT_EVERY_HOURS", "6"))
INGEST_POLL_SECONDS = float(os.getenv("INGEST_POLL_SECONDS", "30"))

MOLECULAR_DATA_SPEC = {
    "required_fields": ["smiles"],
    "supported_data_types": ["structures", "properties", "bioactivity", "spectra"],
    "accepted_licenses": ["CC0-1.0", "CC BY 4.0", "PDBx/mmCIF Terms"],
}

APPROVED_SOURCES = {
    "pubchem": {
        "name": "PubChem",
        "license": "CC0-1.0",
        "record_id_field": "cid",
        "api_base": "https://pubchem.ncbi.nlm.nih.gov/rest/pug",
        "data_types": ["structures", "properties"],
        "active": True,
        "approved_for_sale": True,
        "sync_interval_minutes": int(os.getenv("PUBCHEM_SYNC_INTERVAL_MINUTES", "30")),
        "batch_size": PUBCHEM_BATCH_SIZE,
        "start_cursor": PUBCHEM_START_CID,
    },
    "chembl": {
        "name": "ChEMBL",
        "license": "CC BY 4.0",
        "record_id_field": "chembl_id",
        "api_base": "https://www.ebi.ac.uk/chembl/api/data",
        "data_types": ["structures", "properties", "bioactivity"],
        "active": False,
        "approved_for_sale": True,
        "sync_interval_minutes": int(os.getenv("CHEMBL_SYNC_INTERVAL_MINUTES", "1440")),
        "batch_size": int(os.getenv("CHEMBL_BATCH_SIZE", "100")),
        "start_cursor": int(os.getenv("CHEMBL_START_ID", "1")),
    },
    "pdb": {
        "name": "Protein Data Bank",
        "license": "PDBx/mmCIF Terms",
        "record_id_field": "pdb_id",
        "api_base": "https://data.rcsb.org/rest/v1/core",
        "data_types": ["structures", "spectra"],
        "active": False,
        "approved_for_sale": False,
        "sync_interval_minutes": int(os.getenv("PDB_SYNC_INTERVAL_MINUTES", "1440")),
        "batch_size": int(os.getenv("PDB_BATCH_SIZE", "25")),
        "start_cursor": int(os.getenv("PDB_START_ID", "1")),
    },
}
ACTIVE_INGEST_SOURCES = [
    name.strip().lower()
    for name in os.getenv("ACTIVE_INGEST_SOURCES", "pubchem").split(",")
    if name.strip()
]

DB_PATH = DATA_DIR / "qmol.sqlite"
PARQUET_PATH = DATA_DIR / "qmol.parquet"
STATE_PATH = DATA_DIR / "state.json"
