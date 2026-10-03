"""Small in-memory least-frequently-used answer cache.

Entries live in fixed rows, as in the original prototype: each row stores the
question, its response, an access count starting at 0, and the question's
embedding. A new entry replaces the first row holding the lowest access count.
"""


import math
import time


class CacheLFU:
    """Fixed-row LFU cache; caller serializes access.

    ``ttl_seconds=None`` (the default) disables time-based expiration.
    """

    def __init__(self, capacity=4, ttl_seconds=None, *, clock=time.monotonic):
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("Cache capacity must be positive")
        if ttl_seconds is not None and (
                isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float))
                or not math.isfinite(ttl_seconds) or ttl_seconds <= 0):
            raise ValueError("CACHE_TTL_SECONDS must be a positive finite number")
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._expires = {}
        self.expirations = self.invalidated_entries = self.invalidations = 0
        self.invalidation_reasons = {}
        self.capacity = capacity
        # Each row is [key, answer, access_count, embedding]; row order is stable.
        self._rows = []
        self.semantic_hits = 0
        self.hits = self.misses = self.inserts = self.updates = self.evictions = 0

    @property
    def _entries(self):
        """Read-only view of key -> (answer, access count), in row order."""
        return {row[0]: (row[1], row[2]) for row in self._rows}

    def _row(self, key):
        return next((row for row in self._rows if row[0] == key), None)

    def get(self, question):
        self._expire()
        row = self._row(question)
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        row[2] += 1
        return row[1]

    def put(self, question, answer, embedding=None):
        self._expire()
        if self.ttl_seconds is not None:
            self._expires[question] = self._clock() + self.ttl_seconds
        row = self._row(question)
        if row is not None:
            self.updates += 1
            row[1] = answer
            if embedding is not None:
                row[3] = embedding
            return
        new_row = [question, answer, 0, embedding]
        if len(self._rows) < self.capacity:
            self._rows.append(new_row)
        else:
            # min() returns the first row among equal counts.
            index = min(range(len(self._rows)), key=lambda i: self._rows[i][2])
            self._expires.pop(self._rows[index][0], None)
            self._rows[index] = new_row
            self.evictions += 1
        self.inserts += 1

    def stats(self):
        """Caller holds the same lock used for get/put."""
        self._expire()
        lookups = self.hits + self.misses
        return {
            'exact_hits': self.hits - self.semantic_hits, 'semantic_hits': self.semantic_hits,
            'capacity': self.capacity, 'entries': len(self._rows),
            'hits': self.hits, 'misses': self.misses,
            'hit_rate': self.hits / lookups if lookups else 0.0,
            'inserts': self.inserts, 'updates': self.updates,
            'evictions': self.evictions,
            'ttl_seconds': self.ttl_seconds, 'expirations': self.expirations,
            'invalidations': self.invalidations, 'invalidated_entries': self.invalidated_entries,
            'invalidation_reasons': dict(self.invalidation_reasons),
        }

    def rows(self):
        """Snapshot of each row's question and access count, without responses."""
        self._expire()
        return [{'row': i, 'category': row[0][0], 'question': row[0][1], 'access_count': row[2]}
                for i, row in enumerate(self._rows)]

    def contains(self, key):
        """Check fast-path eligibility without changing hit/miss counters."""
        self._expire()
        return self._row(key) is not None

    def candidates(self, category):
        """Snapshot (key, answer, embedding) for revalidation after unlocked work."""
        self._expire()
        return [(row[0], row[1], row[3]) for row in self._rows if row[0][0] == category]

    def semantic_hit(self, key, expected):
        self._expire()
        row = self._row(key)
        if row is None or row[1] is not expected:
            return None
        row[2] += 1
        self.hits += 1
        self.misses -= 1  # Convert this request's exact miss into a semantic hit.
        self.semantic_hits += 1
        return row[1]

    def _expire(self):
        if self.ttl_seconds is None:
            return
        now = self._clock()
        expired = {key for key, deadline in self._expires.items() if now >= deadline}
        if expired:
            self._rows = [row for row in self._rows if row[0] not in expired]
            for key in expired:
                del self._expires[key]
            self.expirations += len(expired)

    def clear(self, reason):
        self._expire()
        removed = len(self._rows)
        self._rows.clear()
        self._expires.clear()
        self.invalidations += 1
        self.invalidated_entries += removed
        self.invalidation_reasons[reason] = self.invalidation_reasons.get(reason, 0) + 1
        return removed
