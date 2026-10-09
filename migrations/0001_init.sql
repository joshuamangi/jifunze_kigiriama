-- 0001_init: full initial schema. Never edit once applied; add 0002_... instead.
-- Timestamps are UTC ISO-8601 text. Dates (due_date, last_sent_on) are YYYY-MM-DD.

CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL,
    email         TEXT,                       -- used only for reminders; optional
    password_hash TEXT NOT NULL,              -- argon2id, set in Stage 2
    role          TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Serves: login lookup `WHERE username = ? COLLATE NOCASE`; also stops duplicate accounts.
CREATE UNIQUE INDEX idx_users_username ON users (username COLLATE NOCASE);

CREATE TABLE sessions (
    token_hash   TEXT PRIMARY KEY,            -- SHA-256 of the cookie token; never the token
    user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at   TEXT NOT NULL
);

-- Serves: "log this user out everywhere" and cascade deletes `WHERE user_id = ?`.
CREATE INDEX idx_sessions_user ON sessions (user_id);
-- Serves: expired-session cleanup `DELETE ... WHERE expires_at < ?`.
CREATE INDEX idx_sessions_expires ON sessions (expires_at);

CREATE TABLE entries (
    id                  INTEGER PRIMARY KEY,
    giriama             TEXT NOT NULL,        -- Kigiriama text; only ever typed by a person
    english             TEXT NOT NULL,        -- the only column that is embedded
    category            TEXT NOT NULL,
    source_type         TEXT NOT NULL
        CHECK (source_type IN ('own', 'dictionary', 'proverb', 'scripture')),
    verification_status TEXT NOT NULL
        CHECK (verification_status IN ('pending', 'unverified', 'self_corrected', 'native_verified')),
    created_by          INTEGER REFERENCES users (id) ON DELETE SET NULL,  -- NULL = seeded
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    embedded_at         TEXT                  -- NULL until the worker has stored the vector
);

-- Serves: group filter `WHERE category = ? ORDER BY created_at DESC` and the per-category
-- counts behind the "today's gap" suggestion.
CREATE INDEX idx_entries_category_created ON entries (category, created_at DESC);
-- Serves: admin review queue `WHERE verification_status = 'pending' ORDER BY created_at`.
-- Partial, so it only holds what is waiting.
CREATE INDEX idx_entries_pending ON entries (created_at) WHERE verification_status = 'pending';

CREATE TABLE entry_history (
    id                      INTEGER PRIMARY KEY,
    entry_id                INTEGER NOT NULL REFERENCES entries (id) ON DELETE CASCADE,
    changed_by              INTEGER REFERENCES users (id) ON DELETE SET NULL,
    changed_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    old_giriama             TEXT NOT NULL,
    old_english             TEXT NOT NULL,
    old_category            TEXT NOT NULL,
    old_source_type         TEXT NOT NULL,
    old_verification_status TEXT NOT NULL
);

-- Serves: an entry's edit history in order `WHERE entry_id = ? ORDER BY changed_at`;
-- also the foreign-key lookup when an entry is deleted.
CREATE INDEX idx_entry_history_entry ON entry_history (entry_id, changed_at);

-- SRS state is per user and lives here, never on entries (entries are shared).
CREATE TABLE user_progress (
    user_id       INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    entry_id      INTEGER NOT NULL REFERENCES entries (id) ON DELETE CASCADE,
    interval      INTEGER NOT NULL DEFAULT 0,      -- days
    ease_factor   REAL NOT NULL DEFAULT 2.5,
    due_date      TEXT NOT NULL,
    last_reviewed TEXT,
    PRIMARY KEY (user_id, entry_id)                -- one row per user per entry; review = upsert
);

-- Serves: the hottest query, "what is due for this user?"
-- `WHERE user_id = ? AND due_date <= ? ORDER BY due_date`.
CREATE INDEX idx_user_progress_due ON user_progress (user_id, due_date);

-- Grammar rules are data, extracted once from Taylor's front matter and then hand-checked.
-- Nothing is generated; rows only exist if the owner imported them.
CREATE TABLE noun_classes (
    id           INTEGER PRIMARY KEY,
    label        TEXT NOT NULL,
    rule_json    TEXT NOT NULL CHECK (json_valid(rule_json)),
    source_page  TEXT,
    confidence   TEXT CHECK (confidence IN ('low', 'medium', 'high')),
    hand_checked INTEGER NOT NULL DEFAULT 0 CHECK (hand_checked IN (0, 1))
);

CREATE TABLE verb_paradigms (
    id           INTEGER PRIMARY KEY,
    label        TEXT NOT NULL,
    rule_json    TEXT NOT NULL CHECK (json_valid(rule_json)),
    source_page  TEXT,
    confidence   TEXT CHECK (confidence IN ('low', 'medium', 'high')),
    hand_checked INTEGER NOT NULL DEFAULT 0 CHECK (hand_checked IN (0, 1))
);

CREATE TABLE reminders (
    user_id      INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    enabled      INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    send_at      TEXT NOT NULL DEFAULT '18:00',    -- local time of day, HH:MM
    last_sent_on TEXT                              -- date of last send; makes the job idempotent
);

-- Keyword search over both languages. Diacritics are NOT folded (remove_diacritics 0): folding
-- is a linguistic decision about Kigiriama that the owner must make, not a default.
CREATE VIRTUAL TABLE entries_fts USING fts5 (
    english,
    giriama,
    content = 'entries',
    content_rowid = 'id',
    tokenize = 'unicode61 remove_diacritics 0'
);

CREATE TRIGGER entries_fts_insert AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts (rowid, english, giriama) VALUES (new.id, new.english, new.giriama);
END;

CREATE TRIGGER entries_fts_delete AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts (entries_fts, rowid, english, giriama)
    VALUES ('delete', old.id, old.english, old.giriama);
END;

CREATE TRIGGER entries_fts_update AFTER UPDATE OF english, giriama ON entries BEGIN
    INSERT INTO entries_fts (entries_fts, rowid, english, giriama)
    VALUES ('delete', old.id, old.english, old.giriama);
    INSERT INTO entries_fts (rowid, english, giriama) VALUES (new.id, new.english, new.giriama);
END;

-- Semantic search. Holds embeddings of entries.english ONLY (never Kigiriama text).
-- 384 dimensions = MiniLM-class models; changing it later needs a new migration.
CREATE VIRTUAL TABLE entry_vec USING vec0 (
    entry_id INTEGER PRIMARY KEY,
    embedding FLOAT[384]
);
