-- 0006_user_disabled: lets an admin take someone out without deleting their account. Additive only.
-- Removing a person from the Cloudflare allow-list does not end an Access sign-in they already
-- hold (up to 24 hours), so the app must refuse them itself: a disabled account gets no session
-- and its existing sessions stop working. Entries and progress stay.
ALTER TABLE users ADD COLUMN disabled_at TEXT;
