"""Auto-upload the release bundle to an existing Gumroad product.

Setup:
  1. Create a Gumroad account + a digital product (any price). Note the product ID.
  2. Settings -> Advanced -> Generate "Access Token" with `edit_products` scope.
  3. Set in .env:
       GUMROAD_ACCESS_TOKEN=...
       GUMROAD_PRODUCT_ID=...

What this does:
  - Uploads release/qmol_full.parquet and release/qmol_full.csv
    as files attached to your product.
  - Updates the product description with the latest STATS.md.
  - Existing files with the same name are deleted first to avoid duplicates.

Usage:
    python -m src.gumroad_publish
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import requests

API = "https://api.gumroad.com/v2"


def _token() -> str | None:
    return os.getenv("GUMROAD_ACCESS_TOKEN")


def _product_id() -> str | None:
    return os.getenv("GUMROAD_PRODUCT_ID")


def list_files(token: str, product_id: str) -> list[dict]:
    r = requests.get(f"{API}/products/{product_id}",
                     params={"access_token": token}, timeout=30)
    r.raise_for_status()
    return r.json().get("product", {}).get("files", []) or []


def delete_file(token: str, product_id: str, file_id: str) -> None:
    r = requests.delete(
        f"{API}/products/{product_id}/files/{file_id}",
        params={"access_token": token}, timeout=30,
    )
    if r.status_code not in (200, 204, 404):
        print(f"[gumroad] WARN delete {file_id}: {r.status_code} {r.text[:200]}")


def upload_file(token: str, product_id: str, path: Path) -> bool:
    with path.open("rb") as fh:
        r = requests.post(
            f"{API}/products/{product_id}/files",
            params={"access_token": token},
            files={"file": (path.name, fh)},
            timeout=600,
        )
    if not r.ok:
        print(f"[gumroad] upload {path.name} failed: {r.status_code} {r.text[:300]}")
        return False
    print(f"[gumroad] uploaded {path.name}")
    return True


def update_description(token: str, product_id: str, description: str) -> None:
    r = requests.put(
        f"{API}/products/{product_id}",
        params={"access_token": token},
        data={"description": description},
        timeout=30,
    )
    if not r.ok:
        print(f"[gumroad] description update failed: {r.status_code} {r.text[:200]}")
    else:
        print("[gumroad] description updated")


def publish_release(release_dir: Path = Path("release")) -> bool:
    token = _token()
    pid = _product_id()
    if not token or not pid:
        print("[gumroad] GUMROAD_ACCESS_TOKEN or GUMROAD_PRODUCT_ID missing; skipping")
        return False

    targets = [
        release_dir / "qmol_full.parquet",
        release_dir / "qmol_full.csv",
    ]
    targets = [p for p in targets if p.exists()]
    if not targets:
        print("[gumroad] no release files. Run build_release.py first.")
        return False

    existing = list_files(token, pid)
    by_name = {f.get("name") or f.get("file_name"): f.get("id") for f in existing}

    for path in targets:
        fid = by_name.get(path.name)
        if fid:
            delete_file(token, pid, fid)
        if not upload_file(token, pid, path):
            return False

    stats = release_dir / "STATS.md"
    if stats.exists():
        update_description(token, pid, stats.read_text())

    return True


if __name__ == "__main__":
    ok = publish_release()
    sys.exit(0 if ok else 1)
