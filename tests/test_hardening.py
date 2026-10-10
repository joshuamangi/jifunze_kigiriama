"""Stage 7: route/auth table, security headers, size limits, audit record, admin status, logs."""

import json
import logging
import os
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings
from app.db import Database
from app.main import create_app
from app.observability import JsonFormatter
from app.security import CSP
from tests.helpers import GOOD_PASSWORD, GUARD_HEADERS, login

WEB = Path(__file__).resolve().parent.parent / "web"

# The one explicit statement of who may call what. A new route that is not listed here fails
# test_every_route_is_in_the_auth_table, so adding an endpoint forces a decision about its auth.
PUBLIC, USER, ADMIN = "public", "user", "admin"
AUTH_TABLE = {
    ("GET", "/healthz"): PUBLIC,
    ("POST", "/api/login"): PUBLIC,
    ("POST", "/api/logout"): USER,
    ("GET", "/api/me"): USER,
    ("POST", "/api/entries"): USER,
    ("GET", "/api/entries"): USER,
    ("GET", "/api/entries/{entry_id}"): USER,
    ("PATCH", "/api/entries/{entry_id}"): USER,
    ("GET", "/api/entries/{entry_id}/history"): USER,
    ("POST", "/api/entries/{entry_id}/history/{history_id}/revert"): USER,
    ("GET", "/api/categories"): USER,
    ("GET", "/api/suggestions/gap"): USER,
    ("GET", "/api/search"): USER,
    ("GET", "/api/learn/summary"): USER,
    ("GET", "/api/learn/session"): USER,
    ("POST", "/api/learn/review"): USER,
    ("GET", "/api/reminders"): USER,
    ("PUT", "/api/reminders"): USER,
    ("GET", "/api/review"): ADMIN,
    ("POST", "/api/review/{entry_id}/approve"): ADMIN,
    ("POST", "/api/review/{entry_id}/decline"): ADMIN,
    ("GET", "/api/admin/status"): ADMIN,
}


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def _routes(app):
    """Every (method, path) the API declares, from the OpenAPI schema (the static front end is
    mounted separately and only serves GET files)."""
    return {
        (method.upper(), path)
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    }


def _observed_level(app, login_as, method, path):
    """What the running server actually enforces, not what the code claims to depend on."""
    url = _fill(path)
    anon = TestClient(app, headers=GUARD_HEADERS)
    if anon.request(method, url, json={}).status_code != 401:
        return PUBLIC
    member = login_as("member1")
    return ADMIN if member.request(method, url, json={}).status_code == 403 else USER


def test_every_route_is_in_the_auth_table(app):
    assert _routes(app) == set(AUTH_TABLE)


