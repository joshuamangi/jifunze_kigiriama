"""Invite and remove people (admin only). The allow-list lives in Cloudflare Access; the app
edits it through the Cloudflare API and keeps no copy. Removing someone also disables their account
here, because their current Cloudflare sign-in can last up to a day."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import audit
from app.auth.deps import get_db, get_settings, require_admin
from app.config import Settings
from app.db import Database
from app.services.cloudflare import AccessPolicyClient, CloudflareError
from app.services.invites import send_invite
from app.users import EMAIL_RE, set_disabled

router = APIRouter()

Admin = Annotated[dict, Depends(require_admin)]
Db = Annotated[Database, Depends(get_db)]


class EmailBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)


def _client(request: Request) -> AccessPolicyClient:
    client = getattr(request.app.state, "cloudflare", None)
    if client is None:
        raise HTTPException(status_code=503, detail="invites are not set up on this server")
    return client


def _email(body: EmailBody) -> str:
    email = body.email.strip()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="that does not look like an email address")
    return email


def _cloudflare_failed(exc: CloudflareError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/api/admin/people")
def people(admin: Admin, db: Db, request: Request) -> dict:
    client = getattr(request.app.state, "cloudflare", None)
    if client is None:
        return {"enabled": False, "people": [], "other_rules": 0}
    try:
        emails, other_rules = client.list_emails()
    except CloudflareError as exc:
        raise _cloudflare_failed(exc) from None
    with db.read() as conn:
        rows = conn.execute(
            "SELECT access_email, username, role, disabled_at FROM users"
            " WHERE access_email IS NOT NULL"
        ).fetchall()
    accounts = {r["access_email"].lower(): r for r in rows}
    listed = []
    for email in sorted(emails, key=str.lower):
        account = accounts.get(email.lower())
        listed.append(
            {
                "email": email,
                "username": account["username"] if account else None,
                "role": account["role"] if account else None,
                "signed_in_before": account is not None,
                "is_you": bool(account and account["username"] == admin["username"]),
            }
        )
    return {"enabled": True, "people": listed, "other_rules": other_rules}


@router.post("/api/admin/people")
def invite(
    body: EmailBody,
    admin: Admin,
    db: Db,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    email = _email(body)
    client = _client(request)
    try:
        added = client.add_email(email)
    except CloudflareError as exc:
        raise _cloudflare_failed(exc) from None
    set_disabled(db, email, False)  # inviting someone who was removed brings them back
    emailed = send_invite(
        getattr(request.app.state, "mailer", None), email, admin["username"], settings.app_base_url
    )
    audit.record(
        db,
        "people.invite",
        request=request,
        actor=admin,
        detail=f"added={added} emailed={emailed}",
    )
    return {"email": email, "added": added, "emailed": emailed}


@router.post("/api/admin/people/remove")
def remove(body: EmailBody, admin: Admin, db: Db, request: Request) -> dict:
    email = _email(body)
    with db.read() as conn:
        mine = conn.execute(
            "SELECT access_email FROM users WHERE id = ?", (admin["id"],)
        ).fetchone()
    if mine and mine["access_email"] and mine["access_email"].lower() == email.lower():
        raise HTTPException(status_code=409, detail="you cannot remove yourself")
    client = _client(request)
    try:
        removed = client.remove_email(email)
    except CloudflareError as exc:
        raise _cloudflare_failed(exc) from None
    account = set_disabled(db, email, True)
    audit.record(
        db,
        "people.remove",
        request=request,
        actor=admin,
        target=f"user:{account['id']}" if account else None,
        detail=f"removed={removed}",
    )
    return {"email": email, "removed": removed, "had_account": account is not None}
