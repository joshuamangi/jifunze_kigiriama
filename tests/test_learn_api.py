import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.seed import VERIFIED_NUMBERS
from app.services import learn
from tests.helpers import GUARD_HEADERS

TODAY = date.today()
SETTINGS = Settings.from_env({})


@pytest.fixture
def boss(login_as):
    return login_as("boss", "admin")


@pytest.fixture
def amina(login_as):
    return login_as("amina")


@pytest.fixture
def baraka(login_as):
    return login_as("baraka")


def add_numbers(admin, count):
    """Approved entries from the verified list only (CLAUDE.md): admin entries start approved."""
    ids = []
    for giriama, english in VERIFIED_NUMBERS[:count]:
        body = {
            "giriama": giriama,
            "english": english,
            "category": "numbers",
            "source_type": "dictionary",
        }
        ids.append(admin.post("/api/entries", json=body).json()["id"])
    return ids


def card_for(session, entry_id):
    return next(c for c in session["cards"] if c["entry_id"] == entry_id)


def session(client, tier=2):
    response = client.get("/api/learn/session", params={"tier": tier})
    assert response.status_code == 200, response.text
    return response.json()


def review(client, entry_id, drill, **extra):
    return client.post("/api/learn/review", json={"entry_id": entry_id, "drill": drill, **extra})


def summary(client):
    return client.get("/api/learn/summary").json()


# ---- summary and sessions ------------------------------------------------------------------
def test_summary_for_a_user_with_nothing_to_study(amina):
    assert summary(amina) == {
        "due_today": 0,
        "new_available": 0,
        "reviewed_today": 0,
        "streak_days": 0,
        "estimated_minutes": 0,
    }


def test_new_cards_are_offered_up_to_the_daily_limit(boss, amina):
    add_numbers(boss, 12)
    body = summary(amina)
    assert body["new_available"] == 8 and body["due_today"] == 0
    assert body["estimated_minutes"] == 4  # 8 cards x 30 seconds
    assert len(session(amina)["cards"]) == 8


def test_tier_two_new_cards_are_multiple_choice_without_the_answer_marked(boss, amina):
    add_numbers(boss, 5)
    cards = session(amina, 2)["cards"]
    assert len(cards) == 5
    for card in cards:
        assert card["drill"] == "recognise" and card["is_new"] is True
        assert 2 <= len(card["options"]) <= 4 and len(set(card["options"])) == len(card["options"])
        assert "answer" not in card
    giriama_to_english = dict(VERIFIED_NUMBERS)
    assert all(giriama_to_english[c["prompt"]] in c["options"] for c in cards)


def test_tier_one_is_spelling_and_never_sends_the_kigiriama_answer(boss, amina):
    add_numbers(boss, 5)
    payload = session(amina, 1)
    assert {c["drill"] for c in payload["cards"]} == {"spell"}
    text = json.dumps(payload)
    assert not any(giriama in text for giriama, _ in VERIFIED_NUMBERS[:5])
    assert "one" in text  # the English meaning is the prompt


def test_a_single_entry_falls_back_to_recall_because_there_are_no_choices(boss, amina):
    add_numbers(boss, 1)
    card = session(amina, 2)["cards"][0]
    assert card["drill"] == "recall" and card["options"] is None and card["answer"] == "mwenga"


def test_locked_and_invalid_tiers(amina):
    for tier in range(3, 9):
        assert amina.get("/api/learn/session", params={"tier": tier}).status_code == 403
    for tier in (0, 9):
        assert amina.get("/api/learn/session", params={"tier": tier}).status_code == 422
    assert amina.get("/api/learn/session").status_code == 422


def test_only_approved_entries_are_studied(boss, amina, baraka):
    add_numbers(boss, 2)
    amina.post(
        "/api/entries",
        json={"giriama": "hahu", "english": "three", "category": "numbers", "source_type": "own"},
    )
    pending_id = amina.get("/api/entries").json()["items"][0]["id"]
    assert [c["prompt"] for c in session(amina, 1)["cards"]] == [
        "one",
        "two",
    ]  # not her pending one
    assert review(amina, pending_id, "spell", answer="hahu").status_code == 404
    assert review(baraka, pending_id, "spell", answer="hahu").status_code == 404
    boss.post(f"/api/review/{pending_id}/decline")
    assert review(amina, pending_id, "spell", answer="hahu").status_code == 404


