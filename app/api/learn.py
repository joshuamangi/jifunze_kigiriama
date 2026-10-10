"""Study sessions and reviews. Every call is scoped to the signed-in user; no user id is ever
accepted from the client, and the client never supplies an interval or a date."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, StringConstraints

from app.auth.deps import get_db, get_settings, require_user
from app.config import Settings
from app.db import Database
from app.services import learn

router = APIRouter()

CurrentUser = Annotated[dict, Depends(require_user)]
Db = Annotated[Database, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: int
    drill: Literal["spell", "recognise", "recall"]
    answer: Annotated[str, StringConstraints(max_length=1000)] | None = None
    grade: Literal["again", "hard", "good", "easy"] | None = None


@router.get("/api/learn/summary")
def summary(user: CurrentUser, db: Db, settings: Config) -> dict:
    return learn.summary(db, user, learn.today_in(settings), settings)


@router.get("/api/learn/session")
def session(
    user: CurrentUser, db: Db, settings: Config, tier: Annotated[int, Query(ge=1, le=8)]
) -> dict:
    return learn.build_session(db, user, tier, learn.today_in(settings), settings)


@router.post("/api/learn/review")
def review(body: ReviewIn, user: CurrentUser, db: Db, settings: Config, request: Request) -> dict:
    return learn.review(
        db, user, body.entry_id, body.drill, body.answer, body.grade, learn.today_in(settings)
    )
