# From prototype to project: build plan and prompts

> **Superseded by `docs/IMPLEMENTATION.md`** (11 stages, 0 to 10). Kept for its Pi budget and working habits. Where the two differ, IMPLEMENTATION.md wins.

Put this file at `docs/BUILD_PLAN.md`. Put the prototype screens at `docs/prototype/`. Run the prompts in order, one per Claude Code session, and commit after each phase.

## What the prototype is, and isn't

- The seven `.dc.html` files are a **visual and behavioural spec**, not code to ship. They use a proprietary template format (`sc-for`, `sc-if`, `{{holes}}`, a `DCLogic` class) that needs the design tool's own runtime (`support.js`), which isn't in the zip. They won't run standalone in a browser.
- Reusable as-is: layout, spacing, copy, the theme tokens (`docs/theme.css`), the SVG icon paths, the five-item nav, and the interaction logic inside each `renderVals()` (filtering, category counts, suggested-gap logic, approve/decline).
- Not real: every list is in-memory seed data. There is no persistence, no search, no auth, no email. The Add Entry search box is a text filter, not semantic search. The prototype says so on screen, and the real build has to replace each of those.
- The only verified Kigiriama in it is the numbers (mwenga, hiri, hahu, tsano, inne). Don't treat anything else as data.

## Decisions to make before prompting

1. **Frontend**: plain HTML/CSS/JS with small ES modules (lightest on the Pi, no build step) vs Svelte (nicer state handling, needs a build on your Mac, ships static files). Default: plain JS + a tiny router. Svelte only if you'd rather write components.
2. **Where the build runs**: develop on your Mac, deploy to the Pi by `git pull` + `systemctl restart`. Don't run the editor workload on the Pi.
3. **Embeddings**: do you want them on-device (slower, private, ~90MB model, ~300-500MB RAM while loaded) or computed lazily on save? Default: on-device, loaded once at startup, English only.
4. **Auth**: server-side sessions in SQLite (default) plus Cloudflare Access in front.

## Pi budget (design constraints to give Claude)

- 4GB RAM shared with the OS, the tunnel and the embedding model. Target under 800MB steady state for the app.
- One Uvicorn worker. SQLite in WAL mode, one writer, short transactions.
- Load the embedding model once at startup; never per request. Run embedding on a background thread and queue it, so saving an entry returns immediately.
- Vector search over a personal-scale corpus (low thousands of rows) can be brute-force `vec0` KNN. No ANN tuning.
- Database on the USB SSD. Daily `sqlite3 .backup` to a second location.
- Static assets served with long cache headers + a service worker, so most taps never reach the Pi.
- No heavy per-request work: PDF/OCR ingestion is an offline script, not a web route.

## Phase 0: orientation

> Read CLAUDE.md and docs/BUILD_PLAN.md. Open every file in docs/prototype/ and, for each screen, list: the data it shows, the user actions it supports, the state it holds, and which parts are fake. Then propose the module layout for the app (backend, frontend, migrations, scripts) with a one-line reason per folder. Don't write code yet.

## Phase 1: schema and migrations

> Design the SQLite schema for entries, entry_vec (sqlite-vec vec0, English side only), users, sessions, user_progress, entry_history, noun_classes, verb_paradigms and reminders, matching the invariants in CLAUDE.md. Write numbered migrations in migrations/ and a small migration runner. Enable WAL, foreign keys and a busy_timeout. Explain each index you add and why, given the Pi. Seed only the verified numbers listed in CLAUDE.md. Add tests that migrations apply cleanly to an empty database and are idempotent.

## Phase 2: backend core

> Build the FastAPI app: config from environment variables, DB connection handling suited to a single-writer SQLite, and routes for entries (create, edit in place with history, list with category and text filters), categories, and a /healthz. Bind to 127.0.0.1. Keep dependencies minimal and justify each one. Include tests with a temporary database.

## Phase 3: auth and admin review

> Implement login, logout and sessions per the Auth section of CLAUDE.md: argon2 hashing, HttpOnly Secure SameSite=Lax cookies, login rate limiting, no self sign-up, and a CLI command to create the first admin and later accounts. Member submissions are stored as verification_status=pending and are hidden from other users until approved. Build the admin review endpoints (list pending, approve, decline) with server-side role checks. Write tests proving a member cannot read pending entries of others or call admin routes.

## Phase 4: semantic search (Pi-optimised)

> Add semantic search over the English meaning. Choose a small embedding model that runs on a Raspberry Pi 4 (CPU only, ARM64), tell me the memory and per-embedding latency you expect, and verify with a benchmark script rather than assuming. Load it once at startup, embed on a background worker after an entry is saved, and store vectors in sqlite-vec. Provide a search endpoint that returns entries ranked by similarity to an English query, and a `reindex` command. The Kigiriama text must never be embedded. Report peak RSS during a reindex of 2,000 synthetic English rows.

## Phase 5: frontend from the prototype

> Rebuild the seven screens as a real mobile-first PWA using docs/prototype/ as the visual reference and docs/theme.css for tokens. Use the design rules in CLAUDE.md. Replace seed data with API calls. Implement: Login, Home (streak, entries count, suggested topics from the category with the fewest entries), Add Entry (form, category and source chips, search, filter by group, edit in place), Learn (8-tier ladder, locked tiers), Culture (links), Settings (reminders, appearance, admin card visible only to admins) and Review. Add a manifest and a service worker that caches the app shell. Keep the JS payload small and tell me the total transferred size of a cold load.

## Phase 6: grammar and drills

> From Taylor's dictionary front matter (OCR text), build an offline script that extracts candidate noun-class and verb-paradigm rules into a review file. Nothing goes into the database until I have checked it by hand; mark each row's confidence and the page it came from. Then build drills that combine verified rules with entries I have added. Do not generate Kigiriama forms the rules don't license; when a drill needs a form we don't have, skip the item.

## Phase 7: spaced repetition and reminders

> Implement SM-2 style scheduling on user_progress and a daily session of about 20 minutes assembled from due items plus new ones. Add the email reminder job as a systemd timer that reads the reminders table and sends through SMTP credentials from the environment. Make it safe to run twice (idempotent) and log to journald.

## Phase 8: deploy to the Pi

> Write deployment files for the Raspberry Pi: a systemd unit for Uvicorn (one worker, 127.0.0.1:8000, restart on failure, MemoryMax set), a systemd timer for reminders and for nightly `sqlite3 .backup`, an environment file template, and a cloudflared config for a named tunnel. Write a deploy script (git pull, migrate, restart, health check) and a rollback note. Don't include secrets. List every manual step I must do on the Pi, in order.

## Phase 9: hardening review

> Review the whole project for security and for Raspberry Pi suitability. Check: every route's auth, admin checks done server-side, cookie flags, rate limiting, SQL injection, XSS in user-entered Kigiriama and English text, secrets in git, backup and restore tested, memory under load, SD/SSD write volume. Report findings ranked by severity with file and line, and fix only what I approve.

## Habits that keep the build honest

- Ask for a plan before any change to schema, auth, or SRS, then approve it.
- After each phase: run tests, commit, start a fresh session so context stays small.
- When Claude proposes Kigiriama text anywhere, reject it. Examples must come from your own entries or the verified list.
- Keep `CLAUDE.md` current: when you decide something, add one line.