# ---- reviewing -----------------------------------------------------------------------------
def test_spelling_is_judged_on_the_server_after_trim_and_case_only(boss, amina):
    (mwenga, hiri) = add_numbers(boss, 2)
    ok = review(amina, mwenga, "spell", answer="  MWENGA ").json()
    assert ok["correct"] is True and ok["grade"] == "good" and ok["interval_days"] == 1
    assert ok["next_due"] == (TODAY + timedelta(days=1)).isoformat()

    # Accents, a different letter, an extra letter or a missing one are all misses: letters are
    # never folded together, because that is a decision for the owner, not a default.
    for wrong in ("h\u00edri", "hir\u00ed", "hiri\u0301", "hiry", "hirii", "hir", "hri", "   "):
        miss = review(amina, hiri, "spell", answer=wrong).json()
        assert miss["correct"] is False and miss["grade"] == "again", wrong
        assert miss["correct_answer"] == "hiri"  # the stored spelling is shown, unchanged
        assert miss["next_due"] == TODAY.isoformat()  # still due today
    assert review(amina, hiri, "spell", answer="Hiri").json()["correct"] is True


def test_multi_word_spelling_collapses_spaces_only(boss, amina):
    ids = add_numbers(boss, 11)  # the eleventh verified entry is "kumi na hahu"
    assert review(amina, ids[10], "spell", answer="Kumi   na  hahu").json()["correct"] is True
    assert review(amina, ids[10], "spell", answer="kumina hahu").json()["correct"] is False


def test_recognise_is_graded_on_the_server(boss, amina):
    (mwenga,) = add_numbers(boss, 1)
    assert review(amina, mwenga, "recognise", answer="One ").json()["correct"] is True
    other = review(amina, mwenga, "recognise", answer="two").json()
    assert other["correct"] is False and other["correct_answer"] == "one"


def test_recall_uses_the_learners_own_grade_and_requires_one(boss, amina):
    (mwenga,) = add_numbers(boss, 1)
    assert review(amina, mwenga, "recall").status_code == 422
    assert review(amina, mwenga, "spell").status_code == 422  # spelling needs an answer
    easy = review(amina, mwenga, "recall", grade="easy").json()
    assert easy["grade"] == "easy" and easy["interval_days"] == 1
    again = review(amina, mwenga, "recall", grade="again").json()
    assert again["correct"] is False and again["next_due"] == TODAY.isoformat()


def test_the_client_cannot_choose_the_schedule_or_another_user(boss, amina):
    (mwenga,) = add_numbers(boss, 1)
    for extra in (
        {"interval": 999},
        {"due_date": "2099-01-01"},
        {"user_id": 1},
        {"ease_factor": 9},
    ):
        response = review(amina, mwenga, "recall", grade="good", **extra)
        assert response.status_code == 422, extra
    assert review(amina, mwenga, "recall", grade="perfect").status_code == 422
    assert review(amina, mwenga, "dance", grade="good").status_code == 422


def test_a_missed_card_stays_due_and_comes_back_first(boss, amina):
    ids = add_numbers(boss, 4)
    review(amina, ids[0], "spell", answer="wrong")
    body = summary(amina)
    assert body["due_today"] == 1 and body["new_available"] == 3
    cards = session(amina, 1)["cards"]
    assert cards[0]["entry_id"] == ids[0] and cards[0]["is_new"] is False  # due before new
    assert [c["is_new"] for c in cards] == [False, True, True, True]


def test_a_correct_card_leaves_todays_queue_and_streak_starts(boss, amina):
    ids = add_numbers(boss, 3)
    review(amina, ids[0], "spell", answer="mwenga")
    body = summary(amina)
    assert (
        body["due_today"],
        body["new_available"],
        body["reviewed_today"],
        body["streak_days"],
    ) == (0, 2, 1, 1)
    assert ids[0] not in [c["entry_id"] for c in session(amina, 1)["cards"]]


# ---- privacy -------------------------------------------------------------------------------
def test_one_users_progress_never_touches_or_shows_another_users(boss, amina, baraka, db):
    ids = add_numbers(boss, 3)
    for entry_id, answer in zip(ids, ("mwenga", "wrong", "hahu"), strict=True):
        review(amina, entry_id, "spell", answer=answer)
    assert summary(amina)["reviewed_today"] == 3 and summary(amina)["streak_days"] == 1
    other = summary(baraka)
    assert (other["due_today"], other["reviewed_today"], other["streak_days"]) == (0, 0, 0)
    assert other["new_available"] == 3
    assert [c["is_new"] for c in session(baraka, 1)["cards"]] == [True, True, True]
    with db.read() as conn:
        owners = {r[0] for r in conn.execute("SELECT DISTINCT user_id FROM user_progress")}
        logged = {r[0] for r in conn.execute("SELECT DISTINCT user_id FROM review_log")}
    assert owners == logged == {2}  # amina's id only


