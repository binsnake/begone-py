"""A tiny bounded LRU cache for image verdicts.

Keyed by attachment URL so re-posted / duplicate images are evaluated once.
When disabled, every lookup misses and nothing is stored (always recompute).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LRUCache(Generic[K, V]):
    def __init__(self, max_entries: int, enabled: bool = True):
        self.enabled = enabled
        self.max_entries = max(1, int(max_entries))
        self._store: "OrderedDict[K, V]" = OrderedDict()

    def get(self, key: K) -> V | None:
        if not self.enabled:
            return None
        if key not in self._store:
            return None
        self._store.move_to_end(key)  # mark most-recently-used
        return self._store[key]

    def put(self, key: K, value: V) -> None:
        if not self.enabled:
            return
        self._store[key] = value
        self._store.move_to_end(key)
        while len(self._store) > self.max_entries:
            self._store.popitem(last=False)  # evict least-recently-used

    def __len__(self) -> int:
        return len(self._store)
