"""Small in-memory least-frequently-used answer cache."""


class CacheLFU:
    """Evict the oldest entry when frequencies tie; caller serializes access."""

    def __init__(self, capacity=10):
        if capacity < 1:
            raise ValueError("Cache capacity must be positive")
        self.capacity = capacity
        self._entries = {}

    def get(self, question):
        entry = self._entries.get(question)
        if entry is None:
            return None
        answer, count = entry
        self._entries[question] = (answer, count + 1)
        return answer

    def put(self, question, answer):
        if question in self._entries:
            _, count = self._entries[question]
            self._entries[question] = (answer, count)
            return
        if len(self._entries) >= self.capacity:
            victim = min(self._entries, key=lambda key: self._entries[key][1])
            del self._entries[victim]
        self._entries[question] = (answer, 1)
