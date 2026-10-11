"""Request guards: CSRF protection, body-size limit, security headers, request ids and the
access log, and client-address resolution."""

import json
import logging
import time
import uuid
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings
from app.observability import request_id_var

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


# Everything is served from our own origin: scripts, styles and the Kodchasan font files
# (web/fonts, declared in web/css/fonts.css). No inline script or style is allowed, so an
# injected <script> or onclick= attribute does nothing. Nothing may frame the app.
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "manifest-src 'self'",
        "worker-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
HSTS = "max-age=31536000; includeSubDomains"
log = logging.getLogger("jifunze.http")


class RequestContextMiddleware:
    """Outermost layer: assigns the request id, adds the security headers to every response
    (including errors from inner layers) and writes one access-log line per request."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.hsts = settings.cookie_secure  # HTTPS in production; over plain dev http it is noise

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:16]  # never taken from the client
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        path = scope["path"]

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = message.setdefault("headers", [])
                extra = {
                    b"x-request-id": request_id,
                    b"content-security-policy": CSP,
                    b"x-content-type-options": "nosniff",
                    b"referrer-policy": "same-origin",
                    b"permissions-policy": "camera=(), microphone=(), geolocation=()",
                    b"cross-origin-opener-policy": "same-origin",
                }
                if self.hsts:
                    extra[b"strict-transport-security"] = HSTS
                if path.startswith("/api/"):
                    extra[b"cache-control"] = "no-store"  # personal data must not sit in caches
                present = {name.lower() for name, _ in headers}
                headers.extend((k, v.encode()) for k, v in extra.items() if k not in present)
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            # The query string is left out on purpose: search terms are private to the user.
            fields = {
                "method": scope["method"],
                "path": path,
                "status": status,
                "duration_ms": elapsed_ms,
            }
            level = logging.DEBUG if path == "/healthz" else logging.INFO
            log.log(level, "request", extra={"fields": fields})
            request_id_var.reset(token)


class BodyLimitMiddleware:
    """Refuse request bodies over max_bytes with 413, whether or not Content-Length is honest."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"0")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        started = False
        rejected = False

        async def counting_receive() -> Message:
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request" and not rejected:
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Answer now, then tell the app the client is gone so it stops reading.
                    rejected = True
                    if not started:
                        await self._reject(send)
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return  # the 413 has been sent; whatever the app says next is dropped
            started = started or message["type"] == "http.response.start"
            await send(message)

        await self.app(scope, counting_receive, tracking_send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = json.dumps({"detail": "request body too large"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
