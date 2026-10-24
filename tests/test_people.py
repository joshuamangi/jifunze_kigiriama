"""Inviting and removing people: the Cloudflare policy edit, the email, and the disabled account."""

import json

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings
from app.main import create_app
from app.services.cloudflare import AccessPolicyClient, CloudflareError
from tests.helpers import GUARD_HEADERS, login

POLICY = {
    "id": "pol-1",
    "account_id": "acc",
    "app_count": 1,
    "created_at": "2026-01-01T00:00:00Z",
    "name": "Jifunze: allow-listed emails",
    "decision": "allow",
    "include": [
        {"email": {"email": "owner@example.com"}},
        {"email": {"email": "amina@example.com"}},
        {"email_domain": {"domain": "family.example"}},
    ],
    "exclude": [],
    "require": [],
}


class FakeCloudflare:
    """Stands in for Cloudflare's HTTP API: one stored policy, replaced on every PUT."""

    def __init__(self):
        self.policy = json.loads(json.dumps(POLICY))
        self.puts = []
        self.fail = None

    def transport(self, method, url, headers, body):
        assert headers["Authorization"] == "Bearer tok"
        assert url.endswith("/accounts/acc/access/policies/pol-1")
        if self.fail:
            return self.fail, b'{"success": false, "errors": [{"message": "nope"}]}'
        if method == "PUT":
            sent = json.loads(body)
            self.puts.append(sent)
            self.policy.update(sent)
        return 200, json.dumps({"success": True, "result": self.policy}).encode()


def client_for(fake):
    return AccessPolicyClient("tok", "acc", "pol-1", transport=fake.transport)


# ---- the Cloudflare client ----------------------------------------------------------------
def test_add_email_keeps_every_other_rule_and_drops_read_only_fields():
    fake = FakeCloudflare()
    assert client_for(fake).add_email("new@example.com") is True
    sent = fake.puts[0]
    assert {"email": {"email": "new@example.com"}} in sent["include"]
    assert {"email_domain": {"domain": "family.example"}} in sent["include"]
    assert len(sent["include"]) == 4
    assert not {"id", "account_id", "app_count", "created_at"} & set(sent)
    assert sent["name"] == POLICY["name"] and sent["decision"] == "allow"


def test_adding_an_existing_email_ignores_case_and_writes_nothing():
    fake = FakeCloudflare()
    assert client_for(fake).add_email("AMINA@example.com") is False
    assert fake.puts == []


def test_remove_email_and_the_last_person_guard():
    fake = FakeCloudflare()
    c = client_for(fake)
    assert c.remove_email("Amina@Example.com") is True
    assert c.remove_email("nobody@example.com") is False
    assert c.list_emails() == (["owner@example.com"], 1)
    fake.policy["include"] = [{"email": {"email": "owner@example.com"}}]
    with pytest.raises(CloudflareError, match="last allowed person"):
        c.remove_email("owner@example.com")


def test_cloudflare_errors_surface_without_the_token():
    fake = FakeCloudflare()
    fake.fail = 403
    with pytest.raises(CloudflareError) as raised:
        client_for(fake).list_emails()
    assert "403" in str(raised.value) and "nope" in str(raised.value)
    assert "tok" not in str(raised.value)


# ---- the routes ---------------------------------------------------------------------------
class Mailbox:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, to, subject, body):
        if self.fail:
            raise OSError("smtp down")
        self.sent.append((to, subject, body))


@pytest.fixture
def world(app, db, make_user):
    app.state.cloudflare = client_for(fake := FakeCloudflare())
    app.state.mailer = mailbox = Mailbox()
    app.state.settings = Settings.from_env(
        {
            "ARGON2_MEMORY_KIB": "8",
            "ARGON2_TIME_COST": "1",
            "APP_BASE_URL": "https://jifunze.example/",
        }
    )
    make_user("joshua", role="admin")
    with db.write() as conn:
        conn.execute("UPDATE users SET access_email = 'owner@example.com' WHERE username='joshua'")
    admin = TestClient(app, headers=GUARD_HEADERS)
    assert login(admin, "joshua").status_code == 200
    return type("World", (), {"admin": admin, "fake": fake, "mail": mailbox, "app": app, "db": db})


def test_list_marks_who_has_signed_in_and_who_you_are(world):
    body = world.admin.get("/api/admin/people").json()
    assert body["enabled"] is True and body["other_rules"] == 1
    by_email = {p["email"]: p for p in body["people"]}
    assert by_email["owner@example.com"]["is_you"] is True
    assert by_email["amina@example.com"]["signed_in_before"] is False


