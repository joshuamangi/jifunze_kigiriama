"""Daily limits, with small numbers so they are easy to hit."""

import pytest

from app.config import Settings
from app.seed import VERIFIED_NUMBERS
from tests.test_learn_api import add_numbers, review, session, summary


@pytest.fixture
def settings():
    return Settings.from_env(
        {
            "ARGON2_MEMORY_KIB": "8",
            "ARGON2_TIME_COST": "1",
            "NEW_PER_DAY": "3",
            "SESSION_MAX_CARDS": "4",
        }
    )


def test_new_cards_are_capped_per_day_across_sessions(login_as):
    boss, amina = login_as("boss", "admin"), login_as("amina")
    ids = add_numbers(boss, 12)
    assert len(session(amina, 1)["cards"]) == 3  # NEW_PER_DAY
    for entry_id, giriama in zip(ids[:3], ("mwenga", "hiri", "hahu"), strict=True):
        review(amina, entry_id, "spell", answer=giriama)
    assert summary(amina)["new_available"] == 0  # today's new cards are used up
    assert session(amina, 1)["cards"] == []


def test_a_session_never_exceeds_the_card_cap_and_due_cards_come_first(db):
    from datetime import date

    from app.services import learn

    settings = Settings.from_env({"NEW_PER_DAY": "3", "SESSION_MAX_CARDS": "4"})
    with db.write() as conn:
        for giriama, english in VERIFIED_NUMBERS[:8]:
            conn.execute(
                "INSERT INTO entries (giriama, english, category, source_type, verification_status)"
                " VALUES (?, ?, 'numbers', 'dictionary', 'unverified')",
                (giriama, english),
            )
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES ('a', 'x', 'member')"
        )
    user = {"id": 1, "role": "member", "username": "a"}
    yesterday, today = date(2026, 10, 9), date(2026, 10, 10)

    # six misses yesterday are all due today: more than the cap, so no new card fits
    for entry_id in range(1, 7):
        learn.review(db, user, entry_id, "spell", "wrong", None, yesterday)
    cards = learn.build_session(db, user, 1, today, settings)["cards"]
    assert len(cards) == 4 and not any(c["is_new"] for c in cards)

    # a second learner with two misses from yesterday: two due cards, then two new ones fit
    with db.write() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES ('b', 'x', 'member')"
        )
    other = {"id": 2, "role": "member", "username": "b"}
    for entry_id in (1, 2):
        learn.review(db, other, entry_id, "spell", "wrong", None, yesterday)
    cards = learn.build_session(db, other, 1, today, settings)["cards"]
    assert [c["is_new"] for c in cards] == [False, False, True, True]
    assert [c["entry_id"] for c in cards[:2]] == [1, 2]
