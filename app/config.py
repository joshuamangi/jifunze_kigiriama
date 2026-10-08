"""Settings read from environment variables only."""

import os
from dataclasses import dataclass

DEV_SESSION_SECRET = "dev-only-insecure-secret"  # noqa: S105 - placeholder, rejected in prod


class ConfigError(RuntimeError):
    pass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_path: str
    cookie_secure: bool
    session_secret: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        app_env = env.get("APP_ENV", "dev").strip().lower()
        if app_env not in {"dev", "prod"}:
            raise ConfigError("APP_ENV must be 'dev' or 'prod'")
        settings = cls(
            app_env=app_env,
            database_path=env.get("DATABASE_PATH", "data/app.db"),
            cookie_secure=_bool(env.get("COOKIE_SECURE"), default=app_env == "prod"),
            session_secret=env.get("SESSION_SECRET", DEV_SESSION_SECRET),
        )
        if app_env == "prod" and settings.session_secret in {"", DEV_SESSION_SECRET}:
            raise ConfigError("SESSION_SECRET must be set to a real secret when APP_ENV=prod")
        return settings
