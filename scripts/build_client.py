"""Build the qmol-client PyPI artifact.

Copies qmol_client.py into packaging/qmol-client/ and runs `python -m build`.
Run: python scripts/build_client.py
"""
from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging" / "qmol-client"


def main() -> int:
    shutil.copy2(ROOT / "qmol_client.py", PKG / "qmol_client.py")
    r = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--sdist"],
        cwd=PKG, check=False,
    )
    if r.returncode != 0:
        print("build failed; did you `pip install build`?", file=sys.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
