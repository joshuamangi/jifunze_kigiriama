# Jifunze Kigiriama: staged implementation guide

Put this file at `docs/IMPLEMENTATION.md`. It turns the design report into eleven stages (0 to 10). Stages 0 to 7 run and are tested on `localhost` on your Mac. Stages 8 to 10 produce the deployment files for the Raspberry Pi, GitHub Actions and Cloudflare Tunnel.

## How to use it

Start a Claude Code session in the project folder and paste this:

> Read CLAUDE.md, docs/BUILD_PLAN.md and docs/IMPLEMENTATION.md. Work on **Stage 0 only**. Follow the "Rules for every stage" section. When the stage is done, show me how to run and test it, then stop and wait for me to say "go to stage 1".

Then for each later stage:

> Go to stage N. Re-read the stage, state your plan in a few lines first, then implement.

Commit after each stage (`git commit -m "stage N: ..."`) and start a fresh session so the context stays small.

## Rules for every stage

1. **Do only the current stage.** Don't build ahead, and don't leave stubs for later stages unless the stage says so.
2. **Plan first** in at most ten lines: files you will create or change and why. Then implement.
3. **Tests come with the code.** `make test` must pass before you say a stage is done. Add a test for each rule in the stage's acceptance list.
4. **End every stage with this report, then stop:**
   - what changed (files)
   - how to run it (exact commands)
   - how I test it by hand (click path or curl commands, with expected output)
   - what is deliberately not done yet
5. **Never invent Kigiriama.** Seed and test data may use only the verified numbers in CLAUDE.md. If a feature needs a Kigiriama form you don't have, leave it out and say so.
6. **Spelling:** Kigiriama and Giriama, never Kigiryama or Giryama.
7. **Pi budget:** one Uvicorn worker, SQLite in WAL mode, no new dependency without a one-line reason. Explain any dependency that has no ARM64 wheel.
8. **Ask before** destructive schema changes, anything under `deploy/` or `infra/` that touches secrets, and any change to auth.
9. **No secrets in git.** Everything configurable comes from environment variables, with a documented `.env.example`.
10. If this file and CLAUDE.md disagree, stop and ask.

## How the stage prompts work

Each stage below has a **Prompt to paste**. It is written to make Claude produce the stage goal in a checkable form: it names the goal, the constraints that matter, the proof that the stage is done, and where to stop. The pattern is the same every time, so you can adapt it for your own prompts:

1. **Goal in one sentence**, stated as an outcome you can see, not a task list.
2. **Context to read first**: the files that hold the decisions.
3. **Constraints that would be easy to break**: the Pi budget, no invented Kigiriama, the security rules for this stage.
4. **Proof**: the tests and manual checks that must pass.
5. **Stop instruction**: report, then wait.

Two helper prompts to use between stages:

> **Review prompt.** Act as a sceptical reviewer who did not write this code. Read the diff for the stage we just finished. List anything that breaks a rule in CLAUDE.md or docs/IMPLEMENTATION.md, any test that passes without proving its claim, and anything that will behave differently on the Raspberry Pi 4 (memory, CPU, ARM64 wheels, SSD writes). Rank findings by severity with file and line. Do not fix anything yet.

> **Fix prompt.** Fix only these findings: (paste the ones you approve). Don't change anything else. Add or adjust a test for each fix, run `make test`, and report what changed.

And one for when a stage goes wrong:

> Stop. Don't write more code. Tell me what you expected to happen, what actually happened, and the single most likely cause, with the evidence from the logs or test output. Then propose the smallest change that tests that cause.

## Fixed decisions (don't re-litigate)

| Area | Decision |
| --- | --- |
| Backend | Python 3.11+, FastAPI, Uvicorn (one worker), Pydantic v2 |
| Database | SQLite (WAL), `sqlite-vec` for vectors, FTS5 for keywords, numbered SQL migrations |
| Auth | Server-side sessions in SQLite, argon2id, HttpOnly + Secure + SameSite=Lax cookie. No JWT |
| Front end | Plain HTML, CSS and JavaScript ES modules. No build step. Served as static files |
| Embeddings | Behind an `Embedder` interface: `FakeEmbedder` (deterministic, for tests and quick local runs) and a real small CPU model. English text only |
| Proxy | Cloudflare Tunnel, then Nginx on `127.0.0.1:8080`, then a Unix socket to Uvicorn |
| Deploy | GitHub Actions: tests on hosted runners, deploy job on a self-hosted runner on the Pi, release folders with a `current` symlink |
| Process manager | systemd (no Docker) |
| IaC | Ansible for the machine, systemd units and Nginx and cloudflared config in git, secrets with `sops` and `age` |

