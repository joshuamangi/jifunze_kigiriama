"""Edit the Cloudflare Access allow-list (a reusable Access policy) from the app.

Cloudflare replaces a policy on every update, so each change reads the current policy, changes the
email rules and writes the whole thing back. Rules that are not a single email (a domain, a group)
are kept untouched. Uses only the standard library: no new dependency on the Pi.
"""

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable

API = "https://api.cloudflare.com/client/v4"
TIMEOUT_SECONDS = 10
# The fields a PUT accepts. The GET also returns ids and timestamps that must not be sent back.
WRITABLE = (
    "name",
    "decision",
    "include",
    "exclude",
    "require",
    "session_duration",
    "approval_required",
    "approval_groups",
    "isolation_required",
    "purpose_justification_required",
    "purpose_justification_prompt",
    "mfa_config",
    "connection_rules",
)


class CloudflareError(RuntimeError):
    """The Cloudflare call failed. The message is safe to show an admin (never the token)."""


Transport = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]


def _urllib_transport(
    method: str, url: str, headers: dict, body: bytes | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CloudflareError("could not reach Cloudflare") from exc


class AccessPolicyClient:
    def __init__(
        self, token: str, account_id: str, policy_id: str, transport: Transport | None = None
    ) -> None:
        self._token = token
        self._url = f"{API}/accounts/{account_id}/access/policies/{policy_id}"
        self._transport = transport or _urllib_transport
        self._lock = threading.Lock()  # one change at a time: read-modify-write must not interleave

    def _call(self, method: str, body: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        payload = json.dumps(body).encode() if body is not None else None
        status, raw = self._transport(method, self._url, headers, payload)
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        if status >= 300 or not data.get("success"):
            errors = data.get("errors") or []
            detail = "; ".join(str(e.get("message", "")) for e in errors if isinstance(e, dict))
            raise CloudflareError(
                f"Cloudflare answered {status}" + (f": {detail}" if detail else "")
            )
        return data["result"]

    @staticmethod
    def _emails(policy: dict) -> list[str]:
        found = []
        for rule in policy.get("include", []):
            email = rule.get("email", {}).get("email") if isinstance(rule, dict) else None
            if email:
                found.append(email)
        return found

    def list_emails(self) -> tuple[list[str], int]:
        """The allowed emails, and how many other (non-email) rules the policy also has."""
        policy = self._call("GET")
        emails = self._emails(policy)
        return emails, len(policy.get("include", [])) - len(emails)

    def _write(self, policy: dict, include: list) -> None:
        body = {key: policy[key] for key in WRITABLE if key in policy}
        body["include"] = include
        self._call("PUT", body)

    def add_email(self, email: str) -> bool:
        """True if added, False if it was already allowed."""
        with self._lock:
            policy = self._call("GET")
            if email.lower() in (e.lower() for e in self._emails(policy)):
                return False
            self._write(policy, [*policy.get("include", []), {"email": {"email": email}}])
            return True

    def remove_email(self, email: str) -> bool:
        """True if removed, False if it was not on the list. Refuses to empty the policy."""
        with self._lock:
            policy = self._call("GET")
            keep, found = [], False
            for rule in policy.get("include", []):
                address = rule.get("email", {}).get("email") if isinstance(rule, dict) else None
                if address and address.lower() == email.lower():
                    found = True
                else:
                    keep.append(rule)
            if not found:
                return False
            if not keep:
                raise CloudflareError("that is the last allowed person; add someone else first")
            self._write(policy, keep)
            return True