def test_anonymous_requests_are_rejected(app):
    anon = TestClient(app, headers=GUARD_HEADERS)
    assert anon.get("/api/learn/summary").status_code == 401
    assert anon.get("/api/learn/session", params={"tier": 1}).status_code == 401
    assert (
        anon.post(
            "/api/learn/review", json={"entry_id": 1, "drill": "recall", "grade": "good"}
        ).status_code
        == 401
    )


# ---- service-level: time, streak, drills that change with progress ------------------------
def test_streak_counts_consecutive_days_and_survives_a_day_without_a_review_yet():
    d = lambda n: date(2026, 10, n)  # noqa: E731
    assert learn.streak_days({d(8), d(9), d(10)}, d(10)) == 3
    assert learn.streak_days({d(8), d(9)}, d(10)) == 2  # today not reviewed yet: still alive
    assert learn.streak_days({d(7), d(8)}, d(10)) == 0  # missed yesterday: broken
    assert learn.streak_days({d(5), d(6), d(9), d(10)}, d(10)) == 2  # a gap ends the run
    assert learn.streak_days(set(), d(10)) == 0


def test_today_follows_the_configured_time_zone():
    late_utc = datetime(2026, 10, 10, 22, 30, tzinfo=UTC)
    assert learn.today_in(Settings.from_env({"APP_TIMEZONE": "UTC"}), late_utc) == date(
        2026, 10, 10
    )
    nairobi = Settings.from_env({"APP_TIMEZONE": "Africa/Nairobi"})  # UTC+3
    assert learn.today_in(nairobi, late_utc) == date(2026, 10, 11)


def test_cards_move_from_multiple_choice_to_recall_as_they_are_learned(boss, db, amina):
    ids = add_numbers(boss, 5)
    user = {"id": 2, "role": "member", "username": "amina"}
    day = date(2026, 10, 1)
    assert learn.build_session(db, user, 2, day, SETTINGS)["cards"][0]["drill"] == "recognise"
    learn.review(db, user, ids[0], "recognise", "one", None, day)  # first success: due day+1
    learn.review(
        db, user, ids[0], "recognise", "one", None, day + timedelta(days=1)
    )  # second: due +6
    later = learn.build_session(db, user, 2, day + timedelta(days=7), SETTINGS)
    assert later["due_count"] == 1
    assert later["cards"][0]["entry_id"] == ids[0] and later["cards"][0]["drill"] == "recall"
    with db.read() as conn:
        row = conn.execute("SELECT interval, repetitions, due_date FROM user_progress").fetchone()
    assert (row["interval"], row["repetitions"], row["due_date"]) == (6, 2, "2026-10-08")


def test_distractors_are_stable_for_a_day_and_never_repeat_the_answer(boss, amina):
    add_numbers(boss, 12)
    first = session(amina, 2)
    again = session(amina, 2)
    assert first == again
    for card in first["cards"]:
        assert len({o.casefold() for o in card["options"]}) == len(card["options"])


def test_migration_0003_keeps_existing_data(tmp_path):
    from app.db import connect
    from app.migrate import MIGRATIONS_DIR, apply_migrations

    old = tmp_path / "migrations"
    old.mkdir()
    for name in ("0001_init.sql", "0002_entry_decline.sql"):
        (old / name).write_text((MIGRATIONS_DIR / name).read_text())
    conn = connect(tmp_path / "old.db")
    apply_migrations(conn, old)
    conn.execute("INSERT INTO users (username, password_hash, role) VALUES ('a', 'x', 'member')")
    conn.execute(
        "INSERT INTO entries (giriama, english, category, source_type, verification_status)"
        " VALUES ('mwenga', 'one', 'numbers', 'dictionary', 'unverified')"
    )
    conn.execute(
        "INSERT INTO user_progress (user_id, entry_id, due_date) VALUES (1, 1, '2026-10-10')"
    )
    conn.execute("INSERT INTO reminders (user_id) VALUES (1)")
    assert apply_migrations(conn) == ["0003_learning.sql", "0004_audit.sql"]
    row = conn.execute("SELECT repetitions, interval, ease_factor FROM user_progress").fetchone()
    assert (row["repetitions"], row["interval"], row["ease_factor"]) == (0, 0, 2.5)
    assert conn.execute("SELECT frequency FROM reminders").fetchone()[0] == "daily"
    assert conn.execute("SELECT count(*) FROM entries").fetchone()[0] == 1
