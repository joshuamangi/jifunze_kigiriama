"""Study sessions, reviews and the streak. Everything is scoped to one user's id.

Cards come only from entries that exist and are approved (not pending or declined). Nothing here
makes up Kigiriama: prompts, answers and distractors are all real entry text. Drills that would
need a form we do not have (grammar-rule drills, tiers 3-8) are not offered; a card that cannot be
shown in a drill (e.g. too few entries to make choices) falls back to a simpler drill instead.
"""

import hashlib
import math
import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.config import Settings
from app.db import Database
from app.services.srs import CardState, next_state

LIVE_TIERS = {1, 2}
SECONDS_PER_CARD = 30
CHOICES = 4  # recognise: the right answer plus up to three distractors
RECOGNISE_UNTIL = 2  # cards with fewer consecutive successes are shown as multiple choice
POOL_LIMIT = 2000
APPROVED = "e.verification_status != 'pending'"
NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
_SPACES = re.compile(r"\s+")


def today_in(settings: Settings, now: datetime | None = None) -> date:
    zone = ZoneInfo(settings.app_timezone)
    return (now.astimezone(zone) if now else datetime.now(zone)).date()


def normalise_spelling(text: str) -> str:
    """Compare spellings after trimming, collapsing spaces and case-folding only. No accent or
    letter folding: whether such differences matter is a decision for the owner."""
    return _SPACES.sub(" ", unicodedata.normalize("NFC", text).strip()).casefold()


def _rank(seed: str, entry_id: int) -> str:
    return hashlib.sha256(f"{seed}:{entry_id}".encode()).hexdigest()


def streak_days(dates: set[date], today: date) -> int:
    """Consecutive days with a review, ending today, or yesterday if today has none yet."""
    day = today if today in dates else today - timedelta(days=1)
    count = 0
    while day in dates:
        count += 1
        day -= timedelta(days=1)
    return count


def _new_today(conn, uid: int, today: date) -> int:
    return conn.execute(
        "SELECT count(*) FROM review_log WHERE user_id = ? AND reviewed_on = ? AND was_new = 1",
        (uid, today.isoformat()),
    ).fetchone()[0]


def _counts(conn, uid: int, today: date, settings: Settings) -> tuple[int, int]:
    due = conn.execute(
        f"SELECT count(*) FROM user_progress up JOIN entries e ON e.id = up.entry_id"
        f" WHERE up.user_id = ? AND up.due_date <= ? AND {APPROVED}",
        (uid, today.isoformat()),
    ).fetchone()[0]
    unseen = conn.execute(
        f"SELECT count(*) FROM entries e WHERE {APPROVED} AND NOT EXISTS"
        " (SELECT 1 FROM user_progress up WHERE up.user_id = ? AND up.entry_id = e.id)",
        (uid,),
    ).fetchone()[0]
    room = max(settings.new_per_day - _new_today(conn, uid, today), 0)
    return due, min(room, unseen)


def summary(db: Database, user: dict, today: date, settings: Settings) -> dict:
    uid = user["id"]
    with db.read() as conn:
        due, new_available = _counts(conn, uid, today, settings)
        reviewed_today = conn.execute(
            "SELECT count(*) FROM review_log WHERE user_id = ? AND reviewed_on = ?",
            (uid, today.isoformat()),
        ).fetchone()[0]
        since = (today - timedelta(days=400)).isoformat()
        days = {
            date.fromisoformat(r[0])
            for r in conn.execute(
                "SELECT DISTINCT reviewed_on FROM review_log WHERE user_id = ?"
                " AND reviewed_on >= ?",
                (uid, since),
            )
        }
    cards = min(due + new_available, settings.session_max_cards)
    return {
        "due_today": due,
        "new_available": new_available,
        "reviewed_today": reviewed_today,
        "streak_days": streak_days(days, today),
        "estimated_minutes": math.ceil(cards * SECONDS_PER_CARD / 60),
    }


def build_session(db: Database, user: dict, tier: int, today: date, settings: Settings) -> dict:
    if tier not in LIVE_TIERS:
        raise HTTPException(status_code=403, detail="this tier is locked")
    uid = user["id"]
    cap = settings.session_max_cards
    with db.read() as conn:
        due = conn.execute(
            f"SELECT e.id, e.giriama, e.english, up.repetitions FROM user_progress up"
            f" JOIN entries e ON e.id = up.entry_id"
            f" WHERE up.user_id = ? AND up.due_date <= ? AND {APPROVED}"
            f" ORDER BY up.due_date, up.entry_id LIMIT ?",
            (uid, today.isoformat(), cap),
        ).fetchall()
        room = max(min(settings.new_per_day - _new_today(conn, uid, today), cap - len(due)), 0)
        fresh = (
            conn.execute(
                f"SELECT e.id, e.giriama, e.english, 0 AS repetitions FROM entries e"
                f" WHERE {APPROVED} AND NOT EXISTS (SELECT 1 FROM user_progress up"
                f" WHERE up.user_id = ? AND up.entry_id = e.id) ORDER BY e.id LIMIT ?",
                (uid, room),
            ).fetchall()
            if room
            else []
        )
        pool = conn.execute(
            f"SELECT e.id, e.english FROM entries e WHERE {APPROVED} LIMIT ?", (POOL_LIMIT,)
        ).fetchall()
    cards = [_card(row, tier, today, pool, is_new=False) for row in due]
    cards += [_card(row, tier, today, pool, is_new=True) for row in fresh]
    return {"tier": tier, "cards": cards, "due_count": len(due), "new_count": len(fresh)}


