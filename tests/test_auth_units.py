import importlib.util
import sys
import threading
import time
from pathlib import Path

import pytest
from starlette.requests import Request

from app.auth.hashing import MAX_CONCURRENT_HASHES, PasswordService
from app.auth.throttle import BASE_DELAY, FREE_FAILURES, MAX_DELAY, MAX_KEYS, LoginThrottle
from app.config import ConfigError, Settings
from app.db import Database
from app.migrate import apply_migrations
from app.security import client_address
from app.users import UserError, create_user
from tests.helpers import GOOD_PASSWORD


# ---- hashing -------------------------------------------------------------------------------
def test_hash_is_argon2id_and_verifies(settings):
    service = PasswordService(settings)
    encoded = service.hash(GOOD_PASSWORD)
    assert encoded.startswith("$argon2id$")
    assert service.verify(encoded, GOOD_PASSWORD)
    assert not service.verify(encoded, "wrong")
    assert not service.verify("not-a-hash", GOOD_PASSWORD)
    assert service.verify_unknown_user(GOOD_PASSWORD) is False


def test_needs_rehash_when_parameters_change(settings):
    old = PasswordService(settings).hash(GOOD_PASSWORD)
    stronger = Settings.from_env({"ARGON2_MEMORY_KIB": "16", "ARGON2_TIME_COST": "2"})
    assert PasswordService(stronger).needs_rehash(old)
    assert not PasswordService(settings).needs_rehash(old)


