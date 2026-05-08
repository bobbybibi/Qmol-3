"""Global config loaded from .env"""
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

DB_PATH = DATA_DIR / "qmol.sqlite"
PARQUET_PATH = DATA_DIR / "qmol.parquet"
STATE_PATH = DATA_DIR / "state.json"