def _card(row, tier: int, today: date, pool, is_new: bool) -> dict:
    card = {"entry_id": row["id"], "is_new": is_new}
    if tier == 1:  # orthography: see the meaning, type the word
        return {**card, "drill": "spell", "prompt": row["english"], "options": None}
    if row["repetitions"] < RECOGNISE_UNTIL:
        correct = row["english"].strip()
        seen = {correct.casefold()}
        distractors = []
        seed = f"{today.isoformat()}:{row['id']}"
        for other in sorted(pool, key=lambda r: _rank(seed, r["id"])):
            text = other["english"].strip()
            if other["id"] != row["id"] and text.casefold() not in seen:
                seen.add(text.casefold())
                distractors.append(text)
            if len(distractors) == CHOICES - 1:
                break
        if distractors:
            # a stable shuffle: the same card looks the same on a reload during one day
            options = sorted(
                [correct, *distractors],
                key=lambda t: hashlib.sha256(f"{row['id']}:{t}".encode()).hexdigest(),
            )
            return {**card, "drill": "recognise", "prompt": row["giriama"], "options": options}
    # recall: the learner flips the card and grades themselves, so the answer travels with it
    return {
        **card,
        "drill": "recall",
        "prompt": row["english"],
        "options": None,
        "answer": row["giriama"],
    }


def review(
    db: Database,
    user: dict,
    entry_id: int,
    drill: str,
    answer: str | None,
    grade: str | None,
    today: date,
) -> dict:
    uid = user["id"]
    with db.write() as conn:
        entry = conn.execute(
            f"SELECT e.id, e.giriama, e.english FROM entries e WHERE e.id = ? AND {APPROVED}",
            (entry_id,),
        ).fetchone()
        if entry is None:
            raise HTTPException(status_code=404, detail="entry not found")

        if drill == "spell":
            if answer is None:
                raise HTTPException(status_code=422, detail="answer required")
            correct = normalise_spelling(answer) == normalise_spelling(entry["giriama"])
            applied, shown = ("good" if correct else "again"), entry["giriama"]
        elif drill == "recognise":
            if answer is None:
                raise HTTPException(status_code=422, detail="answer required")
            correct = answer.strip().casefold() == entry["english"].strip().casefold()
            applied, shown = ("good" if correct else "again"), entry["english"]
        else:  # recall: the learner's own grade
            if grade is None:
                raise HTTPException(status_code=422, detail="grade required")
            applied, shown = grade, entry["giriama"]
            correct = grade != "again"

        row = conn.execute(
            "SELECT interval, ease_factor, repetitions FROM user_progress"
            " WHERE user_id = ? AND entry_id = ?",
            (uid, entry_id),
        ).fetchone()
        state = (
            CardState(row["interval"], row["ease_factor"], row["repetitions"])
            if row
            else CardState()
        )
        new_state, due = next_state(state, applied, today)
        conn.execute(
            f"INSERT INTO user_progress (user_id, entry_id, interval, ease_factor, due_date,"
            f" last_reviewed, repetitions) VALUES (?, ?, ?, ?, ?, {NOW}, ?)"
            f" ON CONFLICT (user_id, entry_id) DO UPDATE SET interval = excluded.interval,"
            f" ease_factor = excluded.ease_factor, due_date = excluded.due_date,"
            f" last_reviewed = excluded.last_reviewed, repetitions = excluded.repetitions",
            (
                uid,
                entry_id,
                new_state.interval,
                new_state.ease_factor,
                due.isoformat(),
                new_state.repetitions,
            ),
        )
        conn.execute(
            "INSERT INTO review_log (user_id, entry_id, reviewed_on, drill, grade, was_new)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (uid, entry_id, today.isoformat(), drill, applied, 0 if row else 1),
        )
    return {
        "correct": correct,
        "grade": applied,
        "correct_answer": shown,
        "next_due": due.isoformat(),
        "interval_days": new_state.interval,
    }
