"""Audit record: who did what, from where. Written to the audit_log table.

Never put a password, token or session cookie in `detail`. A failed audit write is logged and
swallowed: it must not turn a successful login or approval into an error for the person using it.
"""

import logging
from typing import Any

from fastapi import Request

from app.db import Database
from app.observability import request_id_var
from app.security import client_address

log = logging.getLogger("jifunze.audit")


def record(
    db: Database,
    action: str,
    *,
    request: Request | None = None,
    actor: dict | None = None,
    actor_name: str | None = None,
    target: str | None = None,
    detail: str | None = None,
) -> None:
    address = client_address(request) if request is not None else None
    name = actor["username"] if actor else actor_name
    try:
        with db.write() as conn:
            conn.execute(
                "INSERT INTO audit_log (request_id, actor_id, actor_name, action, target, detail,"
                " address) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    request_id_var.get(),
                    actor["id"] if actor else None,
                    name[:64] if name else None,
                    action,
                    target,
                    detail[:200] if detail else None,
                    address,
                ),
            )
    except Exception:
        log.exception("audit write failed", extra={"fields": {"action": action}})
        return
    # The same event on the log stream, so journald shows it without querying the database.
    fields: dict[str, Any] = {"action": action, "actor": name, "target": target, "address": address}
    log.info("audit", extra={"fields": fields})
