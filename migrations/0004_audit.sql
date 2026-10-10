-- 0004_audit: an append-only record of security-relevant events (logins, failures, moderation,
-- admin actions). Additive only. There is deliberately no foreign key to users: the record must
-- outlive the account it describes, and a failed login names a user that may not exist.
CREATE TABLE audit_log (
    id         INTEGER PRIMARY KEY,
    at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    request_id TEXT,                 -- joins this row to the structured log lines of the request
    actor_id   INTEGER,              -- NULL when nobody is signed in (failed login) or a CLI action
    actor_name TEXT,                 -- for a failed login: the username that was tried
    action     TEXT NOT NULL,        -- e.g. login.failure, entry.approve
    target     TEXT,                 -- e.g. entry:12, user:3
    detail     TEXT,                 -- short, never a password or token
    address    TEXT                  -- client address as seen by client_address()
);

-- Serves: "recent failed logins" `WHERE action = ? AND at >= ?` (the admin status count). The
-- only query so far; add more indexes when a screen needs them, as each costs a write per event.
CREATE INDEX idx_audit_action ON audit_log (action, at DESC);