## Target repository layout

Claude may adjust names, but keep the shape.

```
CLAUDE.md
Makefile
pyproject.toml
requirements.lock            # hash-pinned, generated
.env.example
app/
  main.py                    # app factory, lifespan
  config.py                  # env settings
  db.py                      # connections, pragmas, read pool, write lock
  auth/                      # hashing, sessions, deps, throttle
  api/                       # routers: entries, review, search, learn, admin
  services/                  # entries, moderation, srs, reminders
  embeddings/                # base.py, fake.py, real.py, worker.py
  security.py                # headers, origin check
migrations/                  # 0001_init.sql, ...
scripts/                     # create_user.py, reindex.py, send_reminders.py, bench_*.py
web/                         # index.html, manifest.webmanifest, sw.js, css/, js/
tests/
deploy/
  deploy.sh  rollback.sh  backup.sh  healthcheck.sh
  systemd/   nginx/   cloudflared/
infra/
  ansible/   terraform/      # terraform optional
.github/workflows/
docs/
  BUILD_PLAN.md  IMPLEMENTATION.md  theme.css  prototype/  PI_SETUP.md
```

`make` targets to create in Stage 0 and keep working: `install`, `run`, `test`, `lint`, `migrate`, `create-user`, `reindex`.

---

## Stage 0: scaffold

**Goal:** an empty but correct project that runs on localhost and has tooling in place.

**Prompt to paste**
> Goal: a project skeleton that starts on localhost and answers `/healthz`, with lint, test and secret scanning already working, so every later stage has a safe place to land.
> Read CLAUDE.md and docs/IMPLEMENTATION.md (Stage 0 and "Rules for every stage") first.
> Constraints: Python 3.11+, FastAPI, one Uvicorn worker, settings only from environment variables with a documented `.env.example`, no secret or database file tracked by git, and no feature code beyond `/healthz`.
> Proof: `make install`, `make run`, `make lint` and `make test` all work from a clean checkout; `curl localhost:8000/healthz` returns 200.
> Make a plan of at most ten lines, implement it, then give me the stage report and stop.

**Build**
- `pyproject.toml`, virtual environment, `ruff` (lint and format), `pytest`, `pre-commit` with a secret scanner.
- `app/main.py` with an app factory, a `lifespan` handler (empty for now) and `GET /healthz` returning `{"status":"ok"}`.
- `app/config.py` reading environment variables with safe defaults for local use: `APP_ENV` (`dev` or `prod`), `DATABASE_PATH`, `COOKIE_SECURE` (false in dev), `SESSION_SECRET`.
- `.env.example`, `.gitignore` (env files, database files, `__pycache__`, credentials), `Makefile`.
- A test that calls `/healthz`.

**Run locally:** `make install && make run`, then open `http://localhost:8000/healthz`.

**Acceptance:** `make lint` and `make test` pass; `/healthz` returns 200; no secret or database file is tracked by git.

---

## Stage 1: database, migrations and indexes

**Goal:** the schema from the design report, applied by a migration runner, with the indexes tied to named queries.

**Prompt to paste**
> Goal: a SQLite database that is created only by numbered migrations, runs in WAL mode, and has an index for each hot query we named in the design report and no others.
> Read CLAUDE.md (data model section), docs/IMPLEMENTATION.md Stage 1, and the "Database indexing" section of the design report if I paste it.
> Constraints: `user_progress` holds per-user spaced-repetition state, never `entries`; `entries.embedded_at` is nullable so a worker can resume; only the verified numbers in CLAUDE.md may be seeded; every index gets a comment naming the query it serves; the migration runner must refuse an edited, already applied file.
> Proof: tests that migrations apply cleanly and twice, that `EXPLAIN QUERY PLAN` shows the intended index for the due-items, category-filter, pending-queue and username queries, that foreign keys are enforced, and that a `vec0` insert and nearest-neighbour query works. If this Python cannot load SQLite extensions, tell me exactly what to install.
> Plan first, implement, report, stop.

