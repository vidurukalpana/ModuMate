"""Load backend-local settings without overriding exported environment values."""

from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent / '.env'


def load_environment():
    """Resolve .env relative to the backend, independent of the working directory."""
    load_dotenv(dotenv_path=ENV_FILE, override=False)
