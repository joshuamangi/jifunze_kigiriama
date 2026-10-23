"""Settings read from environment variables only."""

import os
from dataclasses import dataclass, field

DEV_SESSION_SECRET = "dev-only-insecure-secret"  # noqa: S105 - placeholder, rejected in prod


class ConfigError(RuntimeError):
    pass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _choice(env: dict[str, str], name: str, default: str, allowed: set[str]) -> str:
    value = env.get(name, "").strip().lower() or default
    if value not in allowed:
        raise ConfigError(f"{name} must be one of {sorted(allowed)}")
    return value


def _timezone(name: str) -> str:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    name = name.strip() or "UTC"
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(
            f"APP_TIMEZONE {name!r} is not a known time zone (e.g. Africa/Nairobi)"
        ) from None
    return name


def _int(env: dict[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer") from None
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value


MIN_PASSWORD_FLOOR = 6  # PASSWORD_MIN_LENGTH can be lowered this far, never further
MAX_PASSWORD_MIN = 128


def _password_min(env: dict[str, str]) -> int:
    value = _int(env, "PASSWORD_MIN_LENGTH", 12)
    if not MIN_PASSWORD_FLOOR <= value <= MAX_PASSWORD_MIN:
        raise ConfigError(
            f"PASSWORD_MIN_LENGTH must be between {MIN_PASSWORD_FLOOR} and {MAX_PASSWORD_MIN}"
        )
    return value


def _threads(env: dict[str, str]) -> int:
    value = _int(env, "THREADPOOL_SIZE", 12)
    if not 8 <= value <= 16:
        raise ConfigError("THREADPOOL_SIZE must be between 8 and 16")
    return value


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_path: str
    cookie_secure: bool
    session_secret: str
    session_idle_seconds: int = 7 * 24 * 3600
    session_max_age_seconds: int = 30 * 24 * 3600
    argon2_memory_kib: int = 19456  # OWASP minimum: 19 MiB
    argon2_time_cost: int = 2
    argon2_parallelism: int = 1
    allowed_origins: tuple[str, ...] = ()  # empty = same host as the request
    embedder: str = "fake"  # "fake" (tests, quick local runs) or "onnx" (the real model)
    embed_model: str = "fp32"  # which ONNX file: "fp32" or "qint8" (arm64-quantised, smaller)
    embed_model_dir: str = "models"
    embed_threads: int = 2  # CPU threads for the model, so a reindex cannot starve the web app
    app_timezone: str = "UTC"  # defines "today" for due dates, the streak and reminder times
    session_max_cards: int = 40  # about 30 seconds a card, so roughly 20 minutes
    new_per_day: int = 8
    max_body_bytes: int = 64 * 1024  # largest request body accepted; real payloads are < 4 KiB
    threadpool_size: int = 12  # sync route handlers run in this many threads (8 to 16 on a Pi)
    slow_query_ms: int = 100  # database work slower than this is logged as a warning
    backup_stamp_path: str = "data/last_backup"  # touched by the backup job; mtime = last backup
    password_min_length: int = 12  # applied when an account is created; 6 is the lowest allowed
    cf_access_enabled: bool = False  # require a valid Cloudflare Access JWT on every request
    cf_access_team_domain: str = ""  # e.g. myteam.cloudflareaccess.com (issuer and key set)
    cf_access_aud: str = ""  # the Access application's audience tag
    # In-app invites (Settings, People). All three are needed; the token is an API token with only
    # "Access: Apps and Policies Write". repr=False keeps it out of logs and tracebacks.
    cf_api_token: str = field(default="", repr=False)
    cf_account_id: str = ""
    cf_access_policy_id: str = ""  # the reusable Access policy that holds the allowed emails
    app_base_url: str = ""  # the public address put in invite emails

    @property
    def invites_enabled(self) -> bool:
        return bool(self.cf_api_token and self.cf_account_id and self.cf_access_policy_id)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        app_env = env.get("APP_ENV", "dev").strip().lower()
        if app_env not in {"dev", "prod"}:
            raise ConfigError("APP_ENV must be 'dev' or 'prod'")
        origins = tuple(o.strip().rstrip("/") for o in env.get("ALLOWED_ORIGINS", "").split(","))
        settings = cls(
            app_env=app_env,
            database_path=env.get("DATABASE_PATH", "data/app.db"),
            cookie_secure=_bool(env.get("COOKIE_SECURE"), default=app_env == "prod"),
            session_secret=env.get("SESSION_SECRET", DEV_SESSION_SECRET),
            session_idle_seconds=_int(env, "SESSION_IDLE_SECONDS", 7 * 24 * 3600),
            session_max_age_seconds=_int(env, "SESSION_MAX_AGE_SECONDS", 30 * 24 * 3600),
            argon2_memory_kib=_int(env, "ARGON2_MEMORY_KIB", 19456),
            argon2_time_cost=_int(env, "ARGON2_TIME_COST", 2),
            argon2_parallelism=_int(env, "ARGON2_PARALLELISM", 1),
            allowed_origins=tuple(o for o in origins if o),
            embedder=_choice(env, "EMBEDDER", "fake", {"fake", "onnx"}),
            embed_model=_choice(env, "EMBED_MODEL", "fp32", {"fp32", "qint8"}),
            embed_model_dir=env.get("EMBED_MODEL_DIR", "models"),
            embed_threads=_int(env, "EMBED_THREADS", 2),
            app_timezone=_timezone(env.get("APP_TIMEZONE", "UTC")),
            session_max_cards=_int(env, "SESSION_MAX_CARDS", 40),
            new_per_day=_int(env, "NEW_PER_DAY", 8),
            max_body_bytes=_int(env, "MAX_BODY_BYTES", 64 * 1024),
            threadpool_size=_threads(env),
            slow_query_ms=_int(env, "SLOW_QUERY_MS", 100),
            backup_stamp_path=env.get("BACKUP_STAMP_PATH", "data/last_backup"),
            password_min_length=_password_min(env),
            cf_access_enabled=_bool(env.get("CF_ACCESS_ENABLED"), default=False),
            cf_access_team_domain=env.get("CF_ACCESS_TEAM_DOMAIN", "").strip().lower(),
            cf_access_aud=env.get("CF_ACCESS_AUD", "").strip(),
            cf_api_token=env.get("CF_API_TOKEN", "").strip(),
            cf_account_id=env.get("CF_ACCOUNT_ID", "").strip(),
            cf_access_policy_id=env.get("CF_ACCESS_POLICY_ID", "").strip(),
            app_base_url=env.get("APP_BASE_URL", "").strip().rstrip("/"),
        )
        invite_settings = (
            settings.cf_api_token,
            settings.cf_account_id,
            settings.cf_access_policy_id,
        )
        if any(invite_settings) and not all(invite_settings):
            raise ConfigError(
                "invites need CF_API_TOKEN, CF_ACCOUNT_ID and CF_ACCESS_POLICY_ID together"
            )
        if settings.cf_access_enabled and not (
            settings.cf_access_team_domain and settings.cf_access_aud
        ):
            raise ConfigError(
                "CF_ACCESS_ENABLED needs both CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD"
            )
        if app_env == "prod" and settings.session_secret in {"", DEV_SESSION_SECRET}:
            raise ConfigError("SESSION_SECRET must be set to a real secret when APP_ENV=prod")
        return settings
