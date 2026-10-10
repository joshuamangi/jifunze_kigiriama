"""Entries, categories and the gap suggestion. Responses are JSON data, never HTML."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, StringConstraints

from app import audit, entries
from app.auth.deps import get_db, require_user
from app.db import Database
from app.entries import CategoryId, SourceType, Status

router = APIRouter()

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
CurrentUser = Annotated[dict, Depends(require_user)]
Db = Annotated[Database, Depends(get_db)]


def wake_worker(request: Request, entry_id: int) -> None:
    """Tell the embedding worker an entry may need a vector. Never blocks the request."""
    worker = request.app.state.worker
    if worker is not None:
        worker.notify(entry_id)


class EntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    giriama: Text
    english: Text
    category: CategoryId
    source_type: SourceType


class EntryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    giriama: Text | None = None
    english: Text | None = None
    category: CategoryId | None = None
    source_type: SourceType | None = None
    verification_status: Status | None = None  # admin only; enforced in the service


@router.post("/api/entries", status_code=201)
def create_entry(body: EntryIn, user: CurrentUser, db: Db, request: Request) -> dict:
    entry = entries.create_entry(db, user, body.model_dump())
    wake_worker(request, entry["id"])
    return entry


@router.get("/api/entries")
def list_entries(
    user: CurrentUser,
    db: Db,
    category: CategoryId | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    return entries.list_entries(db, user, category, q, limit, offset)


@router.get("/api/entries/{entry_id}")
def get_entry(entry_id: int, user: CurrentUser, db: Db) -> dict:
    return entries.get_entry(db, user, entry_id)


@router.patch("/api/entries/{entry_id}")
def patch_entry(
    entry_id: int, body: EntryPatch, user: CurrentUser, db: Db, request: Request
) -> dict:
    patch = body.model_dump(exclude_unset=True)
    if any(value is None for value in patch.values()):
        raise HTTPException(status_code=422, detail="fields may not be null")
    entry = entries.update_entry(db, user, entry_id, patch)
    wake_worker(request, entry_id)
    if user["role"] == "admin" and "verification_status" in patch:
        audit.record(
            db,
            "entry.set_status",
            request=request,
            actor=user,
            target=f"entry:{entry_id}",
            detail=patch["verification_status"],
        )
    return entry


@router.get("/api/entries/{entry_id}/history")
def get_history(entry_id: int, user: CurrentUser, db: Db) -> list[dict]:
    return entries.entry_history(db, user, entry_id)


@router.post("/api/entries/{entry_id}/history/{history_id}/revert")
def revert_entry(
    entry_id: int, history_id: int, user: CurrentUser, db: Db, request: Request
) -> dict:
    entry = entries.revert_entry(db, user, entry_id, history_id)
    wake_worker(request, entry_id)
    if user["role"] == "admin":
        audit.record(
            db,
            "entry.revert",
            request=request,
            actor=user,
            target=f"entry:{entry_id}",
            detail=f"history:{history_id}",
        )
    return entry


@router.get("/api/categories")
def get_categories(user: CurrentUser, db: Db) -> list[dict]:
    return entries.category_counts(db, user)


@router.get("/api/suggestions/gap")
def get_gap(user: CurrentUser, db: Db) -> dict:
    return entries.gap_category(db, user)
