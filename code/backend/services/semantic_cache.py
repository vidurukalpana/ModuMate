"""Conservative paraphrase reuse; similarity alone never authorizes a hit."""

from dataclasses import dataclass
import math
import os
import re

from config import load_environment


@dataclass(frozen=True)
class SemanticCacheConfig:
    enabled: bool = False
    threshold: float = .90

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise ValueError('SEMANTIC_CACHE_ENABLED must be true or false')
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, (int, float)) or not math.isfinite(self.threshold) or not 0 < self.threshold <= 1:
            raise ValueError('SEMANTIC_CACHE_THRESHOLD must be in (0, 1]')

    @classmethod
    def from_environment(cls):
        load_environment()
        enabled = os.getenv('SEMANTIC_CACHE_ENABLED', 'false').lower().strip()
        if enabled not in {'true', 'false'}:
            raise ValueError('SEMANTIC_CACHE_ENABLED must be true or false')
        try:
            threshold = float(os.getenv('SEMANTIC_CACHE_THRESHOLD', '.90'))
        except ValueError as error:
            raise ValueError('SEMANTIC_CACHE_THRESHOLD must be in (0, 1]') from error
        return cls(enabled == 'true', threshold)


def question_signature(question):
    """Only a small, explicit set of equivalent question forms is eligible.

    Preserve all subject words, negation, identifiers, quantities and ordering.
    Unknown forms miss safely rather than guessing their intent.
    """
    text = ' '.join(question.casefold().strip().rstrip('?.!').split())
    patterns = [
        ('expansion', r'what does (.+) stand for'),
        ('expansion', r'what is the full form of (.+)'),
        ('definition', r'what is (.+)'),
        ('definition', r'define (.+)'),
        ('advantages', r'(?:what are the advantages of|list the advantages of) (.+)'),
        ('disadvantages', r'(?:what are the disadvantages of|list the disadvantages of) (.+)'),
    ]
    for intent, pattern in patterns:
        match = re.fullmatch(pattern, text)
        if match:
            return intent, match[1]
    return None


def compatible(left, right):
    signature = question_signature(left)
    return signature is not None and signature == question_signature(right)


def cosine(left, right):
    if len(left) != len(right) or not len(left):
        return None
    if not all(math.isfinite(float(v)) for vector in (left, right) for v in vector):
        return None
    denominator = math.sqrt(sum(float(v)**2 for v in left) * sum(float(v)**2 for v in right))
    if not denominator:
        return None
    return max(-1., min(1., sum(float(a)*float(b) for a, b in zip(left, right)) / denominator))