def test_no_api_docs_are_served(app):
    anon = TestClient(app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert anon.get(path).status_code == 404


@pytest.mark.parametrize(("method", "path"), sorted(AUTH_TABLE))
def test_the_table_is_enforced_by_the_server(app, login_as, method, path):
    assert _observed_level(app, login_as, method, path) == AUTH_TABLE[(method, path)]
    if AUTH_TABLE[(method, path)] == ADMIN:
        admin = login_as("admin1", role="admin")
        assert admin.request(method, _fill(path), json={}).status_code not in (401, 403)


# ---- headers ----------------------------------------------------------------------------------
def test_csp_has_no_inline_or_external_sources():
    assert "unsafe-inline" not in CSP
    assert "unsafe-eval" not in CSP
    assert "http" not in CSP  # no external origin, so the self-hosted font is enough
    for directive in ("script-src 'self'", "frame-ancestors 'none'", "object-src 'none'"):
        assert directive in CSP


def test_security_headers_on_page_api_and_errors(app):
    anon = TestClient(app)
    for response in (anon.get("/"), anon.get("/api/me"), anon.get("/nope"), anon.get("/healthz")):
        assert response.headers["content-security-policy"] == CSP
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "same-origin"
        assert len(response.headers["x-request-id"]) == 16
    assert anon.get("/api/me").headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in anon.get("/").headers  # dev: plain http


def test_hsts_is_sent_in_production(db):
    prod = Settings.from_env({"APP_ENV": "prod", "SESSION_SECRET": "x" * 40})
    response = TestClient(create_app(prod, db, start_worker=False)).get("/healthz")
    assert "max-age=" in response.headers["strict-transport-security"]


def test_request_ids_are_not_taken_from_the_client(app):
    sent = TestClient(app).get("/healthz", headers={"X-Request-Id": "attacker"})
    assert sent.headers["x-request-id"] != "attacker"


def test_the_page_has_no_inline_script_style_or_handlers():
    html = (WEB / "index.html").read_text()
    for script in re.findall(r"<script\b[^>]*>", html):
        assert "src=" in script
    assert "<style" not in html
    assert not re.search(r"\son[a-z]+\s*=", html)
    assert not re.search(r"\sstyle\s*=", html)


# ---- size limits ------------------------------------------------------------------------------
def test_oversized_body_is_refused_with_413(login_as):
    client = login_as("amina")
    big = {"giriama": "x", "english": "y" * 70_000, "category": "numbers", "source_type": "own"}
    response = client.post("/api/entries", json=big)
    assert response.status_code == 413
    assert response.headers["content-security-policy"] == CSP


def test_oversized_body_without_content_length_is_refused(login_as):
    client = login_as("amina")

    def chunks():
        for _ in range(20):
            yield b" " * 8192

    response = client.post(
        "/api/entries", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_oversized_field_is_refused_by_validation(login_as):
    client = login_as("amina")
    entry = {"giriama": "x", "english": "y" * 1001, "category": "numbers", "source_type": "own"}
    assert client.post("/api/entries", json=entry).status_code == 422
    assert (
        client.post("/api/login", json={"username": "u" * 65, "password": "p"}).status_code == 422
    )


def test_thread_pool_is_capped(settings, db):
    capped = Settings.from_env({"THREADPOOL_SIZE": "9", "ARGON2_MEMORY_KIB": "8"})
    app = create_app(capped, db, start_worker=False)
    with TestClient(app):
        assert app.state.thread_limiter.total_tokens == 9
    for bad in ("4", "64"):
        with pytest.raises(ConfigError):
            Settings.from_env({"THREADPOOL_SIZE": bad})


# ---- audit record -----------------------------------------------------------------------------
def _audit(db, skip_user_create=True):
    with db.read() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id")]
    return [r for r in rows if not (skip_user_create and r["action"] == "user.create")]


def test_failed_login_is_in_the_audit_record(client, make_user, db):
    make_user("amina")
    assert login(client, "amina", "wrong password!").status_code == 401
    assert login(client, "ghost", "wrong password!").status_code == 401
    rows = _audit(db)
    assert [(r["action"], r["actor_name"], r["actor_id"]) for r in rows] == [
        ("login.failure", "amina", None),
        ("login.failure", "ghost", None),
    ]
    assert rows[0]["request_id"] and rows[0]["address"]
    assert "wrong password!" not in json.dumps(rows)


def test_login_logout_and_throttle_are_audited(client, make_user, db):
    make_user("amina")
    assert login(client).status_code == 200
    assert client.post("/api/logout").status_code == 204
    assert [r["action"] for r in _audit(db)] == ["login.success", "logout"]
    for _ in range(20):
        login(client, "amina", "wrong password!")
    assert "login.throttled" in {r["action"] for r in _audit(db)}


def test_moderation_and_admin_actions_are_audited(login_as, db):
    member = login_as("member1")
    admin = login_as("admin1", role="admin")
    entry = {"giriama": "mwenga", "english": "one", "category": "numbers", "source_type": "own"}
    first = member.post("/api/entries", json=entry).json()["id"]
    second = member.post("/api/entries", json=entry).json()["id"]
    assert admin.post(f"/api/review/{first}/approve").status_code == 200
    assert admin.post(f"/api/review/{second}/decline").status_code == 200
    patched = admin.patch(f"/api/entries/{first}", json={"verification_status": "native_verified"})
    assert patched.status_code == 200
    actions = [(r["action"], r["actor_name"], r["target"]) for r in _audit(db)]
    assert ("entry.approve", "admin1", f"entry:{first}") in actions
    assert ("entry.decline", "admin1", f"entry:{second}") in actions
    assert ("entry.set_status", "admin1", f"entry:{first}") in actions


def test_creating_a_user_is_audited_without_the_password(app, make_user, db):
    make_user("amina", role="member")
    row = _audit(db, skip_user_create=False)[0]
    assert (row["action"], row["target"], row["detail"]) == (
        "user.create",
        "user:1",
        "member amina",
    )
    assert GOOD_PASSWORD not in json.dumps(row)


# ---- admin status -----------------------------------------------------------------------------
def test_admin_status_reports_size_pending_embeddings_and_backup(login_as, app, tmp_path):
    stamp = tmp_path / "last_backup"
    object.__setattr__(app.state.settings, "backup_stamp_path", str(stamp))
    admin = login_as("admin1", role="admin")
    assert admin.get("/api/admin/status").json()["backup"]["last_backup_at"] is None
    admin.post(
        "/api/entries",
        json={"giriama": "mwenga", "english": "one", "category": "numbers", "source_type": "own"},
    )
    stamp.touch()
    os.utime(stamp, (1_700_000_000, 1_700_000_000))
    body = admin.get("/api/admin/status").json()
    assert body["database"]["bytes"] > 0
    assert body["embeddings"]["pending"] == 1  # the worker is off in tests
    assert body["backup"]["last_backup_at"] == "2023-11-14T22:13:20Z"


def test_status_counts_recent_failed_logins(login_as, client, make_user):
    admin = login_as("admin1", role="admin")
    login(client, "nobody", "wrong password!")
    assert admin.get("/api/admin/status").json()["audit"]["failed_logins_24h"] == 1


def test_healthz_returns_no_data(app):
    response = TestClient(app).get("/healthz")
    assert response.json() == {"status": "ok"}


# ---- logs -------------------------------------------------------------------------------------
class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []
        self.setFormatter(JsonFormatter())

    def emit(self, record):
        self.lines.append(json.loads(self.format(record)))


@pytest.fixture
def logs():
    handler = _Capture()
    logger = logging.getLogger("jifunze")
    logger.addHandler(handler)
    yield handler.lines
    logger.removeHandler(handler)


def test_access_log_has_request_id_and_no_query_string(app, logs):
    response = TestClient(app).get("/api/me?secret=abc")
    line = next(entry for entry in logs if entry["msg"] == "request")
    assert line["request_id"] == response.headers["x-request-id"]
    assert (line["method"], line["path"], line["status"]) == ("GET", "/api/me", 401)
    assert "secret" not in json.dumps(line)


def test_slow_database_work_is_logged_with_the_request_id(tmp_path, logs):
    from app.db import connect
    from app.migrate import apply_migrations

    setup = connect(tmp_path / "s.db")
    apply_migrations(setup)
    setup.close()
    slow = Database(tmp_path / "s.db", readers=1, slow_ms=20)
    try:
        with slow.read() as conn:
            conn.execute("SELECT 1").fetchone()
        assert not [entry for entry in logs if "slow" in entry["msg"]]
        with slow.read():
            time.sleep(0.05)
        with slow.write():
            time.sleep(0.05)
    finally:
        slow.close()
    kinds = [entry["kind"] for entry in logs if entry["msg"].startswith("slow database")]
    assert kinds == ["read", "write"]
    assert all(entry["duration_ms"] >= 20 for entry in logs if "kind" in entry)


def test_audit_event_is_also_logged(client, make_user, logs):
    make_user("amina")
    login(client, "amina", "wrong password!")
    event = next(e for e in logs if e["msg"] == "audit" and e["action"] == "login.failure")
    assert event["request_id"]


# ---- XSS --------------------------------------------------------------------------------------
XSS = '<img src=x onerror="alert(1)"><script>alert(2)</script>'


def test_markup_in_an_entry_comes_back_as_inert_json(login_as):
    client = login_as("amina")
    entry = {"giriama": "mwenga", "english": XSS, "category": "numbers", "source_type": "own"}
    created = client.post("/api/entries", json=entry)
    assert created.status_code == 201
    response = client.get(f"/api/entries/{created.json()['id']}")
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["english"] == XSS


def test_front_end_never_writes_html_from_data():
    banned = re.compile(
        r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function"
    )
    for path in sorted((WEB / "js").rglob("*.js")) + [WEB / "sw.js"]:
        assert not banned.search(path.read_text()), path
