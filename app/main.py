from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Later stages open the database and start the embedding worker here.
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Jifunze Kigiriama", lifespan=lifespan)
    app.state.settings = settings or Settings.from_env()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
