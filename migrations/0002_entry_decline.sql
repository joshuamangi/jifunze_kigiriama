-- 0002_entry_decline: lets an admin decline a pending entry without deleting it.
-- Additive only (two nullable columns), so a code rollback needs no database restore.
-- A declined entry keeps verification_status = 'pending' and is hidden from everyone but its
-- author and admins. The pending-queue query adds `AND declined_at IS NULL`; it still uses
-- idx_entries_pending, and no new index is needed at this scale.

ALTER TABLE entries ADD COLUMN declined_at TEXT;
ALTER TABLE entries ADD COLUMN declined_by INTEGER REFERENCES users (id) ON DELETE SET NULL;