**Build**
- `app/db.py`: on every connection set `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, `foreign_keys=ON`. Provide a small pool of read connections and a single write connection guarded by a lock. Load `sqlite-vec` into each connection.
- Migration runner: applies `migrations/NNNN_*.sql` in order inside a transaction, records them in a `schema_migrations` table, refuses to run an edited, already applied file (store a checksum).
- `0001_init.sql`: `users`, `sessions`, `entries`, `entry_history`, `user_progress`, `noun_classes`, `verb_paradigms`, `reminders`, an FTS5 table for `english` and `giriama`, and a `vec0` table for English embeddings.
- Indexes, each with a comment naming the query it serves:
  - `user_progress (user_id, due_date)` and primary key `(user_id, entry_id)`
  - `entries (category, created_at DESC)`
  - partial index on `entries (created_at) WHERE verification_status = 'pending'`
  - `entry_history (entry_id, changed_at)`, `sessions (user_id)`, `sessions (expires_at)`
  - `users (username COLLATE NOCASE)` unique
- `entries` includes `embedded_at` (nullable) so the embedding worker can resume after a restart.
- Seed script: only the verified numbers from CLAUDE.md, marked `source_type='dictionary'`, `verification_status='unverified'`.

**Run locally:** `make migrate`, then `sqlite3 data/app.db ".tables"` and `".indexes"`.

**Acceptance (tests):**
- Migrations apply to an empty database and are idempotent on a second run.
- Editing an applied migration file makes the runner fail.
- `EXPLAIN QUERY PLAN` for the due-items query, the category filter, the pending queue and the username lookup each shows the intended index (assert on the plan text).
- Foreign keys are enforced; a progress row cannot reference a missing entry.
- A `vec0` insert and nearest-neighbour query works. If the Python build can't load SQLite extensions (common with the macOS system Python), say so and tell me which Python to use.

---

## Stage 2: authentication and roles

**Goal:** login, logout, sessions and an admin command, with no self sign-up.

**Prompt to paste**
> Goal: only people whose accounts the admin created can log in; a lost session can be revoked instantly; a member can never reach an admin route.
> Read CLAUDE.md (Auth and exposure) and docs/IMPLEMENTATION.md Stage 2. Use server-side sessions, not JWTs, and explain in two lines why if you are tempted to deviate.
> Constraints: argon2id with configurable parameters and a small semaphore around hashing; store only the SHA-256 hash of the session token; cookie flags HttpOnly, SameSite=Lax and Secure controlled by config; generic error on a wrong password; throttle per account and per source address; read `CF-Connecting-IP` only for requests that come from localhost; check `Origin` and require a custom header on state-changing requests; no registration endpoint.
> Proof: tests for every constraint above, a 403 for a member on an admin-only test route, a 401 for an anonymous request, logout deleting the session row, and a benchmark script that prints argon2 time here so I can run it again on the Pi.
> Show me the curl commands to log in and call `/api/me`. Plan first, implement, report, stop.

**Build**
- argon2id hashing. Start from 19 MiB memory, 2 iterations, 1 lane, configurable. A semaphore of about 2 around hashing.
- Sessions: 32 random bytes, base64url; store only the SHA-256 hash; idle timeout plus maximum age, both from config.
- Cookie flags per the design: `HttpOnly`, `SameSite=Lax`, `Secure` when `COOKIE_SECURE` is true.
- `POST /api/login`, `POST /api/logout`, `GET /api/me`.
- Login throttle per account and per source address, with growing delays. Read `CF-Connecting-IP` only when the request comes from localhost.
- State-changing requests: check `Origin` and require a custom header.
- `scripts/create_user.py` (and `make create-user`): creates a user with a role; prints a one-time set-password link or prompts for a password in the terminal. No public registration route.
- Dependencies `require_user` and `require_admin`.

**Run locally:** `make create-user` for an admin, then log in with curl (show me the commands) and call `/api/me`.

**Acceptance (tests):**
- Wrong password gives a generic 401; repeated failures are throttled.
- Only the token hash is stored; a cookie with a bad token is rejected.
- A member gets 403 on an admin-only test route; an anonymous request gets 401.
- A request without the custom header or with a foreign `Origin` is rejected.
- Logout deletes the session server-side.
- Benchmark script prints argon2 time on this machine (I'll run it again on the Pi).

---

## Stage 3: entries, moderation and history

**Goal:** the Add Entry and Review screens' backend.

**Prompt to paste**
> Goal: members can add and edit entries, nothing a member adds is visible to others until an admin approves it, and every change can be traced and reversed.
> Read CLAUDE.md (data model, moderation) and docs/IMPLEMENTATION.md Stage 3, and look at docs/prototype/AddEntry.dc.html and Review.dc.html for the behaviour the screens expect, including the "gap" suggestion rule.
> Constraints: members create `pending` entries and admins create `unverified` ones; every edit writes an `entry_history` row with old values, who and when; only admins may change a `native_verified` entry; approve and decline are idempotent; Pydantic limits on every text field; responses are data, never HTML; do not embed anything yet.
> Proof: tests that a member cannot see another member's pending entry, that approving twice is harmless, that a member cannot edit a verified entry, and that history records every edit. Give me a curl walk-through: member adds, admin approves, member edits, history shows it.
> Plan first, implement, report, stop.

**Build**
- `POST /api/entries`: members create entries with `verification_status='pending'`; admins create directly as `unverified`.
- `PATCH /api/entries/{id}`: edit in place; every change writes a row to `entry_history` (old values, who, when). Only admins can change an entry marked `native_verified`.
- `GET /api/entries`: filters `category`, `q` (keyword search), paging. Members see approved entries plus their own pending ones; admins see everything.
- `GET /api/review`, `POST /api/review/{id}/approve`, `POST /api/review/{id}/decline`: admin only, idempotent.
- `GET /api/categories` with counts, and `GET /api/suggestions/gap` returning the category with the fewest entries (same rule as the prototype's Home screen).
- Input limits with Pydantic (length, trimmed, non-empty). Output is always data, never HTML.
- Keep a note in the code that `english` is what gets embedded later; do not embed yet.

**Run locally:** FastAPI's `/docs` page lists the routes; show me a curl walk-through: member adds an entry, admin approves it, member edits, history shows the change.

**Acceptance (tests):** a member cannot see another member's pending entry; approving twice is harmless; editing a verified entry as a member is refused; history records every edit.

---

## Stage 4: the front end (PWA)

**Goal:** the seven prototype screens, working against the real API.

**Prompt to paste**
> Goal: a mobile-first installable app that looks like the prototype and works against the real API, with no build step.
> Read docs/prototype/ (every screen), docs/theme.css, CLAUDE.md (Design system) and docs/IMPLEMENTATION.md Stage 4. Treat the prototype as a visual and behavioural spec: it uses a template format that will not run here, so rebuild the screens as plain HTML, CSS and JavaScript modules.
> Constraints: Kodchasan font, the tokens from docs/theme.css only, hand-drawn stroke SVG icons and no emoji, 44 px touch targets, the five-item bottom nav (no nav on Login, Review only for admins and reached from Settings), user text always escaped and never set with `innerHTML`, the service worker caches the app shell and never `/api`, and no invented statistics: show real counts, zero when empty.
> Proof: every screen works at 390 px and in both themes; offline the shell loads and API screens show a clear message; the app is installable; report the cold-load transfer size in KB. Give me the click path to test: log in, add an entry, filter, edit, approve as admin.
> Plan first, implement one screen at a time while keeping the app runnable, report, stop.

**Build** (use `docs/prototype/` as the visual reference and `docs/theme.css` for tokens)
- Screens: Login, Home, Add Entry, Learn (ladder only, tiers locked as in the prototype), Culture, Settings, Review (admin only).
- A tiny hash router and fetch wrapper that sends the custom header; a 401 sends the user to Login.
- Same rules as the prototype: Kodchasan font, dark default with the light override, stroke SVG icons, 44 px touch targets, five-item bottom nav (Login has none; Review is reached from Settings and only shown to admins).
- Add Entry: form, group and source chips, filter by group, keyword search box (semantic search arrives in Stage 5), edit in place.
- Home: streak and entry count (real numbers, zero if none), suggested topics from the gap endpoint.
- `manifest.webmanifest`, icons, and a service worker that caches the app shell and never caches `/api`.
- Escape all user text; never use `innerHTML` with user data.
- Serve `web/` with FastAPI static files in dev.

**Run locally:** `make run`, open `http://localhost:8000`, log in, add an entry, filter, edit it, approve as admin. Test on your phone through your Mac's LAN address if you like (note that Secure cookies need HTTPS, so use `COOKIE_SECURE=false` for that test only).

