"""Local .env loading and exported-variable precedence."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config import load_environment
from services.llm_fallback import FallbackConfig


class EnvironmentTests(unittest.TestCase):
    def test_provider_loads_file_and_preserves_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / '.env'
            env_file.write_text('LLM_FALLBACK_MODE=ollama\nOLLAMA_MODEL="llama3.2:1b"\nOLLAMA_TIMEOUT_SECONDS=120\n')
            with patch('config.ENV_FILE', env_file), patch.dict(os.environ, {'OLLAMA_TIMEOUT_SECONDS': '30'}, clear=True):
                config = FallbackConfig.from_environment()
                self.assertEqual(config.mode, 'ollama')
                self.assertEqual(config.model, 'llama3.2:1b')
                self.assertEqual(config.timeout, 30)
                overridden = FallbackConfig.from_environment(mode='simulated')
                self.assertEqual(overridden.mode, 'simulated')
                self.assertEqual(overridden.model, 'llama3.2:1b')
                self.assertEqual(overridden.timeout, 30)

    def test_absent_file_keeps_simulated_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('config.ENV_FILE', Path(directory) / 'missing'), patch.dict(os.environ, {}, clear=True):
                load_environment()
                self.assertEqual(FallbackConfig.from_environment().mode, 'simulated')
