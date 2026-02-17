"""Tests for configuration loading."""

import tempfile
from pathlib import Path

from src.config import Settings


class TestConfigDefaults:
    def test_default_settings_load(self):
        """Settings should construct with all defaults when no config file exists."""
        settings = Settings()
        assert settings.general.log_level == "INFO"
        assert settings.anthropic.model == "claude-haiku-4-5-20251001"
        assert settings.ollama.model == "qwen3:4b"
        assert settings.sync.interval_minutes == 15
        assert settings.raw_storage.enabled is True

    def test_vault_path_is_path(self):
        settings = Settings()
        assert isinstance(settings.general.vault_path, Path)

    def test_db_url_default(self):
        settings = Settings()
        assert "asyncpg" in settings.general.db_url


class TestConfigFromToml:
    def test_load_from_toml(self):
        """Should load overrides from a TOML file."""
        toml_content = """
[general]
vault_path = "/tmp/test-vault"
log_level = "DEBUG"

[anthropic]
model = "claude-haiku-4-5-20251001"

[sync]
interval_minutes = 5
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()

            settings = Settings.load(Path(f.name))
            assert str(settings.general.vault_path) == "/tmp/test-vault"
            assert settings.general.log_level == "DEBUG"
            assert settings.sync.interval_minutes == 5

    def test_missing_config_file_uses_defaults(self):
        settings = Settings.load(Path("/nonexistent/config.toml"))
        assert settings.general.log_level == "INFO"

    def test_partial_toml_fills_defaults(self):
        """A TOML with only [general] should still have defaults for other sections."""
        toml_content = """
[general]
log_level = "WARNING"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            f.flush()

            settings = Settings.load(Path(f.name))
            assert settings.general.log_level == "WARNING"
            assert settings.ollama.model == "qwen3:4b"  # default preserved
            assert settings.sync.interval_minutes == 15  # default preserved