**Acceptance:** every screen works at 390 px wide and in both themes; offline, the shell loads and API calls show a clear message; Lighthouse PWA check is installable; report the cold-load transfer size in KB.

---

## Stage 5: keyword and semantic search

**Goal:** FTS5 keyword search and sqlite-vec semantic search over the English meaning, with a background worker.

**Prompt to paste**
> Goal: searching for an English word finds entries by keyword and by meaning, saving an entry stays fast, and the work of computing vectors happens off the request path and survives a restart.
> Read CLAUDE.md (Stack, data model) and docs/IMPLEMENTATION.md Stage 5.
> Constraints: an `Embedder` interface with a deterministic `FakeEmbedder` as the default for dev and CI and a real small CPU model for later; embed only the English field and assert in a test that Kigiriama text never reaches the embedder; one worker started in `lifespan` that reads rows where `embedded_at IS NULL`, uses a bounded queue and never runs on the event loop; set FTS5 diacritic handling explicitly and explain the choice, without folding Kigiriama characters unless I approve; search results obey the visibility rules from Stage 3.
> For the real model: choose one that runs on a Raspberry Pi 4, say why, state its vector dimension and expected memory, keep the file out of git with a download script and checksum, and provide `scripts/bench_embed.py` and `scripts/reindex.py`.
> Proof: tests with the fake embedder for the fast save, the resume after restart, and the visibility rules. Plan first, implement, report, stop.

