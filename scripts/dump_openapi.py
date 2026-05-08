"""Dump the live OpenAPI spec to landing/openapi.json.

Run: python scripts/dump_openapi.py
"""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import app  # noqa: E402


def main() -> Path:
    spec = app.openapi()
    out = ROOT / "landing" / "openapi.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(spec, indent=2))
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    print(f"paths: {len(spec.get('paths', {}))}")
    return out


if __name__ == "__main__":
    main()
