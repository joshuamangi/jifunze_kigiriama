from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.seed import VERIFIED_NUMBERS
from app.services.reminders import (
    Backend,
    ConsoleBackend,
    SmtpBackend,
    SmtpConfig,
    compose,
    run_reminders,
)
from tests.helpers import GUARD_HEADERS

MONDAY_8 = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
SATURDAY_8 = datetime(2026, 10, 10, 8, 0, tzinfo=UTC)
SETTINGS = Settings.from_env({})


class Recorder(Backend):
    def __init__(self, fail=0):
        self.sent, self.fail = [], fail

    def send(self, to, subject, body):
        if self.fail:
            self.fail -= 1
            raise ConnectionError("smtp down")
        self.sent.append((to, subject, body))


def add_user(db, name, email="x@example.com", enabled=1, send_at="07:00", frequency="daily"):
    with db.write() as conn:
        uid = conn.execute(
            "INSERT INTO users (username, password_hash, role, email) VALUES (?, 'x', 'member', ?)",
            (name, email),
        ).lastrowid
        conn.execute(
            "INSERT INTO reminders (user_id, enabled, send_at, frequency) VALUES (?, ?, ?, ?)",
            (uid, enabled, send_at, frequency),
        )
    return uid


def add_entries(db, count=3):
    with db.write() as conn:
        for giriama, english in VERIFIED_NUMBERS[:count]:
            conn.execute(
                "INSERT INTO entries (giriama, english, category, source_type, verification_status)"
                " VALUES (?, ?, 'numbers', 'dictionary', 'unverified')",
                (giriama, english),
            )


def run(db, backend, now=MONDAY_8, **kw):
    return run_reminders(db, SETTINGS, backend, now=now, log=lambda *_: None, **kw)


# ---- when an email goes out ----------------------------------------------------------------
def test_a_due_reminder_is_sent_once_and_a_second_run_the_same_day_sends_nothing(db):
    add_entries(db)
    add_user(db, "amina")
    backend = Recorder()
    assert run(db, backend)["sent"] == 1
    assert run(db, backend)["sent"] == 0
    assert run(db, backend, now=MONDAY_8.replace(hour=20))["sent"] == 0
    assert len(backend.sent) == 1
    next_day = MONDAY_8.replace(day=13)
    assert run(db, backend, now=next_day)["sent"] == 1  # a new day, a new email
    assert len(backend.sent) == 2


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ({"enabled": 0}, "reminders are not listed when disabled"),
        ({"email": None}, "no email address"),
        ({"send_at": "09:00"}, "not time yet"),
    ],
)
def test_reminders_that_should_not_go_out_are_skipped(db, setup, reason):
    add_entries(db)
    add_user(db, "amina", **setup)
    backend = Recorder()
    result = run(db, backend)
    assert result["sent"] == 0 and backend.sent == []
    if setup != {"enabled": 0}:
        assert result["skipped"] == {reason: 1}


def test_weekdays_only_skips_the_weekend_but_daily_does_not(db):
    add_entries(db)
    add_user(db, "weekday", frequency="weekdays")
    add_user(db, "daily", frequency="daily")
    backend = Recorder()
    result = run(db, backend, now=SATURDAY_8)
    assert result["sent"] == 1 and result["skipped"] == {"weekend": 1}
    # on Monday both get one: the weekday user for the first time, the daily user for a new day
    assert run(db, Recorder(), now=MONDAY_8)["sent"] == 2


def test_nothing_is_sent_when_there_is_nothing_to_study_and_it_is_not_marked_sent(db):
    add_user(db, "amina")
    backend = Recorder()
    assert run(db, backend)["skipped"] == {"nothing to study": 1}
    add_entries(db)  # later in the day an entry is approved
    assert run(db, backend, now=MONDAY_8.replace(hour=15))["sent"] == 1


def test_the_send_time_uses_the_configured_time_zone(db):
    add_entries(db)
    add_user(db, "amina", send_at="07:00")
    nairobi = Settings.from_env({"APP_TIMEZONE": "Africa/Nairobi"})  # UTC+3
    early = datetime(2026, 10, 12, 3, 30, tzinfo=UTC)  # 06:30 in Nairobi
    later = datetime(2026, 10, 12, 4, 30, tzinfo=UTC)  # 07:30 in Nairobi
    backend = Recorder()
    assert run_reminders(db, nairobi, backend, now=early, log=lambda *_: None)["sent"] == 0
    assert run_reminders(db, nairobi, backend, now=later, log=lambda *_: None)["sent"] == 1


def test_a_failed_send_is_not_marked_done_and_is_retried(db):
    add_entries(db)
    add_user(db, "amina")
    backend = Recorder(fail=1)
    first = run(db, backend)
    assert first["failed"] == 1 and first["sent"] == 0
    with db.read() as conn:
        assert conn.execute("SELECT last_sent_on FROM reminders").fetchone()[0] is None
    assert run(db, backend)["sent"] == 1  # the next run (e.g. 15 minutes later) succeeds


def test_one_users_failure_does_not_stop_the_others(db):
    add_entries(db)
    add_user(db, "first")
    add_user(db, "second", email="y@example.com")
    backend = Recorder(fail=1)
    result = run(db, backend)
    assert (result["sent"], result["failed"]) == (1, 1)
    assert [to for to, _, _ in backend.sent] == ["y@example.com"]


