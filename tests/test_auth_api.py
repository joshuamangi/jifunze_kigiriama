from datetime import UTC, datetime, timedelta

from fastapi import Depends
from fastapi.testclient import TestClient

from app.auth.deps import require_admin
from app.auth.sessions import COOKIE_NAME, hash_token
from app.config import Settings
from app.main import create_app
from tests.helpers import GOOD_PASSWORD, GUARD_HEADERS, login


def _iso(delta: timedelta) -> str:
    moment = datetime.now(UTC) + delta
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def test_login_me_logout_round_trip(client, make_user, db):
    make_user()
    response = login(client)
    assert response.status_code == 200
    assert response.json()["username"] == "amina"
    assert client.get("/api/me").json() == {"id": 1, "username": "amina", "role": "member"}

    assert client.post("/api/logout").status_code == 204
    with db.read() as conn:
        assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    assert client.get("/api/me").status_code == 401


def test_login_is_case_insensitive_on_username(client, make_user):
    make_user("Amina")
    assert login(client, "amina").status_code == 200


def test_wrong_password_and_unknown_user_give_identical_generic_401(client, make_user):
    make_user()
    wrong = login(client, "amina", "not the password")
    unknown = login(client, "nobody", "not the password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "invalid username or password"}


def test_repeated_failures_are_throttled_even_for_the_right_password(client, make_user):
    make_user()
    for _ in range(5):
        assert login(client, "amina", "wrong").status_code == 401
    blocked = login(client, "amina", GOOD_PASSWORD)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_throttle_is_also_per_address_across_usernames(client, make_user):
    make_user()
    for i in range(5):
        assert login(client, f"guess{i}", "wrong").status_code == 401
    assert login(client, "amina", GOOD_PASSWORD).status_code == 429


def test_only_the_token_hash_is_stored(client, make_user, db):
    make_user()
    login(client)
    token = client.cookies.get(COOKIE_NAME)
    assert token
    with db.read() as conn:
        rows = conn.execute("SELECT * FROM sessions").fetchall()
    assert len(rows) == 1
    assert rows[0]["token_hash"] == hash_token(token)
    assert token not in [str(v) for v in tuple(rows[0])]


def test_forged_or_unknown_cookie_is_rejected(client, make_user):
    make_user()
    client.cookies.set(COOKIE_NAME, "not-a-real-token")
    assert client.get("/api/me").status_code == 401


def test_expired_session_is_rejected(client, make_user, db):
    make_user()
    login(client)
    with db.write() as conn:
        conn.execute("UPDATE sessions SET expires_at = ?", (_iso(timedelta(seconds=-5)),))
    assert client.get("/api/me").status_code == 401


def test_idle_session_is_rejected(client, make_user, db, settings):
    make_user()
    login(client)
    idle = timedelta(seconds=-(settings.session_idle_seconds + 60))
    with db.write() as conn:
        conn.execute("UPDATE sessions SET last_seen_at = ?", (_iso(idle),))
    assert client.get("/api/me").status_code == 401


def test_last_seen_is_refreshed_but_not_on_every_request(client, make_user, db):
    make_user()
    login(client)
    old = _iso(timedelta(hours=-1))
    with db.write() as conn:
        conn.execute("UPDATE sessions SET last_seen_at = ?", (old,))
    client.get("/api/me")
    with db.read() as conn:
        refreshed = conn.execute("SELECT last_seen_at FROM sessions").fetchone()[0]
    assert refreshed > old
    client.get("/api/me")
    with db.read() as conn:
        assert conn.execute("SELECT last_seen_at FROM sessions").fetchone()[0] == refreshed


def test_logout_revokes_the_session_for_a_copied_cookie(client, make_user, app):
    make_user()
    login(client)
    token = client.cookies.get(COOKIE_NAME)
    client.post("/api/logout")
    with TestClient(app, headers=GUARD_HEADERS) as other:
        other.cookies.set(COOKIE_NAME, token)
        assert other.get("/api/me").status_code == 401


def test_cookie_flags_in_dev(client, make_user):
    make_user()
    cookie = login(client).headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "secure" not in cookie


def test_cookie_is_secure_when_configured(db, make_user, tmp_path):
    secure = Settings.from_env(
        {"ARGON2_MEMORY_KIB": "8", "ARGON2_TIME_COST": "1", "COOKIE_SECURE": "true"}
    )
    secure_app = create_app(secure, db)
    # User created with a hasher from the same params, so verification works.
    from app.users import create_user

    create_user(db, secure_app.state.passwords, "amina", GOOD_PASSWORD, "member")
    with TestClient(secure_app, headers=GUARD_HEADERS, base_url="https://testserver") as c:
        cookie = login(c).headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "httponly" in cookie


def test_anonymous_gets_401_member_gets_403_admin_gets_200(app, make_user):
    @app.get("/t/admin-only")
    def admin_only(user: dict = Depends(require_admin)):  # noqa: B008
        return {"ok": True}

    make_user("member1", role="member")
    make_user("boss", role="admin")
    with TestClient(app, headers=GUARD_HEADERS) as anon:
        assert anon.get("/t/admin-only").status_code == 401
    with TestClient(app, headers=GUARD_HEADERS) as member:
        login(member, "member1")
        assert member.get("/t/admin-only").status_code == 403
    with TestClient(app, headers=GUARD_HEADERS) as admin:
        login(admin, "boss")
        assert admin.get("/t/admin-only").status_code == 200


def test_login_body_limits(client):
    assert client.post("/api/login", json={"username": "", "password": "x"}).status_code == 422
    big = {"username": "a", "password": "x" * 2000}
    assert client.post("/api/login", json=big).status_code == 422


def test_state_changing_request_needs_the_custom_header(client, make_user):
    make_user()
    response = client.post(
        "/api/login",
        json={"username": "amina", "password": GOOD_PASSWORD},
        headers={"X-Requested-With": ""},
    )
    assert response.status_code == 403


def test_foreign_origin_is_rejected_and_matching_origin_allowed(client, make_user):
    make_user()
    body = {"username": "amina", "password": GOOD_PASSWORD}
    evil = client.post("/api/login", json=body, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    ok = client.post("/api/login", json=body, headers={"Origin": "http://testserver"})
    assert ok.status_code == 200


def test_allowed_origins_setting_is_honoured(db, make_user):
    settings = Settings.from_env(
        {
            "ARGON2_MEMORY_KIB": "8",
            "ARGON2_TIME_COST": "1",
            "ALLOWED_ORIGINS": "https://jifunze.example.com/",
        }
    )
    app = create_app(settings, db)
    from app.users import create_user

    create_user(db, app.state.passwords, "amina", GOOD_PASSWORD, "member")
    body = {"username": "amina", "password": GOOD_PASSWORD}
    with TestClient(app, headers=GUARD_HEADERS) as c:
        same_host = c.post("/api/login", json=body, headers={"Origin": "http://testserver"})
        assert same_host.status_code == 403
        listed = c.post("/api/login", json=body, headers={"Origin": "https://jifunze.example.com"})
        assert listed.status_code == 200


def test_there_is_no_registration_route_and_public_routes_are_known(app):
    paths = set(app.openapi()["paths"])
    assert not [p for p in paths if "regist" in p or "signup" in p or "sign-up" in p]
    assert paths == {
        "/healthz",
        "/api/login",
        "/api/logout",
        "/api/me",
        "/api/entries",
        "/api/entries/{entry_id}",
        "/api/entries/{entry_id}/history",
        "/api/entries/{entry_id}/history/{history_id}/revert",
        "/api/categories",
        "/api/suggestions/gap",
        "/api/review",
        "/api/review/{entry_id}/approve",
        "/api/review/{entry_id}/decline",
    }


def test_healthz_needs_no_session(client):
    assert client.get("/healthz").status_code == 200
