"""Temporary stand-in for a future external LLM provider."""


FALLBACK_REASONS = frozenset({
    'low_retrieval_score', 'low_qa_score', 'no_extracted_answer',
    'invalid_retrieval_score', 'invalid_qa_score', 'answer_not_in_context',
    'no_accepted_answer',
})


def simulated_fallback(reason='no_accepted_answer'):
    """Return an explicit placeholder, never a fabricated course answer."""
    return {
        'answer': 'Simulated external LLM response: no accepted local answer was found. A real LLM is not connected yet.',
        'source': 'simulated_fallback',
        'simulated': True,
        'fallback_reason': reason if reason in FALLBACK_REASONS else 'no_accepted_answer',
    }
