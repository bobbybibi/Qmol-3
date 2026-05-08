"""qmol_client — tiny Python SDK that buyers can pip install.

    pip install qmol-client
    export QMOL_API_KEY=qmol_xxx
    python -c "from qmol_client import compute; print(compute(['CCO']))"

Zero dependencies beyond `requests`. Kept in the repo so tests can import it.
"""
from __future__ import annotations
import os
from typing import Iterable, Sequence

import requests

DEFAULT_BASE = os.getenv("QMOL_API_URL", "https://qua-22p1.onrender.com")


class QmolError(Exception):
    pass


class Client:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 timeout: float = 60.0):
        self.api_key = api_key or os.getenv("QMOL_API_KEY")
        self.base = (base_url or DEFAULT_BASE).rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h = {"content-type": "application/json"}
        if self.api_key:
            h["x-api-key"] = self.api_key
        return h

    def compute(self, smiles: Sequence[str], premium: bool | None = None) -> list[dict]:
        """Compute descriptors. Auto-picks premium endpoint if api_key is set."""
        endpoint = "/compute/premium" if (premium or self.api_key) else "/compute"
        r = requests.post(
            self.base + endpoint,
            json={"smiles": list(smiles)},
            headers=self._headers(),
            timeout=self.timeout,
        )
        if r.status_code == 402:
            raise QmolError(f"Quota exceeded: {r.json().get('detail')}")
        if r.status_code == 401:
            raise QmolError("Invalid or missing API key")
        r.raise_for_status()
        return r.json()["results"]

    def compute_iter(self, smiles: Iterable[str], batch_size: int = 500):
        """Yield descriptor dicts in batches, good for very large inputs."""
        buf: list[str] = []
        for s in smiles:
            buf.append(s)
            if len(buf) >= batch_size:
                yield from self.compute(buf)
                buf = []
        if buf:
            yield from self.compute(buf)

    def similarity(self, query: str, top_k: int = 10) -> list[dict]:
        r = requests.post(self.base + "/similarity",
                          json={"smiles": query, "top_k": top_k},
                          headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("hits", [])

    def screen(self, smiles: Sequence[str]) -> list[dict]:
        r = requests.post(self.base + "/screen",
                          json={"smiles": list(smiles)},
                          headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        return r.json()["results"]

    def standardize(self, smiles: Sequence[str]) -> list[dict]:
        r = requests.post(self.base + "/standardize",
                          json={"smiles": list(smiles)},
                          headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        return r.json()["results"]

    def predict(self, smiles: Sequence[str]) -> list[dict]:
        r = requests.post(self.base + "/predict",
                          json={"smiles": list(smiles)},
                          headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        return r.json()["results"]

    def usage(self) -> dict:
        if not self.api_key:
            raise QmolError("usage() requires an API key")
        r = requests.get(self.base + "/usage", headers=self._headers(),
                         timeout=self.timeout)
        r.raise_for_status()
        return r.json()


# Public aliases used in README examples
QMolClient = Client


def compute(smiles: Sequence[str], api_key: str | None = None,
            base_url: str | None = None) -> list[dict]:
    """Module-level convenience wrapper."""
    return Client(api_key=api_key, base_url=base_url).compute(smiles)


def _cli_main() -> None:
    """Minimal CLI for the pip package: `qmol compute SMILES...`."""
    import argparse
    import json
    import sys

    p = argparse.ArgumentParser(prog="qmol")
    sub = p.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("compute")
    pc.add_argument("smiles", nargs="+")
    ps = sub.add_parser("similarity")
    ps.add_argument("smiles")
    ps.add_argument("--top-k", type=int, default=10)
    pst = sub.add_parser("standardize")
    pst.add_argument("smiles", nargs="+")
    psc = sub.add_parser("screen")
    psc.add_argument("smiles", nargs="+")
    pp = sub.add_parser("predict")
    pp.add_argument("smiles", nargs="+")

    args = p.parse_args()
    c = Client()
    if args.cmd == "compute":
        out = c.compute(args.smiles)
    elif args.cmd == "similarity":
        out = c.similarity(args.smiles, top_k=args.top_k)
    elif args.cmd == "standardize":
        out = c.standardize(args.smiles)
    elif args.cmd == "screen":
        out = c.screen(args.smiles)
    elif args.cmd == "predict":
        out = c.predict(args.smiles)
    else:
        p.print_help()
        sys.exit(2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    _cli_main()