def test_hashing_concurrency_is_capped(settings):
    service = PasswordService(settings)
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    class SlowHasher:
        def verify(self, *_):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            return True

    service._hasher = SlowHasher()
    threads = [threading.Thread(target=service.verify, args=("h", "p")) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["peak"] == MAX_CONCURRENT_HASHES


# ---- throttle ------------------------------------------------------------------------------
class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_throttle_allows_free_failures_then_blocks_with_growing_delay():
    clock = FakeClock()
    throttle = LoginThrottle(clock)
    for _ in range(FREE_FAILURES - 1):
        throttle.record_failure("amina", "1.1.1.1")
    assert throttle.retry_after("amina", "1.1.1.1") == 0
    throttle.record_failure("amina", "1.1.1.1")
    first = throttle.retry_after("amina", "1.1.1.1")
    assert first == int(BASE_DELAY) + 1
    clock.now += first
    assert throttle.retry_after("amina", "1.1.1.1") == 0
    throttle.record_failure("amina", "1.1.1.1")
    assert throttle.retry_after("amina", "1.1.1.1") > first


def test_throttle_delay_is_capped_and_usernames_are_case_insensitive():
    clock = FakeClock()
    throttle = LoginThrottle(clock)
    for _ in range(40):
        throttle.record_failure("Amina", "1.1.1.1")
    assert throttle.retry_after("AMINA", "9.9.9.9") <= int(MAX_DELAY) + 1


def test_success_clears_the_account_counter():
    throttle = LoginThrottle(FakeClock())
    for _ in range(FREE_FAILURES):
        throttle.record_failure("amina", "1.1.1.1")
    assert throttle.retry_after("amina", "2.2.2.2") > 0
    throttle.record_success("amina")
    assert throttle.retry_after("amina", "2.2.2.2") == 0


def test_throttle_memory_is_bounded():
    throttle = LoginThrottle(FakeClock())
    for i in range(MAX_KEYS + 500):
        throttle.record_failure(f"user{i}", f"10.0.{i // 250}.{i % 250}")
    assert len(throttle._entries) <= MAX_KEYS


# ---- client address ------------------------------------------------------------------------
def _request(peer, headers=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": raw, "client": peer, "method": "POST"})


def test_cf_connecting_ip_is_ignored_from_a_remote_peer():
    request = _request(("203.0.113.9", 5000), {"CF-Connecting-IP": "1.2.3.4"})
    assert client_address(request) == "203.0.113.9"


@pytest.mark.parametrize("peer", [("127.0.0.1", 5000), ("::1", 5000), None])
def test_cf_connecting_ip_is_used_from_a_local_peer_or_unix_socket(peer):
    request = _request(peer, {"CF-Connecting-IP": "1.2.3.4"})
    assert client_address(request) == "1.2.3.4"


def test_local_peer_without_header_falls_back_to_peer():
    assert client_address(_request(("127.0.0.1", 5000))) == "127.0.0.1"


# ---- config --------------------------------------------------------------------------------
def test_auth_settings_defaults_match_the_design():
    s = Settings.from_env({})
    assert (s.argon2_memory_kib, s.argon2_time_cost, s.argon2_parallelism) == (19456, 2, 1)
    assert s.session_idle_seconds == 7 * 24 * 3600
    assert s.session_max_age_seconds == 30 * 24 * 3600
    assert s.allowed_origins == ()


def test_auth_settings_reject_bad_numbers():
    with pytest.raises(ConfigError):
        Settings.from_env({"ARGON2_TIME_COST": "fast"})
    with pytest.raises(ConfigError):
        Settings.from_env({"SESSION_IDLE_SECONDS": "0"})


def test_password_minimum_is_configurable_within_limits():
    assert Settings.from_env({}).password_min_length == 12
    assert Settings.from_env({"PASSWORD_MIN_LENGTH": "6"}).password_min_length == 6
    for bad in ("5", "0", "-1", "129", "short"):
        with pytest.raises(ConfigError, match="PASSWORD_MIN_LENGTH|integer|positive"):
            Settings.from_env({"PASSWORD_MIN_LENGTH": bad})


# ---- accounts ------------------------------------------------------------------------------
def test_create_user_uses_the_configured_minimum(app, db):
    passwords = app.state.passwords
    with pytest.raises(UserError, match="12 to"):
        create_user(db, passwords, "eve", "x" * 11, "member")  # the default is still 12
    with pytest.raises(UserError, match="6 to"):
        create_user(db, passwords, "eve", "x" * 5, "member", min_length=6)
    assert create_user(db, passwords, "eve", "x" * 6, "member", min_length=6) > 0


def test_create_user_validates_and_rejects_case_insensitive_duplicates(app, db):
    passwords = app.state.passwords
    create_user(db, passwords, "Amina", GOOD_PASSWORD, "member")
    with pytest.raises(UserError, match="taken"):
        create_user(db, passwords, "amina", GOOD_PASSWORD, "member")
    with pytest.raises(UserError, match="password"):
        create_user(db, passwords, "bob", "short", "member")
    with pytest.raises(UserError, match="username"):
        create_user(db, passwords, "a b", GOOD_PASSWORD, "member")
    with pytest.raises(UserError, match="role"):
        create_user(db, passwords, "carol", GOOD_PASSWORD, "superuser")


def test_stored_password_is_a_hash_not_the_password(app, db):
    create_user(db, app.state.passwords, "amina", GOOD_PASSWORD, "member")
    with db.read() as conn:
        stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    assert stored.startswith("$argon2id$")
    assert GOOD_PASSWORD not in stored


def _load_script():
    path = Path(__file__).resolve().parent.parent / "scripts" / "create_user.py"
    spec = importlib.util.spec_from_file_location("create_user_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_create_user_command_prompts_twice_and_creates_the_account(monkeypatch, tmp_path, capsys):
    path = tmp_path / "cli.db"
    setup = Database(path, readers=1)
    apply_migrations(setup._writer)
    setup.close()
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("ARGON2_MEMORY_KIB", "8")
    monkeypatch.setenv("ARGON2_TIME_COST", "1")
    monkeypatch.setattr(sys, "argv", ["create_user.py", "--username", "joshua", "--role", "admin"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": GOOD_PASSWORD)

    assert _load_script().main() == 0
    check = Database(path, readers=1)
    with check.read() as conn:
        row = conn.execute("SELECT username, role FROM users").fetchone()
    check.close()
    assert (row["username"], row["role"]) == ("joshua", "admin")
    assert "created admin" in capsys.readouterr().out


def test_create_user_command_refuses_mismatched_passwords(monkeypatch, tmp_path, capsys):
    answers = iter([GOOD_PASSWORD, "something else entirely"])
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "x.db"))
    monkeypatch.setattr(sys, "argv", ["create_user.py", "--username", "joshua"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": next(answers))
    assert _load_script().main() == 1
    assert "do not match" in capsys.readouterr().err


# ---- password reset ----------------------------------------------------------------------------
def test_reset_password_replaces_the_password_and_signs_the_user_out(client, app, db, make_user):
    from app.users import reset_password
    from tests.helpers import login

    make_user("amina")
    assert login(client, "amina").status_code == 200
    assert client.get("/api/me").status_code == 200

    reset_password(db, app.state.passwords, "AMINA", "new passphrase here")  # case-insensitive

    assert client.get("/api/me").status_code == 401  # the old session is gone
    assert login(client, "amina").status_code == 401  # the old password no longer works
    assert login(client, "amina", "new passphrase here").status_code == 200
    with db.read() as conn:
        row = conn.execute(
            "SELECT action, target, detail FROM audit_log WHERE action = 'user.password_reset'"
        ).fetchone()
    assert tuple(row) == ("user.password_reset", "user:1", "amina")


def test_reset_password_only_touches_the_named_account(client, app, db, make_user):
    from app.users import reset_password
    from tests.helpers import login

    make_user("amina")
    make_user("baraka")
    reset_password(db, app.state.passwords, "amina", "new passphrase here")
    assert login(client, "baraka").status_code == 200  # untouched: still the original password


def test_reset_password_rules(app, db, make_user):
    from app.users import reset_password

    make_user("amina")
    with pytest.raises(UserError, match="no account"):
        reset_password(db, app.state.passwords, "nobody", "new passphrase here")
    with pytest.raises(UserError, match="12 to"):
        reset_password(db, app.state.passwords, "amina", "x" * 11)  # same minimum as sign-up
    reset_password(db, app.state.passwords, "amina", "x" * 6, min_length=6)  # configured minimum
