import pytest

from app.config import ConfigError, Settings


def test_dev_defaults():
    s = Settings.from_env({})
    assert s.app_env == "dev"
    assert s.cookie_secure is False
    assert s.database_path == "data/app.db"


def test_prod_defaults_to_secure_cookie():
    s = Settings.from_env({"APP_ENV": "prod", "SESSION_SECRET": "x" * 32})
    assert s.cookie_secure is True


def test_prod_rejects_missing_or_default_secret():
    with pytest.raises(ConfigError):
        Settings.from_env({"APP_ENV": "prod"})
    with pytest.raises(ConfigError):
        Settings.from_env({"APP_ENV": "prod", "SESSION_SECRET": ""})


def test_unknown_env_rejected():
    with pytest.raises(ConfigError):
        Settings.from_env({"APP_ENV": "staging"})