def test_invite_adds_to_cloudflare_and_sends_the_email(world):
    r = world.admin.post("/api/admin/people", json={"email": " New@Example.com "})
    assert r.json() == {"email": "New@Example.com", "added": True, "emailed": True}
    to, subject, body = world.mail.sent[0]
    assert to == "New@Example.com" and "invited" in subject
    assert (
        "https://jifunze.example" in body and "password" in body
    )  # says there is none to remember
    assert "tok" not in body


def test_invite_survives_a_mail_failure(world):
    world.mail.fail = True
    r = world.admin.post("/api/admin/people", json={"email": "new@example.com"})
    assert r.status_code == 200
    assert r.json()["added"] is True and r.json()["emailed"] is False
    assert {"email": {"email": "new@example.com"}} in world.fake.policy["include"]


def test_invite_without_a_base_url_still_adds_but_sends_nothing(world):
    world.app.state.settings = Settings.from_env({"ARGON2_MEMORY_KIB": "8"})
    r = world.admin.post("/api/admin/people", json={"email": "new@example.com"})
    assert r.json()["added"] is True and r.json()["emailed"] is False
    assert world.mail.sent == []


@pytest.mark.parametrize("bad", ["nope", "a b@example.com", "x@y", "a@b.c\nBcc: z@example.com"])
def test_invalid_emails_are_refused(world, bad):
    assert world.admin.post("/api/admin/people", json={"email": bad}).status_code == 422
    assert world.fake.puts == []


def test_a_cloudflare_failure_is_a_502_and_sends_no_email(world):
    world.fake.fail = 500
    r = world.admin.post("/api/admin/people", json={"email": "new@example.com"})
    assert r.status_code == 502 and "nope" in r.json()["detail"]
    assert world.mail.sent == []


def test_remove_disables_the_account_and_ends_its_sessions(world, make_user, app):
    make_user("amina")
    with world.db.write() as conn:
        conn.execute("UPDATE users SET access_email = 'amina@example.com' WHERE username='amina'")
    amina = TestClient(app, headers=GUARD_HEADERS)
    assert login(amina, "amina").status_code == 200
    assert amina.get("/api/me").status_code == 200
    r = world.admin.post("/api/admin/people/remove", json={"email": "amina@example.com"})
    assert r.json() == {"email": "amina@example.com", "removed": True, "had_account": True}
    assert amina.get("/api/me").status_code == 401  # the session is gone
    assert login(TestClient(app, headers=GUARD_HEADERS), "amina").status_code == 401
    with world.db.read() as conn:  # the account and its data stay
        assert conn.execute("SELECT count(*) FROM users WHERE username='amina'").fetchone()[0] == 1


def test_inviting_a_removed_person_again_brings_the_account_back(world, make_user, app):
    make_user("amina")
    with world.db.write() as conn:
        conn.execute("UPDATE users SET access_email = 'amina@example.com' WHERE username='amina'")
    world.admin.post("/api/admin/people/remove", json={"email": "amina@example.com"})
    world.admin.post("/api/admin/people", json={"email": "amina@example.com"})
    assert login(TestClient(app, headers=GUARD_HEADERS), "amina").status_code == 200


def test_you_cannot_remove_yourself(world):
    r = world.admin.post("/api/admin/people/remove", json={"email": "OWNER@example.com"})
    assert r.status_code == 409
    assert world.fake.puts == []


def test_members_cannot_use_any_of_it(world, login_as):
    member = login_as("baraka")
    assert member.get("/api/admin/people").status_code == 403
    assert member.post("/api/admin/people", json={"email": "x@example.com"}).status_code == 403
    assert (
        member.post("/api/admin/people/remove", json={"email": "x@example.com"}).status_code == 403
    )
    assert world.fake.puts == []


def test_not_configured_reports_disabled_and_refuses_changes(app, login_as):
    admin = login_as("joshua", role="admin")
    assert app.state.cloudflare is None
    assert admin.get("/api/admin/people").json()["enabled"] is False
    assert admin.post("/api/admin/people", json={"email": "x@example.com"}).status_code == 503


