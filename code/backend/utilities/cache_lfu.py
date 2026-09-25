"""Small in-memory least-frequently-used answer cache."""


import math
import time


class CacheLFU:
    """Evict the oldest entry when frequencies tie; caller serializes access."""

    def __init__(self, capacity=10, ttl_seconds=3600, *, clock=time.monotonic):
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("Cache capacity must be positive")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("CACHE_TTL_SECONDS must be a positive finite number")
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._expires = {}
        self.expirations = self.invalidated_entries = self.invalidations = 0
        self.invalidation_reasons = {}
        self.capacity = capacity
        self._entries = {}
        self.semantic_hits = 0
        self.hits = self.misses = self.inserts = self.updates = self.evictions = 0

    def get(self, question):
        self._expire()
        entry = self._entries.get(question)
        if entry is None:
            self.misses += 1
            return None
        self.hits += 1
        answer, count = entry
        self._entries[question] = (answer, count + 1)
        return answer

    def put(self, question, answer):
        self._expire()
        self._expires[question] = self._clock() + self.ttl_seconds
        if question in self._entries:
            self.updates += 1
            _, count = self._entries[question]
            self._entries[question] = (answer, count)
            return
        if len(self._entries) >= self.capacity:
            victim = min(self._entries, key=lambda key: self._entries[key][1])
            del self._entries[victim]
            del self._expires[victim]
            self.evictions += 1
        self._entries[question] = (answer, 1)
        self.inserts += 1

    def stats(self):
        """Caller holds the same lock used for get/put."""
        self._expire()
        lookups = self.hits + self.misses
        return {
            'exact_hits': self.hits - self.semantic_hits, 'semantic_hits': self.semantic_hits,
            'capacity': self.capacity, 'entries': len(self._entries),
            'hits': self.hits, 'misses': self.misses,
            'hit_rate': self.hits / lookups if lookups else 0.0,
            'inserts': self.inserts, 'updates': self.updates,
            'evictions': self.evictions,
            'ttl_seconds': self.ttl_seconds, 'expirations': self.expirations,
            'invalidations': self.invalidations, 'invalidated_entries': self.invalidated_entries,
            'invalidation_reasons': dict(self.invalidation_reasons),
        }

    def candidates(self, category):
        """Snapshot identities for revalidation after unlocked embedding work."""
        self._expire()
        return [(key, answer) for key, (answer, _) in self._entries.items() if key[0] == category]

    def semantic_hit(self, key, expected):
        self._expire()
        entry = self._entries.get(key)
        if entry is None or entry[0] is not expected:
            return None
        answer, count = entry
        self._entries[key] = (answer, count + 1)
        self.hits += 1
        self.misses -= 1  # Convert this request's exact miss into a semantic hit.
        self.semantic_hits += 1
        return answer

    def _expire(self):
        now = self._clock()
        for key in [key for key, deadline in self._expires.items() if now >= deadline]:
            del self._entries[key]
            del self._expires[key]
            self.expirations += 1

    def clear(self, reason):
        self._expire()
        removed = len(self._entries)
        self._entries.clear()
        self._expires.clear()
        self.invalidations += 1
        self.invalidated_entries += removed
        self.invalidation_reasons[reason] = self.invalidation_reasons.get(reason, 0) + 1
        return removed
