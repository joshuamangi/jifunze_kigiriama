import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.entries import router as entries_router
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
from app.security import install_request_guard

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
mimetypes.add_type("application/manifest+json", ".webmanifest")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    owns_db = app.state.db is None
    if owns_db:
        app.state.db = Database(app.state.settings.database_path)
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


def create_app(
    settings: Settings | None = None,
    db: Database | None = None,
    embedder: Embedder | None = None,
    start_worker: bool = True,
) -> FastAPI:
    """Build the app. Tests pass their own settings, an already-migrated database and, if they
    want to drive the embedding worker themselves, start_worker=False."""
    app = FastAPI(title="Jifunze Kigiriama", lifespan=lifespan)
    app.state.settings = settings or Settings.from_env()
    app.state.db = db
    app.state.embedder = embedder
    app.state.start_worker = start_worker
    app.state.worker = None
    app.state.passwords = PasswordService(app.state.settings)
    app.state.throttle = LoginThrottle()
    install_request_guard(app)
    app.include_router(auth_router)
    app.include_router(entries_router)
    app.include_router(review_router)
    app.include_router(search_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Static front end, public like /healthz. Mounted last so every API route wins. In production
    # Nginx serves these files directly (Stage 8).
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
