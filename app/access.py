"""Optional second gate: verify the Cloudflare Access JWT on every request.

Cloudflare Access puts a signed token in the Cf-Access-Jwt-Assertion header after the visitor
passes the email allow-list. With CF_ACCESS_ENABLED=1 the app refuses anything without a valid
token (RS256 signature from the team's published keys, issuer, audience, expiry), so traffic that
reaches the machine around Access is rejected. /healthz stays open for the local health checks.
The app login still applies afterwards: these are two separate gates.
"""

import logging

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import Settings

HEADER = "cf-access-jwt-assertion"
EXEMPT_PATHS = {"/healthz"}
log = logging.getLogger("jifunze.access")


class AccessVerifier:
    """Checks one token. `key_source` returns the signing key for a token; the default fetches the
    team's key set (cached by PyJWT), tests pass a function that returns a local public key."""

    def __init__(self, settings: Settings, key_source=None) -> None:
        self.audience = settings.cf_access_aud
        self.issuer = f"https://{settings.cf_access_team_domain}"
        if key_source is None:
            keys = jwt.PyJWKClient(
                f"{self.issuer}/cdn-cgi/access/certs", cache_keys=True, lifespan=3600, timeout=5
            )

            def key_source(token: str):
                return keys.get_signing_key_from_jwt(token).key

        self._key_source = key_source

    def verify(self, token: str) -> dict:
        """Return the claims, or raise jwt.PyJWTError. Only RS256 is accepted, so a token cannot
        pick a weaker algorithm (such as "none") for itself."""
        return jwt.decode(
            token,
            self._key_source(token),
            algorithms=["RS256"],
            audience=self.audience,
            issuer=self.issuer,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )


def install_access_gate(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    if not settings.cf_access_enabled:
        return
    app.state.access_verifier = AccessVerifier(settings)

    @app.middleware("http")
    async def access_gate(request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        token = request.headers.get(HEADER)
        if token:
            try:
                await run_in_threadpool(request.app.state.access_verifier.verify, token)
            except jwt.PyJWTError as exc:
                log.warning("access token rejected: %s", type(exc).__name__)
            else:
                return await call_next(request)
        return JSONResponse({"detail": "access required"}, status_code=403)
