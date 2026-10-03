"""Paraphrase reuse by embedding similarity, guarded by a key-term check."""

from dataclasses import dataclass
import math
import os
import re

from config import load_environment


@dataclass(frozen=True)
class SemanticCacheConfig:
    enabled: bool = True
    # A hit needs similarity strictly greater than this value.
    threshold: float = .75

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise ValueError('SEMANTIC_CACHE_ENABLED must be true or false')
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, (int, float)) or not math.isfinite(self.threshold) or not 0 <= self.threshold < 1:
            raise ValueError('SEMANTIC_CACHE_THRESHOLD must be in [0, 1)')

    @classmethod
    def from_environment(cls):
        load_environment()
        enabled = os.getenv('SEMANTIC_CACHE_ENABLED', 'true').lower().strip()
        if enabled not in {'true', 'false'}:
            raise ValueError('SEMANTIC_CACHE_ENABLED must be true or false')
        try:
            threshold = float(os.getenv('SEMANTIC_CACHE_THRESHOLD', '.75'))
        except ValueError as error:
            raise ValueError('SEMANTIC_CACHE_THRESHOLD must be in [0, 1)') from error
        return cls(enabled == 'true', threshold)


# Words that reverse or narrow a question's meaning must agree on both sides.
CONTRAST_WORDS = frozenset({'not', 'no', 'never', 'without', 'advantage', 'advantages',
                            'disadvantage', 'disadvantages'})


def _tokens(question):
    return re.findall(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*', question)


def key_terms(question):
    """Technical identifiers that similarity alone cannot tell apart.

    Acronyms (SISD, CC-NUMA), hyphenated terms (write-invalidate) and tokens with
    digits (L1) count, plus contrast words such as "not" or "disadvantages".
    """
    terms = set()
    for token in _tokens(question):
        if (sum(c.isupper() for c in token) >= 2 or '-' in token
                or any(c.isdigit() for c in token) or token.casefold() in CONTRAST_WORDS):
            terms.add(token.casefold())
    return terms


def compatible(left, right):
    """A hit needs every key term in either question to appear in both.

    This blocks near-identical topic names (NC-NUMA vs CC-NUMA, SISD vs SIMD)
    whose embeddings are similar, while plain paraphrases rely on similarity.
    """
    left_tokens = {t.casefold() for t in _tokens(left)}
    right_tokens = {t.casefold() for t in _tokens(right)}
    return (key_terms(left) | key_terms(right)) <= (left_tokens & right_tokens)


def cosine(left, right):
    if len(left) != len(right) or not len(left):
        return None
    if not all(math.isfinite(float(v)) for vector in (left, right) for v in vector):
        return None
    denominator = math.sqrt(sum(float(v)**2 for v in left) * sum(float(v)**2 for v in right))
    if not denominator:
        return None
    return max(-1., min(1., sum(float(a)*float(b) for a, b in zip(left, right)) / denominator))
