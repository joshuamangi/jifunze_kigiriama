import logging
import mimetypes
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio.to_thread
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.access import install_access_gate
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.entries import router as entries_router
from app.api.learn import router as learn_router
from app.api.people import router as people_router
from app.api.reminders import router as reminders_router
from app.api.review import router as review_router
from app.api.search import router as search_router
from app.auth.hashing import PasswordService
from app.auth.throttle import LoginThrottle
from app.config import Settings
from app.db import Database
from app.embeddings import build_embedder
from app.embeddings.base import Embedder
from app.embeddings.worker import EmbeddingWorker
from app.migrate import pending_migrations
from app.observability import configure_logging
from app.security import BodyLimitMiddleware, RequestContextMiddleware, install_request_guard
from app.services.cloudflare import AccessPolicyClient
from app.services.reminders import ConsoleBackend, SmtpBackend, SmtpConfig

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
mimetypes.add_type("application/manifest+json", ".webmanifest")
log = logging.getLogger("jifunze.invites")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    owns_db = app.state.db is None
    if owns_db:
        app.state.db = Database(
            app.state.settings.database_path, slow_ms=app.state.settings.slow_query_ms
        )
    # Sync route handlers run in a thread pool; cap it so a burst cannot starve the Pi.
    app.state.thread_limiter = anyio.to_thread.current_default_thread_limiter()
    app.state.thread_limiter.total_tokens = app.state.settings.threadpool_size
    try:
        # Refuse to serve from an out-of-date database: otherwise every request that touches a
        # new column fails with a 500 instead of one clear message at startup.
        with app.state.db.read() as conn:
            pending = pending_migrations(conn)
        if pending:
            raise RuntimeError(
                f"database is not up to date (pending: {', '.join(pending)}). Run `make migrate`."
            )
        if app.state.embedder is None:
            app.state.embedder = build_embedder(app.state.settings)  # loads the model once
        if app.state.start_worker:
            app.state.worker = EmbeddingWorker(app.state.db, app.state.embedder)
            app.state.worker.start()
        yield
    finally:
        if app.state.worker is not None:
            app.state.worker.stop()
            app.state.worker = None
        if owns_db:
            app.state.db.close()
            app.state.db = None


def _build_mailer():
    """The same email settings the study reminders use (REMINDER_BACKEND, SMTP_*). None if the
    SMTP settings are incomplete, so an invite is still added and the screen says no email went."""
    if os.environ.get("REMINDER_BACKEND", "console") != "smtp":
        return ConsoleBackend(
            out=lambda text: log.info("invite email (console backend): %s", text.splitlines()[0])
        )
    try:
        return SmtpBackend(SmtpConfig.from_env())
    except RuntimeError:
        return None


def create_app(
    settings: Settings | None = None,
    db: Database | None = None,
    embedder: Embedder | None = None,
    start_worker: bool = True,
) -> FastAPI:
    """Build the app. Tests pass their own settings, an already-migrated database and, if they
    want to drive the embedding worker themselves, start_worker=False."""
    # No /docs, /redoc or /openapi.json: they would publish the API map to anyone who asks.
    app = FastAPI(
        title="Jifunze Kigiriama",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings or Settings.from_env()
    configure_logging()
    app.state.db = db
    app.state.embedder = embedder
    app.state.start_worker = start_worker
    app.state.worker = None
    app.state.passwords = PasswordService(app.state.settings)
    app.state.throttle = LoginThrottle()
    s = app.state.settings
    # In-app invites are off unless the three Cloudflare settings are present. Tests replace these.
    app.state.cloudflare = (
        AccessPolicyClient(s.cf_api_token, s.cf_account_id, s.cf_access_policy_id)
        if s.invites_enabled
        else None
    )
    app.state.mailer = _build_mailer()
    # Added last = outermost: request id and headers wrap everything, then the size limit, then
    # the CSRF guard, so even a 413 or 403 carries the security headers.
    install_request_guard(app)
    app.add_middleware(BodyLimitMiddleware, max_bytes=app.state.settings.max_body_bytes)
    install_access_gate(app)
    app.add_middleware(RequestContextMiddleware, settings=app.state.settings)
    app.include_router(auth_router)
    app.include_router(entries_router)
    app.include_router(review_router)
    app.include_router(search_router)
    app.include_router(learn_router)
    app.include_router(reminders_router)
    app.include_router(admin_router)
    app.include_router(people_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Static front end, public like /healthz. Mounted last so every API route wins. In production
    # Nginx serves these files directly (Stage 8).
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