**Build**
- `Embedder` interface and `FakeEmbedder` (deterministic vectors from a hash, fixed dimension). `EMBEDDER=fake` is the default in dev and CI.
- A real CPU embedder behind the same interface. Choose a small model that runs on a Raspberry Pi 4, say why, state its vector dimension and expected memory, and keep the model file out of git (download script plus checksum).
- A single background worker started in `lifespan`: finds rows where `embedded_at IS NULL`, embeds `english`, writes the vector and sets `embedded_at`. It resumes on restart, uses a bounded queue, and never runs on the event loop.
- Keyword search through FTS5. Set diacritic handling explicitly and explain the choice; do not fold characters in Kigiriama text without my say-so.
- `GET /api/search?q=...&mode=keyword|semantic` ranked results.
- `scripts/reindex.py` rebuilds all vectors; `scripts/bench_embed.py` prints per-embedding latency and peak memory.

**Run locally:** add three entries, wait a moment, search for a related English word and see ranked results; run the reindex.

**Acceptance (tests, using `FakeEmbedder`):** a saved entry returns quickly with `embedded_at` null and gains a vector afterwards; restart mid-queue resumes; Kigiriama text is never passed to the embedder (assert on the call); search results respect visibility rules from Stage 3.

---

## Stage 6: learning engine and reminders

**Goal:** spaced repetition, the daily session and email reminders.

**Prompt to paste**
> Goal: each user gets a daily session of about 20 minutes built from their own due items, their progress is private to them, and reminder emails go out at most once a day.
> Read CLAUDE.md (Teaching model) and docs/IMPLEMENTATION.md Stage 6, and the Learn and Settings prototype screens.
> Constraints: an SM-2 style scheduler writing only to `user_progress`; only tiers 1 and 2 are live and higher tiers stay locked; do not generate grammar rules or Kigiriama forms, so provide the review-file format and an empty example for `noun_classes` and `verb_paradigms` and let me fill it by hand; drills use only rows that exist and skip any item that would need a form we do not have; reminders run as a separate script, never in the web process, with a console backend for local use and SMTP from the environment otherwise, and running it twice in a day sends one email.
> Proof: tests that intervals grow after good grades and reset after a miss, that one user cannot read another's progress, and that reminders are idempotent per day. Show me how to review a few cards and see due dates change.
> Plan first, implement, report, stop.

