"""Sign-in through Cloudflare Access: the verified email is the identity, no password is typed."""

import sqlite3

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.access import HEADER, AccessVerifier
from app.config import Settings
from app.main import create_app
from app.users import link_access_email
from tests.helpers import GOOD_PASSWORD, GUARD_HEADERS
from tests.test_access import ENV, make_token


@pytest.fixture(scope="module")
def keys():
    return (rsa.generate_private_key(public_exponent=65537, key_size=2048),)


@pytest.fixture
def gated_app(db, keys):
    settings = Settings.from_env(ENV)
    app = create_app(settings, db, start_worker=False)
    app.state.access_verifier = AccessVerifier(settings, key_source=lambda _t: keys[0].public_key())
    return app


def visit(app, keys, email="newperson@example.com", **overrides):
    """A fresh browser: only the Access header, no cookie."""
    client = TestClient(app, headers=GUARD_HEADERS)
    token = make_token(keys[0], email=email, **overrides)
    return client, client.post("/api/access-login", headers={HEADER: token})


def test_first_visit_creates_a_member_and_signs_them_in(gated_app, keys, db):
    client, response = visit(gated_app, keys)
    assert response.status_code == 200
    assert response.json() == {"id": 1, "username": "newperson", "role": "member", "new": True}
    token = make_token(keys[0], email="newperson@example.com")
    me = client.get("/api/me", headers={HEADER: token})
    assert me.json() == {"id": 1, "username": "newperson", "role": "member"}


def test_second_visit_matches_the_same_account_without_a_password(gated_app, keys):
    visit(gated_app, keys)
    _, again = visit(gated_app, keys, email="NewPerson@Example.com")
    assert again.json()["id"] == 1
    assert again.json()["new"] is False


def test_username_clash_gets_a_number(gated_app, keys):
    visit(gated_app, keys, email="sam@one.example")
    _, second = visit(gated_app, keys, email="sam@two.example")
    assert second.json()["username"] == "sam2"


def test_existing_account_is_matched_by_linked_email_and_keeps_its_role(
    gated_app,
    keys,
    db,
    make_user,
):
    make_user("joshua", role="admin")
    link_access_email(db, "joshua", "owner@example.com")
    _, response = visit(gated_app, keys, email="owner@example.com")
    assert response.json() == {"id": 1, "username": "joshua", "role": "admin", "new": False}


def test_typing_an_email_as_reminder_email_does_not_claim_an_account(
    gated_app,
    keys,
    db,
    make_user,
):
    make_user("mallory")
    with db.write() as conn:
        conn.execute("UPDATE users SET email = 'victim@example.com' WHERE id = 1")
    _, response = visit(gated_app, keys, email="victim@example.com")
    assert response.json()["id"] == 2  # a new account, not mallory's


def test_no_token_or_no_email_claim_is_refused(gated_app, keys):
    client = TestClient(gated_app, headers=GUARD_HEADERS)
    assert client.post("/api/access-login").status_code == 403  # the gate itself
    _, service_token = visit(gated_app, keys, email=None)
    assert service_token.status_code == 401
    _, junk = visit(gated_app, keys, email="not-an-email")
    assert junk.status_code == 401


def test_a_session_cannot_be_forged_by_sending_an_email(gated_app, keys):
    client = TestClient(gated_app, headers=GUARD_HEADERS)
    token = make_token(keys[0], email="real@example.com")
    r = client.post(
        "/api/access-login",
        headers={HEADER: token, "X-Access-Email": "admin@example.com"},
        json={"email": "admin@example.com"},
    )
    assert r.json()["username"] == "real"


def test_password_login_is_off_behind_access(gated_app, keys, make_user):
    make_user("joshua")
    client = TestClient(gated_app, headers=GUARD_HEADERS)
    token = make_token(keys[0])
    r = client.post(
        "/api/login",
        headers={HEADER: token},
        json={"username": "joshua", "password": GOOD_PASSWORD},
    )
    assert r.status_code == 404


def test_access_login_is_inert_without_the_gate(client):
    assert client.post("/api/access-login").status_code == 404


def test_access_accounts_have_no_usable_password(app, db):
    from app.users import UNUSABLE_HASH, create_access_user

    create_access_user(db, "x@example.com")
    with db.read() as conn:
        stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    assert stored == UNUSABLE_HASH
    for guess in ("", "!", UNUSABLE_HASH, GOOD_PASSWORD):
        assert not app.state.passwords.verify(stored, guess)


NEW_PASSWORD = "a brand new passphrase"  # noqa: S105 - test fixture


def test_set_password_screen_endpoint(app, client, make_user):
    make_user("amina")
    from tests.helpers import login

    assert login(client).status_code == 200
    assert client.put("/api/me/password", json={"password": "short"}).status_code == 422
    ok = client.put("/api/me/password", json={"password": NEW_PASSWORD})
    assert ok.status_code == 204
    other = TestClient(app, headers=GUARD_HEADERS)
    assert login(other, password=NEW_PASSWORD).status_code == 200
    old = login(TestClient(app, headers=GUARD_HEADERS))
    assert old.status_code == 401  # the old password is gone


def test_set_password_needs_a_session(client):
    response = client.put("/api/me/password", json={"password": NEW_PASSWORD})
    assert response.status_code == 401


def test_linking_an_email_twice_is_refused(db, make_user):
    from app.users import UserError

    make_user("aaa")
    make_user("bbb")
    link_access_email(db, "aaa", "same@example.com")
    with pytest.raises(UserError):
        link_access_email(db, "bbb", "SAME@example.com")
    with pytest.raises(sqlite3.Error):
        with db.write() as conn:
            conn.execute("UPDATE users SET access_email = 'same@example.com' WHERE username='bbb'")
