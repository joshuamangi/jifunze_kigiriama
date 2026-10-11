"""Admin review queue. Every route here depends on require_admin, checked server-side."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app import audit, entries
from app.auth.deps import get_db, require_admin
from app.db import Database

router = APIRouter()

Admin = Annotated[dict, Depends(require_admin)]
Db = Annotated[Database, Depends(get_db)]


@router.get("/api/review")
def review_queue(admin: Admin, db: Db) -> dict:
    return entries.review_queue(db)


@router.post("/api/review/{entry_id}/approve")
def approve(entry_id: int, admin: Admin, db: Db, request: Request) -> dict:
    result = entries.approve_entry(db, admin, entry_id)
    audit.record(db, "entry.approve", request=request, actor=admin, target=f"entry:{entry_id}")
    return result


@router.post("/api/review/{entry_id}/decline")
def decline(entry_id: int, admin: Admin, db: Db, request: Request) -> dict:
    result = entries.decline_entry(db, admin, entry_id)
    audit.record(db, "entry.decline", request=request, actor=admin, target=f"entry:{entry_id}")
    return result