def test_dry_run_sends_and_marks_nothing(db):
    add_entries(db)
    add_user(db, "amina")
    backend = Recorder()
    assert run(db, backend, dry_run=True)["sent"] == 0 and backend.sent == []
    assert run(db, backend)["sent"] == 1


def test_each_email_goes_only_to_its_owner_with_their_own_counts(db):
    add_entries(db, 3)
    add_user(db, "amina", email="amina@example.com")
    add_user(db, "baraka", email="baraka@example.com")
    backend = Recorder()
    run(db, backend)
    assert sorted(to for to, _, _ in backend.sent) == ["amina@example.com", "baraka@example.com"]


def test_the_email_states_counts_and_never_contains_entry_text(db):
    add_entries(db, 3)
    add_user(db, "amina")
    backend = Recorder()
    run(db, backend, base_url="https://jifunze.example.com")
    _, subject, body = backend.sent[0]
    assert subject == "Jifunze Kigiriama: 3 cards to study today"
    assert "3 new" in body and "https://jifunze.example.com" in body
    for giriama, english in VERIFIED_NUMBERS[:3]:
        assert giriama not in body and english not in body


def test_compose_wording():
    assert compose("a", 1, 0, None)[0].endswith("1 card to study today")
    assert "Open the app" not in compose("a", 1, 0, None)[1]


# ---- backends ------------------------------------------------------------------------------
def test_console_backend_prints_the_email():
    lines = []
    ConsoleBackend(out=lines.append).send("a@example.com", "Hi", "Body")
    assert "a@example.com" in lines[0] and "Subject: Hi" in lines[0] and "Body" in lines[0]


def test_smtp_config_comes_from_the_environment_and_is_validated():
    with pytest.raises(RuntimeError, match="SMTP_HOST"):
        SmtpConfig.from_env({})
    cfg = SmtpConfig.from_env({"SMTP_HOST": "mail.example.com", "SMTP_FROM": "a@example.com"})
    assert (cfg.port, cfg.starttls, cfg.user) == (587, True, None)
    plain = SmtpConfig.from_env(
        {
            "SMTP_HOST": "h",
            "SMTP_FROM": "f@example.com",
            "SMTP_PORT": "25",
            "SMTP_STARTTLS": "false",
        }
    )
    assert plain.port == 25 and plain.starttls is False


def test_smtp_backend_uses_starttls_login_and_sends_the_message(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user, password))

        def send_message(self, message):
            calls.append(("send", message["From"], message["To"], message["Subject"]))

    monkeypatch.setattr("app.services.reminders.smtplib.SMTP", FakeSMTP)
    cfg = SmtpConfig("mail.example.com", 587, "user", "secret", "from@example.com", True)
    SmtpBackend(cfg).send("to@example.com", "Subject", "Body")
    assert calls == [
        ("connect", "mail.example.com", 587),
        ("starttls",),
        ("login", "user", "secret"),
        ("send", "from@example.com", "to@example.com", "Subject"),
    ]


# ---- the settings API ----------------------------------------------------------------------
@pytest.fixture
def amina(login_as):
    return login_as("amina")


def test_reminder_defaults_are_off_until_the_user_opts_in(amina):
    body = amina.get("/api/reminders").json()
    assert body == {
        "enabled": False,
        "send_at": "07:00",
        "frequency": "daily",
        "email": "",
        "timezone": "UTC",
    }


def test_saving_a_reminder_stores_it_and_the_email(amina, db):
    saved = amina.put(
        "/api/reminders",
        json={
            "enabled": True,
            "send_at": "06:45",
            "frequency": "weekdays",
            "email": " a@example.com ",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["email"] == "a@example.com" and saved.json()["frequency"] == "weekdays"
    assert amina.get("/api/reminders").json()["send_at"] == "06:45"
    with db.read() as conn:
        assert conn.execute("SELECT email FROM users").fetchone()[0] == "a@example.com"
    again = amina.put(
        "/api/reminders",
        json={"enabled": False, "send_at": "08:00", "frequency": "daily", "email": ""},
    )
    assert again.json()["enabled"] is False and again.json()["email"] == ""  # upsert, email cleared


@pytest.mark.parametrize(
    "body",
    [
        {"enabled": True, "send_at": "25:00", "frequency": "daily", "email": "a@example.com"},
        {"enabled": True, "send_at": "7am", "frequency": "daily", "email": "a@example.com"},
        {"enabled": True, "send_at": "07:00", "frequency": "hourly", "email": "a@example.com"},
        {"enabled": True, "send_at": "07:00", "frequency": "daily", "email": "not-an-email"},
        {"enabled": True, "send_at": "07:00", "frequency": "daily", "email": ""},
        {
            "enabled": True,
            "send_at": "07:00",
            "frequency": "daily",
            "email": "a@example.com",
            "user_id": 2,
        },
    ],
)
def test_reminder_validation(amina, body):
    assert amina.put("/api/reminders", json=body).status_code == 422


def test_reminders_are_private_to_each_user(login_as):
    amina, baraka = login_as("amina"), login_as("baraka")
    amina.put(
        "/api/reminders",
        json={"enabled": True, "send_at": "06:00", "frequency": "daily", "email": "a@example.com"},
    )
    other = baraka.get("/api/reminders").json()
    assert other["enabled"] is False and other["email"] == "" and other["send_at"] == "07:00"


def test_anonymous_reminder_requests_are_rejected(app):
    anon = TestClient(app, headers=GUARD_HEADERS)
    assert anon.get("/api/reminders").status_code == 401
    assert anon.put("/api/reminders", json={}).status_code == 401
