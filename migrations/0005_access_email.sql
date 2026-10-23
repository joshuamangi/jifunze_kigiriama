-- 0005_access_email: the email Cloudflare Access verified for an account. Additive only.
-- Kept apart from users.email (reminders, typed by the user) on purpose: if the two were one,
-- anyone could take over another person's account by typing that person's address as their own
-- reminder email. This column is written only by the Access sign-in or by an admin at the CLI.
-- Access-created accounts have no password; their password_hash is a value that is not a valid
-- hash, so no password can ever verify against it (see app/users.py UNUSABLE_HASH).
ALTER TABLE users ADD COLUMN access_email TEXT;

-- Serves: the Access sign-in lookup `WHERE access_email = ? COLLATE NOCASE`; one account per email.
CREATE UNIQUE INDEX idx_users_access_email ON users (access_email COLLATE NOCASE)
    WHERE access_email IS NOT NULL;
