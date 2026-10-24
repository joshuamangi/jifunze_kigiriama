"""The invite email. It says where the app is and what to expect; it never carries a password or
a sign-in link, because Cloudflare sends its own one-time PIN when the person opens the site."""

import logging

from app.services.reminders import Backend

log = logging.getLogger("jifunze.invites")


def compose(inviter: str, base_url: str) -> tuple[str, str]:
    subject = "You are invited to Jifunze Kigiriama"
    body = "\n".join(
        [
            f"{inviter} has invited you to Jifunze Kigiriama, an app for learning Kigiriama.",
            "",
            f"Open it here: {base_url}",
            "",
            "Enter this email address when asked. Cloudflare then sends you a short one-time code"
            " by email; type it in and you are signed in. There is no password to remember.",
            "",
            "If you were not expecting this, you can ignore this email.",
        ]
    )
    return subject, body


def send_invite(mailer: Backend | None, to: str, inviter: str, base_url: str) -> bool:
    """Best effort: True if the email was sent. A failure is logged (without the address) and
    reported to the admin, never raised, so a mail problem cannot undo an invite."""
    if mailer is None or not base_url:
        return False
    try:
        subject, body = compose(inviter, base_url)
        mailer.send(to, subject, body)
    except Exception as exc:  # noqa: BLE001 - any mail failure must not break the invite
        log.warning("invite email failed: %s", type(exc).__name__)
        return False
    return True
