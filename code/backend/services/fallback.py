"""Temporary stand-in for a future external LLM provider."""


def simulated_fallback():
    """Return an explicit placeholder, never a fabricated course answer."""
    return {
        'answer': 'Simulated external LLM response: no accepted local answer was found. A real LLM is not connected yet.',
        'source': 'simulated_fallback',
        'simulated': True,
    }
