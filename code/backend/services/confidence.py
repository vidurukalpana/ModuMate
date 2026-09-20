"""Explicit acceptance rules for extractive QA; scores are not calibrated odds."""

from dataclasses import dataclass
import math

DEFAULT_MIN_RETRIEVAL_SCORE = 0.5
DEFAULT_MIN_QA_SCORE = 0.5


def valid_score(value, minimum, maximum):
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and minimum <= value <= maximum
    )


@dataclass(frozen=True)
class ConfidencePolicy:
    """Immutable per-service policy so accepted cache entries keep the same rules."""

    min_retrieval_score: float = DEFAULT_MIN_RETRIEVAL_SCORE
    min_qa_score: float = DEFAULT_MIN_QA_SCORE

    def __post_init__(self):
        for name in ('min_retrieval_score', 'min_qa_score'):
            if not valid_score(getattr(self, name), 0, 1):
                raise ValueError(f'{name} must be a finite number between 0 and 1')

    def retrieval_rejection(self, score):
        if not valid_score(score, -1, 1):
            return 'invalid_retrieval_score'
        if score < self.min_retrieval_score:
            return 'below_retrieval_threshold'
        return None

    def answer_rejection(self, answer, qa_score, context):
        # A high score for an empty answer is confidence in abstention, not an answer.
        if not answer.strip():
            return 'qa_returned_no_answer'
        if not valid_score(qa_score, 0, 1):
            return 'invalid_qa_score'
        if qa_score < self.min_qa_score:
            return 'below_qa_threshold'
        # Extractive answers must occur in the provided source context.
        if ' '.join(answer.split()) not in ' '.join(context.split()):
            return 'answer_not_in_context'
        return None
