import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.access import HEADER, AccessVerifier
from app.config import ConfigError, Settings
from app.main import create_app

TEAM = "example-team.cloudflareaccess.com"
AUD = "test-audience-tag"
ENV = {
    "ARGON2_MEMORY_KIB": "8",
    "ARGON2_TIME_COST": "1",
    "CF_ACCESS_ENABLED": "1",
    "CF_ACCESS_TEAM_DOMAIN": TEAM,
    "CF_ACCESS_AUD": AUD,
}


@pytest.fixture(scope="module")
def keys():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048), rsa.generate_private_key(
        public_exponent=65537, key_size=2048
    )


def make_token(private_key, **overrides):
    now = int(time.time())
    claims = {
        "iss": f"https://{TEAM}",
        "aud": [AUD],
        "iat": now,
        "exp": now + 300,
        "email": "someone@example.com",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private_key, algorithm="RS256")


@pytest.fixture
def gated(db, keys):
    """An app with the gate on and the key set replaced by the local public key."""
    settings = Settings.from_env(ENV)
    app = create_app(settings, db, start_worker=False)
    app.state.access_verifier = AccessVerifier(settings, key_source=lambda _t: keys[0].public_key())
    return TestClient(app)


def test_valid_token_passes_the_gate(gated, keys):
    # /api/me needs a session, so reaching it as 401 (not 403) proves the gate let us through.
    r = gated.get("/api/me", headers={HEADER: make_token(keys[0])})
    assert r.status_code == 401


def test_missing_token_is_rejected(gated):
    r = gated.get("/api/me")
    assert r.status_code == 403
    assert r.json() == {"detail": "access required"}


def test_static_files_are_gated_too(gated, keys):
    assert gated.get("/").status_code == 403
    assert gated.get("/", headers={HEADER: make_token(keys[0])}).status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": ["some-other-app"]},
        {"iss": "https://evil.cloudflareaccess.com"},
        {"exp": int(time.time()) - 60},
        {"aud": None},
        {"exp": None},
    ],
    ids=["wrong-aud", "wrong-issuer", "expired", "no-aud", "no-exp"],
)
def test_bad_claims_are_rejected(gated, keys, overrides):
    r = gated.get("/api/me", headers={HEADER: make_token(keys[0], **overrides)})
    assert r.status_code == 403


def test_token_signed_by_another_key_is_rejected(gated, keys):
    assert gated.get("/api/me", headers={HEADER: make_token(keys[1])}).status_code == 403


def test_unsigned_and_garbage_tokens_are_rejected(gated):
    now = int(time.time())
    unsigned = jwt.encode(
        {"iss": f"https://{TEAM}", "aud": [AUD], "iat": now, "exp": now + 300}, None, "none"
    )
    assert gated.get("/api/me", headers={HEADER: unsigned}).status_code == 403
    assert gated.get("/api/me", headers={HEADER: "not-a-jwt"}).status_code == 403


def test_hs256_token_signed_with_the_public_key_is_rejected(gated, keys):
    # Algorithm-confusion attempt: HMAC using the (public) key bytes as the secret. PyJWT refuses
    # to build this token, so it is assembled by hand.
    import base64
    import hashlib
    import hmac
    import json

    from cryptography.hazmat.primitives import serialization

    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    pem = (
        keys[0]
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    now = int(time.time())
    claims = {"iss": f"https://{TEAM}", "aud": [AUD], "iat": now, "exp": now + 300}
    signing_input = (
        b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        + b"."
        + b64(json.dumps(claims).encode())
    )
    signature = b64(hmac.new(pem, signing_input, hashlib.sha256).digest())
    forged = (signing_input + b"." + signature).decode()
    assert gated.get("/api/me", headers={HEADER: forged}).status_code == 403


def test_healthz_stays_open(gated):
    assert gated.get("/healthz").status_code == 200


def test_disabled_gate_changes_nothing(db):
    app = create_app(Settings.from_env({"ARGON2_MEMORY_KIB": "8"}), db, start_worker=False)
    assert not hasattr(app.state, "access_verifier")
    assert TestClient(app).get("/api/me").status_code == 401


@pytest.mark.parametrize(
    "env",
    [
        {"CF_ACCESS_ENABLED": "1"},
        {"CF_ACCESS_ENABLED": "1", "CF_ACCESS_TEAM_DOMAIN": TEAM},
        {"CF_ACCESS_ENABLED": "1", "CF_ACCESS_AUD": AUD},
    ],
)
def test_enabled_without_team_and_audience_refuses_to_start(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)
