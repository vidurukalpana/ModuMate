"""Load backend-local settings without overriding exported environment values."""

from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent / '.env'


def load_environment():
    """Resolve .env relative to the backend, independent of the working directory."""
    load_dotenv(dotenv_path=ENV_FILE, override=False)


def cache_capacity_from_environment():
    """Validate capacity before initializing services."""
    import os

    load_environment()
    raw = os.getenv('CACHE_CAPACITY', '10')
    try:
        capacity = int(raw)
    except ValueError as error:
        raise ValueError('CACHE_CAPACITY must be a positive integer') from error
    if capacity < 1:
        raise ValueError('CACHE_CAPACITY must be a positive integer')
    return capacity


def cache_ttl_from_environment():
    import math
    import os

    load_environment()
    try:
        ttl = float(os.getenv('CACHE_TTL_SECONDS', '3600'))
    except ValueError as error:
        raise ValueError('CACHE_TTL_SECONDS must be a positive finite number') from error
    if not math.isfinite(ttl) or ttl <= 0:
        raise ValueError('CACHE_TTL_SECONDS must be a positive finite number')
    return ttl
