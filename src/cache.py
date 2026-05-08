"""Tiny thread-safe TTL+LRU cache for compute results.

A huge fraction of customer SMILES are duplicates (same molecule across
tenants, benchmark sets, etc). Caching their descriptor output saves our
CPU budget and makes the service feel instant on repeat workloads.

Keyed by (endpoint, inchikey-of-smiles, extra-tag).
"""
from __future__ import annotations
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from rdkit import Chem

_DEFAULT_MAX = 10_000
_DEFAULT_TTL_SECONDS = 24 * 3600


class LRUCache:
    def __init__(self, max_size: int = _DEFAULT_MAX,
                 ttl_seconds: int = _DEFAULT_TTL_SECONDS):
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return None
            ts, val = item
            if time.time() - ts > self.ttl:
                self._data.pop(key, None)
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return val

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.time(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "size": len(self._data),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl,
                "hits": self.hits,
                "misses": self.misses,
                "hit_ratio": (self.hits / total) if total else 0.0,
            }


# Module-level cache used by the API
COMPUTE_CACHE = LRUCache()


def key_for(smiles: str, tag: str = "compute") -> str:
    """Canonical-key: InChIKey of the SMILES, tagged by endpoint."""
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return f"{tag}:invalid:{smiles}"
    ikey = Chem.MolToInchiKey(m) or Chem.MolToSmiles(m)
    return f"{tag}:{ikey}"


def memoize(tag: str, smiles: str,
            producer: Callable[[], Any]) -> Any:
    """Return cached result for (tag, smiles) or compute + cache."""
    k = key_for(smiles, tag=tag)
    hit = COMPUTE_CACHE.get(k)
    if hit is not None:
        return hit
    val = producer()
    COMPUTE_CACHE.set(k, val)
    return val
