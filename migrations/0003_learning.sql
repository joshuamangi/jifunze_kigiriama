-- 0003_learning: what spaced repetition, the streak and reminders need. Additive only (new
-- nullable-or-defaulted columns and one new table), so a code rollback needs no database restore.

-- SM-2 needs the count of consecutive successful reviews; it cannot be recovered from interval.
ALTER TABLE user_progress ADD COLUMN repetitions INTEGER NOT NULL DEFAULT 0;

-- The Settings screen offers "every day" or "weekdays only".
ALTER TABLE reminders ADD COLUMN frequency TEXT NOT NULL DEFAULT 'daily'
    CHECK (frequency IN ('daily', 'weekdays'));

-- Append-only history of reviews. user_progress stays the only SRS state; this log exists to
-- compute the streak, "new cards introduced today" and the daily session size.
CREATE TABLE review_log (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    entry_id    INTEGER NOT NULL REFERENCES entries (id) ON DELETE CASCADE,
    reviewed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    reviewed_on TEXT NOT NULL,                     -- local date (APP_TIMEZONE), YYYY-MM-DD
    drill       TEXT NOT NULL CHECK (drill IN ('spell', 'recognise', 'recall')),
    grade       TEXT NOT NULL CHECK (grade IN ('again', 'hard', 'good', 'easy')),
    was_new     INTEGER NOT NULL CHECK (was_new IN (0, 1))
);

-- Serves: the streak (`DISTINCT reviewed_on WHERE user_id = ? AND reviewed_on >= ?`) and
-- "new cards introduced today" (`WHERE user_id = ? AND reviewed_on = ? AND was_new = 1`).
CREATE INDEX idx_review_log_user_day ON review_log (user_id, reviewed_on);