**Build**
- SM-2 style scheduler updating `user_progress`; `GET /api/learn/session` assembles about 20 minutes of due items plus a few new ones; `POST /api/learn/review` records a grade.
- The Learn screen becomes live for tier 1 and tier 2 only (sounds and core vocabulary built from the user's own entries). Higher tiers stay locked.
- Grammar tables: a script that reads a hand-prepared review file into `noun_classes` and `verb_paradigms`. **Do not generate rules.** Provide the file format and an empty example; I will fill it from Taylor's book. Drills use only rows that exist.
- `scripts/send_reminders.py`: reads `reminders`, sends through SMTP settings from the environment; locally, a console backend prints the email instead. Safe to run twice (idempotent per day).
- Settings screen saves the reminder preference through the API.

**Run locally:** review some cards, see due dates change; `python scripts/send_reminders.py --backend=console` prints the reminder.

**Acceptance (tests):** scheduler intervals grow after good grades and reset after a miss; a user only ever sees their own progress; reminders send at most once a day per user.

---

## Stage 7: hardening and observability

**Goal:** the controls from the security section of the report.

**Prompt to paste**
> Goal: close the gaps an attacker or a mistake would find first, and make the app tell me what happened when something goes wrong.
> Read CLAUDE.md (Auth and exposure), docs/IMPLEMENTATION.md Stage 7, and, if I paste it, the "Security" section of the design report.
> Constraints: security headers and a strict Content-Security-Policy with no inline scripts (say how fonts are served so the CSP stays tight); request and field size limits, Uvicorn timeouts, `--limit-concurrency` and a thread pool capped at 8 to 16; structured logs with a request id and a line for any query over 100 ms; an audit record of logins, failures, approvals and admin actions; `pip-audit` and a secret scan under one `make audit` target; `/healthz` returns no data and an authenticated admin status route shows database size, pending embeddings and last backup time.
> Proof: a test that walks every route and compares its auth requirement with an explicit table in the test, so a new unprotected route fails the build; a manual XSS check where an English meaning containing markup is displayed as text; a failed login appearing in the audit record.
> Plan first, implement, report, stop.

**Build**
- Security headers (`Strict-Transport-Security`, `X-Content-Type-Options`, `Referrer-Policy`) and a strict Content-Security-Policy (no inline scripts; self-hosted font file if the CSP would otherwise need an external origin, and say which you chose).
- Request body and field size limits; Uvicorn timeouts and `--limit-concurrency`; thread pool cap (8 to 16).
- Structured logs with a request id; a log line for any query over 100 ms; an audit table or log for logins, failures, approvals and admin actions.
- `GET /healthz` (no auth, no data) and an authenticated `/api/admin/status` showing database size, pending embeddings and the last backup time.
- `pip-audit` and a secret scan wired into `make lint` or a `make audit` target.
- A test that walks every route and asserts its auth requirement against a table in the test.

**Run locally:** run the app, open the browser dev tools and show the headers; try an XSS string as an English meaning and show it rendered as text.

**Acceptance:** the route-table test passes; the CSP blocks an injected inline script in a manual test; the audit log records a failed login.

---

## Stage 8: Raspberry Pi packaging and deploy scripts

**Goal:** everything the Pi needs, as files in git. Nothing here runs on your Mac except syntax checks.

**Prompt to paste**
> Goal: a deploy that either completes and passes its health check or puts the previous release back, using only files in git, with a backup taken before every change.
> Read CLAUDE.md, docs/IMPLEMENTATION.md Stage 8, and the "CI/CD and infrastructure as code" section of the design report if I paste it.
> Constraints: Uvicorn on a Unix socket under a dedicated user with `MemoryMax` and systemd hardening options; Nginx on `127.0.0.1:8080` trusting `CF-Connecting-IP` only from `127.0.0.1`, with a login rate limit, body cap, security headers, static files with cache headers and a maintenance page for 502; timers for reminders, backup and `PRAGMA optimize` plus an `OnFailure=` unit that emails me; `deploy.sh` unpacks to a release folder, builds a virtual environment from the hash-pinned lock file, backs up, migrates, switches the `current` symlink atomically, restarts, health-checks, and calls `rollback.sh` on failure, keeping five releases; document at the top of the script that migrations must be backward compatible so rollback never needs a database restore.
> Proof: a `--dry-run` mode that prints each step without acting, a script test that exercises `rollback.sh` against a temporary directory tree, `shellcheck` clean, and a list of the checks I must run on the Pi because they only exist there. Write docs/PI_SETUP.md as one ordered list of my manual steps.
> Plan first, implement, report, stop.

**Build** (under `deploy/`)
- `systemd/jifunze.service`: Uvicorn on a Unix socket, dedicated user, `MemoryMax`, restart on failure, hardening options such as `NoNewPrivileges` and `ProtectSystem`, environment file path.
- `systemd/jifunze-reminders.service` and `.timer`; `jifunze-backup.service` and `.timer`; `jifunze-optimize.service` and `.timer`; an `OnFailure=` unit that emails you.
- `nginx/jifunze.conf`: listens on `127.0.0.1:8080`; trusts `CF-Connecting-IP` from `127.0.0.1`; `limit_req` on `/api/login`; body size cap; security headers; static files from `current/web` with cache headers; a maintenance page on 502.
- `backup.sh`: `sqlite3 .backup` to a dated file, integrity check, prune old files, optional off-device copy command via a configured remote.
- `deploy.sh <release-tag>`: unpack to `releases/<tag>`, create a virtual environment from `requirements.lock` with hash checking, **take a backup**, run migrations, switch the `current` symlink atomically, restart the service, call the health check, and on failure run `rollback.sh` (point the symlink back, restart). Keep the last five releases.
- Rule to document in the file header: migrations must be backward compatible (add first, remove in a later release) so code rollback never needs a database restore.
- `healthcheck.sh`: calls `/healthz` through the socket, then `vcgencmd get_throttled` and temperature if present.
- `docs/PI_SETUP.md`: one numbered list of manual steps for the Pi, in order (OS image settings, SSD mount, packages, service user, directories, enabling units).

**Check locally:** `shellcheck` on scripts, `nginx -t` using a throwaway container or local install if available, `systemd-analyze verify` is Linux-only, so say which checks I should run on the Pi.

**Acceptance:** a dry-run mode of `deploy.sh` that prints each step without doing it; `rollback.sh` tested against a temporary directory structure in a script test.

---

## Stage 9: GitHub Actions

**Goal:** tests on every pull request, a release on a tag, a gated deploy to the Pi.

**Prompt to paste**
> Goal: nothing reaches the Pi unless tests pass and I approve it, and a failed deploy leaves the previous version running.
> Read docs/IMPLEMENTATION.md Stage 9 and the deploy scripts from Stage 8.
> Constraints: three workflows. `ci.yml` on pull requests and pushes to main on hosted runners (cached install, `ruff`, `pytest` with `EMBEDDER=fake`, migration tests, `pip-audit`, secret scan, front-end size budget, plus an ARM64 job only if you can confirm an ARM64 hosted runner is available to me, and say what you assumed). `release.yml` on tags `v*` builds one tarball of app, web, migrations, deploy and lock file, with a checksum, as release assets. `deploy.yml` runs on a self-hosted ARM64 runner, uses `environment: production`, has a `concurrency` group, downloads the asset, verifies the checksum, runs `deploy/deploy.sh`. Every workflow sets `permissions: contents: read` by default, pins every third-party action to a full commit SHA that you have looked up rather than guessed (list them so I can verify), never echoes secrets, and cannot run the deploy job from a fork.
> Also write docs/RUNNER_SETUP.md: installing the runner under its own unprivileged user, limiting its sudo to restarting the one service, labels, and removal.
> Proof: valid YAML, `make lint test` reproduces CI locally, and a short explanation of how I confirm each protection in the GitHub settings.
> Plan first, implement, report, stop.

**Build** (under `.github/workflows/`)
- `ci.yml` on pull request and push to `main`, hosted runner: install with caching, `ruff`, `pytest` (with `EMBEDDER=fake`), migration tests, `pip-audit`, secret scan, front-end size budget. An optional ARM64 job if an ARM64 hosted runner is available to me; say what you assumed.
- `release.yml` on tags `v*`: build one tarball (app, `web/`, `migrations/`, `deploy/`, `requirements.lock`), upload it as a release asset with its checksum.
- `deploy.yml` on release published or manual dispatch: `runs-on: [self-hosted, linux, ARM64]`, `environment: production` (I'll configure required reviewers), a `concurrency` group so two deploys never overlap, downloads the release asset, verifies the checksum, runs `deploy/deploy.sh`.
- Security: `permissions: contents: read` by default; pin every third-party action to a full commit SHA (look each one up, don't guess, and list them so I can check); no secrets echoed; fork pull requests cannot reach the deploy job.
- `docs/RUNNER_SETUP.md`: installing the runner on the Pi under its own unprivileged user, limiting its `sudo` to restarting the one service, labels, and how to remove it.

**Check locally:** `act` is optional; at least validate YAML and show me how to dry-run CI steps with `make lint test`.

**Acceptance:** opening a pull request runs CI; the deploy job cannot start without approval; a failed health check fails the workflow and leaves the previous release running.

---

## Stage 10: Cloudflare Tunnel, Access and infrastructure as code

**Goal:** reproducible machine setup and the public hostname, with a restore drill.

**Prompt to paste**
> Goal: the Pi can be rebuilt from git in one sitting, the app is reachable only through Cloudflare Access, and I have proved I can restore the dictionary from a backup.
> Read CLAUDE.md, docs/IMPLEMENTATION.md Stage 10 and the earlier deploy files.
> Constraints: `cloudflared` ingress to `http://127.0.0.1:8080` with a 404 catch-all; an idempotent Ansible playbook for packages, service user, SSD mount by UUID with `noatime`, a default-deny firewall, key-only SSH, unattended security updates, journald limits, Nginx, the Stage 8 units and `cloudflared`; secrets with `sops` and `age` with the key handling documented and no key ever committed; an `ansible-pull` option; optional Terraform for the tunnel, DNS record and Access policy; optional middleware that verifies `Cf-Access-Jwt-Assertion` (signature and audience) behind an environment variable, tested with a locally generated key pair. Do not run anything against my Pi; write files and instructions.
> Also write docs/CLOUDFLARE_SETUP.md (the interactive steps I must do), docs/RESTORE_DRILL.md with a script that restores the latest backup into a clean directory and checks integrity and row counts, and docs/GO_LIVE.md as a checklist: tests green, backup restored once, Access policy tried from a non-allowed email, admin created, no default passwords, runner limited, alerts verified.
> Proof: `ansible-playbook --check` instructions, the JWT tests, and a restore drill I can run on my Mac against a sample backup.
> Plan first, implement, report, stop.

**Build**
- `deploy/cloudflared/config.yml.j2` with ingress to `http://127.0.0.1:8080` and a 404 catch-all.
- `infra/ansible/`: playbook and roles for packages, service user, directories, SSD mount by UUID with `noatime`, firewall (deny inbound by default), key-only SSH, unattended security updates, journald size limits, Nginx, the systemd units from Stage 8, `cloudflared`, and the runner prerequisites. Idempotent; secrets from `sops` with `age` (document key handling, never commit keys). Include an `ansible-pull` option.
- `docs/CLOUDFLARE_SETUP.md`: the manual, interactive steps I must do (`cloudflared tunnel login`, create the tunnel, route DNS, create the Access application with an email allow-list, copy credentials into the encrypted secrets file).
- Optional `infra/terraform/` describing the tunnel, DNS record and Access policy.
- Add Cloudflare Access JWT verification (`Cf-Access-Jwt-Assertion`, signature and audience) as an optional middleware controlled by an environment variable, with tests using a locally generated key pair.
- `docs/RESTORE_DRILL.md`: restore the latest backup onto a clean machine or directory and run the app against it; add a script that verifies row counts and an integrity check.
- A final checklist in `docs/GO_LIVE.md`: tests green, backup restored once, Access policy tested from a non-allowed email, admin account created, default passwords none, runner limited, logs and alerts verified.

**Acceptance:** `ansible-playbook --check` against the Pi completes without errors; I can reach the app at the hostname only after passing Access; a deliberate failed deploy rolls back; the restore drill succeeds.

---

## What stays manual (Claude can't do these for you)

- Creating the Cloudflare account steps that open a browser, and choosing the domain.
- Flashing the OS, mounting the SSD and the first SSH login on the Pi.
- Registering the self-hosted runner (the token comes from GitHub's settings page).
- Writing the grammar review file from Taylor's dictionary by hand.
- Adding GitHub environment protection rules and branch protection.
