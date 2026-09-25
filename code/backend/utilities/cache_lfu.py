"""Small in-memory least-frequently-used answer cache."""


class CacheLFU:
    """Evict the oldest entry when frequencies tie; caller serializes access."""

    def __init__(self, capacity=10):
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("Cache capacity must be positive")
        self.capacity = capacity
        self._entries = {}
        self.hits = self.misses = self.inserts = self.updates = self.evictions = 0

    def get(self, question):
        entry = self._entries.get(question)
        if entry is None:
            self.misses += 1
            return None
        self.hits += 1
        answer, count = entry
        self._entries[question] = (answer, count + 1)
        return answer

    def put(self, question, answer):
        if question in self._entries:
            self.updates += 1
            _, count = self._entries[question]
            self._entries[question] = (answer, count)
            return
        if len(self._entries) >= self.capacity:
            victim = min(self._entries, key=lambda key: self._entries[key][1])
            del self._entries[victim]
            self.evictions += 1
        self._entries[question] = (answer, 1)
        self.inserts += 1

    def stats(self):
        """Caller holds the same lock used for get/put."""
        lookups = self.hits + self.misses
        return {
            'capacity': self.capacity, 'entries': len(self._entries),
            'hits': self.hits, 'misses': self.misses,
            'hit_rate': self.hits / lookups if lookups else 0.0,
            'inserts': self.inserts, 'updates': self.updates,
            'evictions': self.evictions,
        }
