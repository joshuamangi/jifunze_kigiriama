from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.auth.hashing import PasswordService
from app.auth.throttle import LoginThrottle
from app.config import Settings
from app.db import Database
from app.security import install_request_guard


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    owns_db = app.state.db is None
    if owns_db:
        app.state.db = Database(app.state.settings.database_path)
    try:
        yield
    finally:
        if owns_db:
            app.state.db.close()
            app.state.db = None


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings and an already-migrated database."""
    app = FastAPI(title="Jifunze Kigiriama", lifespan=lifespan)
    app.state.settings = settings or Settings.from_env()
    app.state.db = db
    app.state.passwords = PasswordService(app.state.settings)
    app.state.throttle = LoginThrottle()
    install_request_guard(app)
    app.include_router(auth_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