def test_invite_and_removal_are_audited_without_the_email_address(world):
    world.admin.post("/api/admin/people", json={"email": "new@example.com"})
    with world.db.read() as conn:
        rows = conn.execute(
            "SELECT action, detail FROM audit_log WHERE action LIKE 'people.%'"
        ).fetchall()
    assert [r["action"] for r in rows] == ["people.invite"]
    assert "new@example.com" not in (rows[0]["detail"] or "")


# ---- Access sign-in for a removed person, and settings -----------------------------------
def test_a_removed_person_with_a_live_access_token_cannot_sign_back_in(db):
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.users import create_access_user, set_disabled
    from tests.test_access import ENV, make_token
    from tests.test_access_login import HEADER, AccessVerifier, keys  # noqa: F401

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = Settings.from_env(ENV)
    app = create_app(settings, db, start_worker=False)
    app.state.access_verifier = AccessVerifier(settings, key_source=lambda _t: key.public_key())
    create_access_user(db, "gone@example.com")
    set_disabled(db, "gone@example.com", True)
    client = TestClient(app, headers=GUARD_HEADERS)
    r = client.post(
        "/api/access-login", headers={HEADER: make_token(key, email="gone@example.com")}
    )
    assert r.status_code == 403


def test_partial_cloudflare_settings_are_refused_at_startup():
    with pytest.raises(ConfigError, match="together"):
        Settings.from_env({"CF_API_TOKEN": "tok"})
    assert Settings.from_env({}).invites_enabled is False
    full = {"CF_API_TOKEN": "tok", "CF_ACCOUNT_ID": "a", "CF_ACCESS_POLICY_ID": "p"}
    assert Settings.from_env(full).invites_enabled is True


def test_the_api_token_never_appears_in_the_settings_repr():
    full = {"CF_API_TOKEN": "super-secret-token", "CF_ACCOUNT_ID": "a", "CF_ACCESS_POLICY_ID": "p"}
    assert "super-secret-token" not in repr(Settings.from_env(full))


# ---- roles --------------------------------------------------------------------------------
def _give_access_email(world, make_user, username, email):
    make_user(username)
    with world.db.write() as conn:
        conn.execute("UPDATE users SET access_email = ? WHERE username = ?", (email, username))


def test_promote_and_demote(world, make_user, app):
    _give_access_email(world, make_user, "amina", "amina@example.com")
    amina = TestClient(app, headers=GUARD_HEADERS)
    assert login(amina, "amina").status_code == 200
    assert amina.get("/api/review").status_code == 403
    r = world.admin.post(
        "/api/admin/people/role", json={"email": "Amina@Example.com", "role": "admin"}
    )
    assert r.json() == {"email": "Amina@Example.com", "username": "amina", "role": "admin"}
    assert amina.get("/api/review").status_code == 200  # takes effect without signing in again
    world.admin.post(
        "/api/admin/people/role", json={"email": "amina@example.com", "role": "member"}
    )
    assert amina.get("/api/review").status_code == 403


def test_role_must_be_admin_or_member(world, make_user):
    _give_access_email(world, make_user, "amina", "amina@example.com")
    for bad in ("owner", "", "ADMIN"):
        r = world.admin.post(
            "/api/admin/people/role", json={"email": "amina@example.com", "role": bad}
        )
        assert r.status_code == 422


def test_cannot_change_your_own_role(world):
    r = world.admin.post(
        "/api/admin/people/role", json={"email": "owner@example.com", "role": "member"}
    )
    assert r.status_code == 409


def test_someone_who_has_not_signed_in_has_no_role_to_change(world):
    r = world.admin.post(
        "/api/admin/people/role", json={"email": "nobody@example.com", "role": "admin"}
    )
    assert r.status_code == 404


def test_members_cannot_change_roles(world, login_as, make_user):
    _give_access_email(world, make_user, "amina", "amina@example.com")
    member = login_as("baraka")
    r = member.post("/api/admin/people/role", json={"email": "baraka@example.com", "role": "admin"})
    assert r.status_code == 403
    r = member.post("/api/admin/people/role", json={"email": "amina@example.com", "role": "admin"})
    assert r.status_code == 403


def test_role_changes_are_audited(world, make_user):
    _give_access_email(world, make_user, "amina", "amina@example.com")
    world.admin.post("/api/admin/people/role", json={"email": "amina@example.com", "role": "admin"})
    with world.db.read() as conn:
        row = conn.execute(
            "SELECT detail, target FROM audit_log WHERE action = 'people.role'"
        ).fetchone()
    assert (row["detail"], row["target"]) == ("admin", "user:2")
