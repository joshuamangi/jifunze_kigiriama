"""Request guards: CSRF protection for state-changing requests and client-address resolution."""

from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import Settings

CUSTOM_HEADER = "x-requested-with"
CUSTOM_HEADER_VALUE = "jifunze"
STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
_LOCAL_PEERS = {"127.0.0.1", "::1", "localhost"}


def origin_allowed(request: Request, settings: Settings) -> bool:
    """No Origin header is fine (non-browser client); if present it must match."""
    origin = request.headers.get("origin")
    if origin is None:
        return True
    origin = origin.rstrip("/")
    if settings.allowed_origins:
        return origin in settings.allowed_origins
    return urlsplit(origin).netloc == request.headers.get("host", "")


def client_address(request: Request) -> str:
    """Source address for throttling.

    CF-Connecting-IP is believed only when the direct peer is local (cloudflared/Nginx on this
    machine, or a Unix socket, which has no client address). From anywhere else the header could
    be forged, so the peer address is used.
    """
    peer = request.client.host if request.client else None
    if peer is None or peer in _LOCAL_PEERS:
        forwarded = request.headers.get("cf-connecting-ip", "").strip()
        if forwarded:
            return forwarded
    return peer or "local"


def install_request_guard(app: FastAPI) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.method in STATE_CHANGING:
            settings: Settings = request.app.state.settings
            header_ok = request.headers.get(CUSTOM_HEADER) == CUSTOM_HEADER_VALUE
            if not header_ok or not origin_allowed(request, settings):
                return JSONResponse({"detail": "request rejected"}, status_code=403)
        return await call_next(request)
