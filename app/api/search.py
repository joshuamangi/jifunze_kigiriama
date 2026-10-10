"""GET /api/search: keyword or semantic search over entries the caller may see."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app import search
from app.auth.deps import get_db, require_user
from app.db import Database

router = APIRouter()


@router.get("/api/search")
def search_entries(
    request: Request,
    user: Annotated[dict, Depends(require_user)],
    db: Annotated[Database, Depends(get_db)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    mode: search.Mode = "keyword",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict:
    return search.search_entries(db, request.app.state.embedder, user, q, mode, limit)
