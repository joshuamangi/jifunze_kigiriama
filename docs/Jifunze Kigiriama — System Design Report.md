# Jifunze Kigiriama — System Design Report

Oct 6, 2026 · @Polymathian

## The story in one page

Every choice in this design is the cheapest option that still satisfies five constraints; where a choice looks modest, a constraint made it so. The numbers below are design targets to be measured on the Pi, not benchmarks.

| Constraint | What it forces |
| --- | --- |
| Raspberry Pi 4, 4 GB RAM shared with the OS, tunnel and an embedding model | One app process, SQLite instead of a database server, no Redis or message broker |
| Reachable from the public internet through Cloudflare Tunnel | Real authentication, rate limiting and server-side permission checks; the tunnel hides ports, not bad requests |
| A small trusted group, tens of users, a few concurrent requests at most | No load balancer, no horizontal scaling; spend effort on correctness, backups and recovery instead |
| One builder who is learning while building | Boring, well-documented tools, few moving parts, a one-command deploy |
| A language no model can generate reliably | Human-entered data is the only source of truth, so moderation, edit history and backups matter more than throughput |

The chain of reasoning, in order:

1. **Low traffic and little RAM** lead to a single FastAPI process with SQLite in WAL mode. This removes a database server (roughly 100–300 MB of RAM, plus its own failure modes) and keeps backup to one file.
2. **SQLite allows one writer at a time**, so writes are kept short and the slow work (embedding an entry) moves to a background worker. A save returns in milliseconds while the vector is computed afterwards.
3. **Public exposure** leads to server-side sessions rather than JWTs, a hardened login, and Cloudflare Access in front as a second gate. Revocation, which matters for a small group where one lost phone must mean one instant logout, is the deciding factor.
4. **A public hostname with no open ports** leads to the tunnel terminating TLS at Cloudflare. Nginx stays optional: it earns its place only when it serves static files or adds rate limits you would rather not write in Python.
5. **Solo operation** leads to GitHub Actions running the tests and a pull-based deploy to the Pi, plus infrastructure as code (Ansible and systemd units in git) so a dead SD card or SSD is a 30-minute rebuild instead of a lost weekend.

The rest of this report takes each decision, says what causes it, what it costs, and how much it matters (high, medium or low impact).

## Architecture

A request passes the Cloudflare Access gate, the tunnel, an Nginx buffer and the app's own login before it can touch the database, and background work never shares the request path.

&#91;embedded content: request path · phone to SQLite, 8 components\]

Read the picture left to right and top to bottom. The highlighted box is the asset every layer exists to protect. The embedding worker and the timers sit beside the request path, not on it, which is why a slow embedding or a slow mail server cannot slow a user's tap.

## Database indexing

Indexes are chosen from the queries the prototype's screens actually make, because an index you cannot tie to a query is write cost with no read benefit. At the expected size (low thousands of entries, tens of users) most queries would be fast even unindexed; the indexes below matter for the two tables that grow without bound, `user_progress` and `sessions`, and for keeping the hot path predictable as the corpus grows.

**Cause and effect, in four steps.**

1. The Learn screen asks "what is due for this user today?" on every session start. That is the hottest query in the system, so `user_progress` gets a composite index on `(user_id, due_date)`. Without it, the query scans every user's progress rows; with it, it reads only the user's own due rows, in order.
2. Reviewing a card is an upsert on `(user_id, entry_id)`. That pair is therefore the primary key, which also guarantees one progress row per user per entry. The cost is that the key is wider than a surrogate id, which is irrelevant at this scale.
3. The admin queue shows pending entries only. A **partial index** on `entries(created_at) WHERE verification_status = 'pending'` stays tiny (it holds only what is waiting) and makes the admin screen cost the same whether the dictionary has 200 entries or 20,000.
4. SQLite does not index foreign-key columns automatically. `entry_history(entry_id, changed_at)` and `sessions(user_id)` are indexed explicitly; otherwise deleting an entry or logging a user out everywhere scans the child table.

**Search comes in three kinds, each with its own structure.**

- **Filter by group** uses `entries(category, created_at DESC)`. This serves the group chips on Add Entry and, because the leading column is `category`, the per-category counts that drive the "today's gap" suggestion.
- **Keyword search** over both languages uses an FTS5 virtual table. A `LIKE '%word%'` cannot use any index and would scan every row. Set the tokenizer's diacritic handling explicitly: folding accents is a linguistic decision, and for Kigiriama it must be a human's choice, not a default.
- **Semantic search** over the English meaning uses sqlite-vec's `vec0` table with brute-force nearest-neighbour search. If the embedding has 384 dimensions (typical of small MiniLM-class models), 2,000 entries take 2,000 × 384 × 4 bytes, about 3 MB. A full scan of that is cheap, so approximate-index tuning is deliberately skipped until the corpus is orders of magnitude bigger.

**Settings that decide behaviour more than any index.**

| Setting | Why it is set | What it costs |
| --- | --- | --- |
| `journal_mode = WAL` | Readers stop blocking the single writer, so a review submit does not freeze someone browsing | Two extra files next to the database; backups must use `.backup`, not a plain file copy |
| `synchronous = NORMAL` | Fewer fsyncs, so fewer writes to the SSD and faster commits | On sudden power loss the last few commits can be lost (never corrupted); the nightly backup covers that |
| `busy_timeout = 5000` | A second writer waits instead of failing immediately | A stuck writer shows up as latency rather than an error, so log slow queries |
| `foreign_keys = ON` | SQLite ignores foreign keys unless asked; this stops orphaned progress rows | Negligible |

**Impact, weighted.**

| Index or structure | Serves | Write cost | Impact |
| --- | --- | --- | --- |
| `user_progress (user_id, due_date)` | Daily session assembly | Low (one row per review) | High: removes the only query that grows with users × entries |
| `users (username)` unique, case-insensitive | Login | Negligible | High: correctness, not speed; stops duplicate accounts |
| `sessions (token_hash)` primary key, `(expires_at)` | Session lookup and cleanup | Low | High: every request pays this lookup |
| `entries (category, created_at DESC)` | Group filter, gap counts | Low | Medium |
| Partial index on pending entries | Admin queue | Near zero | Medium: keeps admin cost flat |
| FTS5 over english and giriama | Keyword search | Medium (a second copy of the text) | Medium: the Add Entry search box |
| `vec0` for English embeddings | Semantic search | Medium (one embedding per save, off the request path) | Medium: the feature that justifies sqlite-vec |

Two habits keep this honest. Run `EXPLAIN QUERY PLAN` on each hot query and keep the output in the tests, so a refactor that silently drops an index fails a test. Run `PRAGMA optimize` on a schedule so SQLite's statistics stay current.

## Authentication: server-side sessions, not JWTs

The app uses opaque server-side sessions in a cookie, because the one thing JWTs are good at, letting many services verify a user without sharing a store, is a problem this system does not have. Everything lives in one process and one SQLite file, so checking a session is a single primary-key lookup, and the stateless benefit buys nothing.

**Why JWTs would cost more than they give here.**

1. A JWT is valid until it expires. For a small group the realistic emergency is one lost phone, and the right response is "log that person out now". With JWTs that needs a denylist, which is a session table by another name.
2. Short-lived access tokens fix revocation but add refresh-token rotation, reuse detection and a second token to store. That is a lot of security-critical code for a solo builder, and each piece is a place to make a mistake.
3. Where the token is kept matters. In `localStorage` any injected script can read it; in a cookie you are back to cookie-based auth, so you have taken on JWT complexity and kept cookie risks.

**What is built instead, and what each part prevents.**

| Part | Detail | What it prevents |
| --- | --- | --- |
| Session token | 32 random bytes, base64url. Only its SHA-256 hash is stored in `sessions` | A leaked database does not leak usable sessions |
| Cookie flags | `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/` | Script theft of the token, plain-HTTP leakage, most cross-site request forgery |
| Expiry | Sliding idle timeout plus a hard maximum age; both stored server-side | A forgotten logged-in phone stays valid forever |
| State-changing requests | Check the `Origin` header and require a custom header on `POST`, `PUT`, `DELETE` | Forgery that `SameSite` alone does not stop |
| Passwords | argon2id, memory-hard, parameters tuned on the Pi (start at OWASP's minimum of 19 MiB, 2 iterations, 1 lane) and benchmarked | Offline cracking if the database file leaks |
| Hash concurrency | A small semaphore (about 2) around hashing | Several simultaneous logins spiking RAM on a 4 GB board |
| Login throttling | Per account and per source address, with growing delays | Password guessing |
| Accounts | Created by the admin via a command; a one-time, hashed, expiring link sets the first password | Open registration and its abuse |
| Roles | `admin` or `member` on the user row, enforced by a FastAPI dependency on every admin route | A member calling admin endpoints directly, whatever the UI hides |

The source address behind a tunnel is the tunnel's, so the app reads Cloudflare's client-address header and trusts it only when the request arrives from localhost. If it trusted that header from anywhere, an attacker could forge it and defeat the throttle.

**Where a JWT does appear.** If Cloudflare Access sits in front of the hostname, Cloudflare attaches a signed token (`Cf-Access-Jwt-Assertion`) to each request. The app should verify its signature against Cloudflare's published keys and check the audience claim. The origin is only reachable through the tunnel, so this is defence in depth rather than a requirement, but it is cheap and it means a mistake in the tunnel configuration cannot silently open the app.

**Impact.**

| Decision | Impact | Why it carries that weight |
| --- | --- | --- |
| Sessions over JWT | High | Instant revocation and far less security code to get wrong |
| Hash tokens at rest | Medium | Turns a database leak from account takeover into an annoyance |
| argon2id tuned on the Pi | Medium | Wrong parameters either weaken hashes or let a handful of logins exhaust memory |
| Cloudflare Access in front | High | A second, independent gate before the login page is even reachable |
| Server-side admin checks | High | The review queue is the integrity gate for the whole dictionary |

## Proxy, load balancing and gateway

The design uses Cloudflare as the edge, a thin local Nginx as the front door to the app, and deliberately no load balancer and no API gateway. Each of those three answers follows from how little traffic and how few services there are.

**Cloudflare Tunnel is already your reverse proxy.** `cloudflared` makes an outbound connection from the Pi to Cloudflare, so no router port is opened and the home IP is never published. Cloudflare terminates TLS, absorbs junk traffic and can enforce Access rules before a request reaches the Pi. The trade-off is that Cloudflare sees traffic in clear text after TLS ends; for study notes and email addresses in a trusted group that is an acceptable, but conscious, choice. A second trade-off is dependency: a Cloudflare outage takes the public URL down, though you can still reach the app on your home network.

**Why add Nginx at all.** The tunnel could point straight at Uvicorn, and for the first build it can. Nginx earns its small cost (a few megabytes of RAM, one more config file) with four jobs that are awkward to do well in Python:

1. **Slow clients.** Mobile connections are slow and flaky. Nginx buffers the whole request and the whole response, so a slow phone ties up Nginx, not a Uvicorn connection.
2. **Limits before Python runs.** Request body cap, header timeouts and `limit_req` zones on `/login` stop abusive traffic before it uses CPU in the app. Pairing this with the app's own throttle means a bug in one layer does not remove the protection.
3. **Static files.** The PWA shell is served with `sendfile` and long cache headers, so most taps on the Pi never touch Python.
4. **A graceful failure.** While the app restarts during a deploy, Nginx serves a small maintenance page instead of the raw 502 from the tunnel.

The path is: tunnel to `127.0.0.1:8080` (Nginx), then a Unix socket to Uvicorn. A socket means the app has no network port that anything else on the Pi, or the home network, can reach. Nginx's real-IP module is told to trust `CF-Connecting-IP` only from `127.0.0.1`, which is where `cloudflared` connects from.

**Why no load balancing.** A second app instance would share one SQLite file and fight for its single writer. A second Pi would need database replication, a real operational burden. In exchange you would remove a one-minute outage during deploys, which a small learning group will not notice. The scaling path, in order of cost, is: more Uvicorn workers (but then run the embedding model in one dedicated worker, not once per worker), a separate embedding process, and only then a move to PostgreSQL.

**Why no API gateway.** A gateway earns its place when it routes between several services and centralises their auth, rate limits and versioning. Here there is one service, and those jobs are already done: Cloudflare Access for identity, Nginx for limits, FastAPI dependencies for permissions. A gateway would add a layer that has nothing to route.

| Layer | Job | Why it lives there | Impact |
| --- | --- | --- | --- |
| Cloudflare edge and Access | TLS, DDoS absorption, email allow-list | Stops strangers before they reach your hardware | High |
| Tunnel (`cloudflared`) | Outbound-only link, no open ports | Removes the whole class of router and firewall mistakes | High |
| Nginx | Buffering, limits, static files, maintenance page | Protects the single app worker from slow or abusive clients | Medium |
| Unix socket to Uvicorn | App unreachable from the network | Shrinks the attack surface at no cost | Medium |
| Load balancer | Skipped | One SQLite writer makes a second instance counter-productive | Low |
| API gateway | Skipped | One service means nothing to route | Low |

## FastAPI and asynchronous work

Async in this app is not about speed; it is about making sure one slow operation never freezes everyone else. FastAPI runs `async def` handlers directly on one event loop, so a single blocking call inside one stalls every request until it returns. With one worker process on a small board, that is the failure mode to design against.

**Cause and effect, by operation.**

1. **SQLite calls are blocking.** The standard `sqlite3` module has no async mode, and making queries "async" does not make them faster; it only moves them off the loop. Two safe patterns exist: plain `def` handlers, which FastAPI runs in a thread pool, or `aiosqlite` inside `async def`. Either is fine. What is not fine is calling `sqlite3` directly in an `async def` handler. The recommended shape is a small pool of read connections (WAL lets readers run in parallel) and one write connection guarded by a lock, so writers queue politely instead of failing with "database is locked".
2. **The default thread pool is too generous.** It allows about 40 threads, each with its own stack and potentially its own connection. Cap it at roughly 8–16 so a burst cannot exhaust memory on a 4 GB board.
3. **Embedding is CPU-bound.** Computing a vector takes real CPU time, and a model that holds the Python GIL while it runs would freeze the loop. So an entry is saved first with `embedded_at = NULL`, the request returns, and a single dedicated worker (a one-thread executor, or a separate process if the library does not release the GIL) fills in the vector afterwards. The user sees their entry immediately; semantic search catches up within moments.
4. **Jobs must survive a restart.** An in-memory queue loses pending work when systemd restarts the app during a deploy. Because the "needs embedding" state is a column in the table, the worker simply asks for rows where `embedded_at IS NULL` on startup and carries on. No broker is needed.
5. **The model loads once.** A `lifespan` handler opens the database and loads the embedding model at startup and closes both at shutdown. Loading per request would cost seconds and hundreds of megabytes each time.
6. **Email never sends from the web process.** Reminders run as a systemd timer that calls a separate command. A slow mail server then cannot hold a request thread, and a web crash cannot drop a reminder.

**Settings that make it behave.**

| Choice | Reason | Impact |
| --- | --- | --- |
| One Uvicorn worker | Two workers would each load the model and contend for SQLite's single writer | High |
| Cap on thread pool and on concurrent hashing | Bounds memory so a burst slows things down instead of crashing them | High |
| Embedding off the request path, state in the row | Keeps saves fast and survives restarts without extra infrastructure | High |
| Pydantic length limits on every text field | Stops a huge payload tying up memory and the writer | Medium |
| Request timeouts and `--limit-concurrency` | A stuck client cannot hold the app indefinitely | Medium |
| `uvicorn[standard]` (uvloop, httptools) | Modest speedup on ARM64 where wheels exist; not required | Low |
| Idempotent approve and decline | A double tap on a flaky connection cannot corrupt the queue | Medium |

Two things to measure rather than assume: peak memory during a reindex of a few thousand entries, and the 95th-percentile latency of a save while the embedding worker is busy. If a save slows noticeably while it is, the worker needs lower priority or its own process.

## Security

The biggest risks are an exposed login, a stolen admin session and a damaged dictionary, so controls are layered so that no single mistake opens the system, and they are ranked by how much harm they prevent. The assets worth protecting are, in order: the integrity of the entries (a wrong Kigiriama word taught as fact does lasting harm), the admin account, members' email addresses, and the Pi itself.

**Who might attack, and how.**

| Threat | How it happens | Primary defence | Backup defence |
| --- | --- | --- | --- |
| Password guessing | Bots hit the public login page | Cloudflare Access allow-list | Throttling in Nginx and in the app, argon2id |
| Stolen or leaked session | Lost phone, shared device | Server-side revocation, short idle timeout | Admin can end all sessions for a user |
| Member escalates to admin | Calls admin endpoints directly | Role check on every admin route, in code | Tests that prove a member gets 403 |
| Script injection | Someone enters markup as an "English meaning" | Output escaping by default, strict Content-Security-Policy | `HttpOnly` cookies so scripts cannot read the session |
| SQL injection | Crafted search text | Parameterised queries only, never string-built SQL | Database user has no file or shell access |
| Bad data enters the dictionary | An honest mistake or a malicious entry | Moderation: members' entries start as `pending` | Edit history makes any change reversible |
| Pi compromised | Unpatched OS, exposed SSH | No inbound ports, key-only SSH, unattended security updates | Backups kept off the Pi |
| Lost or corrupted data | SSD failure, bad deploy, human error | Nightly `sqlite3 .backup` copied off-device | A restore that has actually been tested |

**Controls in the order they should be built.**

1. **Network posture.** The only way in is the tunnel. The firewall denies inbound traffic by default, SSH accepts keys only and is reachable from the LAN or via the tunnel's private access rather than the open internet, and the app listens on a Unix socket. This removes the largest class of attacks (port scans, exposed services) at almost no cost.
2. **Identity gates.** Cloudflare Access first, the app's own login second. Two independent gates mean a flaw in one does not expose the app.
3. **Authorisation in code.** Every route declares the role it needs through a dependency, and a test asserts that each admin route rejects a member. Hiding a button is not security.
4. **Input and output handling.** Pydantic validates type and length at the boundary; templates and the front end escape output by default; user text never enters `innerHTML`; a Content-Security-Policy forbids inline scripts and third-party script origins. Kigiriama and English text should be treated as untrusted strings like any other.
5. **Secrets.** Kept in an environment file readable only by the service user, never in git. A pre-commit secret scanner and GitHub's secret scanning catch accidents. Tunnel credentials and the SMTP password are the two to guard.
6. **Headers and cookies.** `Strict-Transport-Security`, `X-Content-Type-Options`, a restrictive `Referrer-Policy`, and cookie flags as set out in the authentication section.
7. **Supply chain.** Pin dependencies with hashes, run `pip-audit` and Dependabot, and keep the dependency list short; each package on a Pi is something you must keep patched.
8. **Audit and recovery.** Log logins, failures, approvals and admin actions with who and when. Test a restore from backup on a different machine at least once; an untested backup is a hope, not a control.

**One content-integrity point that is specific to this project.** The sources are the only authority for Kigiriama text. The admin review screen should show the source type next to every pending entry, and entries marked `native_verified` should be changeable only by an admin, so a casual edit cannot silently downgrade verified content.

**Impact ranking.**

| Control | Harm it prevents | Effort | Impact |
| --- | --- | --- | --- |
| No inbound ports, tunnel only | Direct attacks on the Pi | Low | High |
| Cloudflare Access in front | Anonymous reach of the login page | Low | High |
| Server-side authorisation tests | Silent admin takeover | Medium | High |
| Moderation plus edit history | Wrong or malicious dictionary data | Medium | High |
| Tested off-device backups | Permanent data loss | Low | High |
| Strict CSP and output escaping | Stored script injection | Medium | Medium |
| Dependency auditing | Known-vulnerability exploits | Low | Medium |
| Audit log | Slow detection, no answer to "what happened" | Low | Medium |

## CI/CD and infrastructure as code

The pipeline exists so that deploying is boring and undoing a deploy takes seconds, and the infrastructure code exists so that the Pi can die tonight and be rebuilt tomorrow. Both matter more for a solo builder than for a team, because there is nobody else who remembers how the Pi was set up.

### The pipeline, stage by stage

1. **On every pull request, on GitHub's own runners.** Lint and format check (`ruff`), tests with `pytest` against a throwaway SQLite file, a migration test (apply all migrations to an empty database, then to a copy of the previous schema), assertions on `EXPLAIN QUERY PLAN` for the hot queries, `pip-audit` for vulnerable dependencies, a secret scan, and a size budget for the front-end bundle. Cause: a bad change is cheapest to catch before it reaches the Pi, and the Pi is too small to be a build machine.
2. **An ARM64 check.** Several dependencies (sqlite-vec, the embedding runtime, argon2) ship native code. A package that installs on your Mac can fail on the Pi. Run the install and a smoke test on an ARM64 runner (GitHub offers ARM64 hosted runners; confirm current availability and pricing for private repositories) or let the first deploy step on the Pi do it.
3. **On a version tag, build one release artifact.** Application code, front-end files and a hash-pinned requirements list, packaged once. Cause: you deploy exactly the thing you tested, not a fresh build that might differ.
4. **Deploy, behind a manual approval.** A GitHub Environment named `production` requires your approval and holds the deploy secrets, so a stray merge cannot reach the Pi.
5. **On the Pi: take a pre-deploy database backup, unpack to a new release folder, run migrations, switch a `current` symlink, restart the service, then call the health endpoint.** The symlink switch is atomic, so there is no half-deployed state; downtime is the length of one restart.
6. **If the health check fails, point the symlink back and restart.** This gives a rollback in seconds, with no rebuild. It is only safe if migrations are backward compatible (add columns first, remove them in a later release), which is why that is a rule and not a preference.

### How the code gets onto the Pi

The Pi sits behind home internet with no open ports, so something must reach in or the Pi must reach out. Three workable options, with the trade-offs:

| Option | How it works | Strength | Weakness | Verdict |
| --- | --- | --- | --- | --- |
| Self-hosted runner on the Pi | A GitHub runner on the Pi connects outward and runs only the deploy job | Immediate feedback in the Actions page; no inbound access | Workflow code runs on your hardware, so a compromised repository means a compromised Pi | Recommended for a private repository you alone control, with the controls below |
| SSH through the tunnel | A hosted runner connects over Cloudflare's private access using a service token | Nothing runs on the Pi except SSH | More secrets and moving parts to set up | Good if you dislike a runner on the Pi |
| Pull-based deploy | A systemd timer on the Pi checks for a new tagged release and installs it | Smallest attack surface; nothing in GitHub can touch the Pi | Slower feedback (minutes), the Pi must be able to read releases | Best security, worth it if the group grows |

Controls if you use the self-hosted runner: keep the repository private, disable workflows from forks, run the deploy job only on tags and only after environment approval, give the runner its own unprivileged user whose sudo is limited to restarting the one service, pin third-party actions to commit hashes, and set `permissions: contents: read` by default. Run tests and builds on hosted runners; the Pi only deploys.

### Infrastructure as code on the Pi

Keep the whole machine description in git so rebuilding is a command, not a memory. This is possible and worthwhile on a Pi; the question is only how much to automate.

| Layer | Tool | What it declares | Impact |
| --- | --- | --- | --- |
| OS and packages | Ansible, run from your Mac over SSH | Packages, users, directories, SSD mount by UUID with `noatime`, firewall, SSH hardening, unattended security updates, journald size limits | High: a fresh SD card or SSD becomes a 30-minute rebuild |
| Application services | systemd units in git, installed by Ansible | The app service with a `MemoryMax` ceiling, the reminder timer, the nightly backup timer, a periodic `PRAGMA optimize`, and `OnFailure=` units that email you | High: restarts, limits and alerts become declared behaviour |
| Proxy and tunnel | Templated Nginx config and `cloudflared` config in git | Routes, limits, headers, the tunnel's ingress rules | Medium |
| Secrets | `sops` with `age`, or Ansible Vault | Tunnel credentials, SMTP password, session secret, stored encrypted in the repository | High: secrets are reproducible without being exposed |
| Edge configuration | Terraform with the Cloudflare provider (optional) | The tunnel, the DNS record and the Access allow-list policy | Medium: worth it if you want the allow-list reviewed in a pull request |
| Backups | `sqlite3 .backup` plus an off-device copy; Litestream as an upgrade | A restore point you can reach even if the Pi is gone | High: the only protection against losing the dictionary |

A useful variant is `ansible-pull`: the Pi fetches the playbook from git on a timer and applies it itself, which gives the pull-based security property for configuration as well as code.

**Why native systemd and not Docker.** A container adds a layer to debug and some memory overhead on a 4 GB board, in return for identical dev and production environments. With one service and a Python virtual environment, systemd gives restarts, limits and logs directly. Containers become attractive if you later add more services or need a development environment that matches production exactly. Either way, confirm that every dependency has an ARM64 build.

**Pi-specific hazards that the code should declare or monitor.** A weak power supply causes undervoltage and can corrupt storage, so check `vcgencmd get_throttled` in a health script. Heat causes throttling under embedding load, so log temperature. Cap journald so logs do not fill the disk. Prefer the USB SSD for the database and for logs.

### Impact of the whole pipeline

| Capability | Without it | With it | Impact |
| --- | --- | --- | --- |
| Tests and migration checks before deploy | A broken migration found in production | Found on a pull request | High |
| Atomic release folders with health-check rollback | Manual repair after a bad deploy | Back to the previous version in seconds | High |
| Pre-deploy backup | A bad migration can destroy data | A restore point exists before every change | High |
| Ansible and systemd in git | A dead SD card means a lost weekend | A scripted rebuild | High |
| Approval gate on `production` | Any merge can deploy | One deliberate click | Medium |
| Dependency and secret scanning | Silent vulnerable or leaked credentials | Reported on every change | Medium |

## Build order, measurements and open decisions

Build in the order that removes the most risk first: protect the data and the door before adding features, because those are the things that cannot be repaired afterwards.

1. **Schema, migrations and backups.** Data loss is the one unrecoverable failure, so the migration runner, the WAL settings and a tested restore come before any screen.
2. **Auth, roles and the review queue**, with the tests that prove a member cannot reach admin routes. Moderation is what keeps the dictionary trustworthy.
3. **Tunnel plus Cloudflare Access plus Nginx.** Expose the app only after steps 1 and 2 exist.
4. **The CI pipeline and the first deploy with rollback.** Every later change then ships the same safe way.
5. **Features that use the database:** entries, filtering, keyword search, then the embedding worker and semantic search.
6. **Drills, spaced repetition and reminders**, followed by the Ansible description of the machine, once the shape of the services has settled.

**Measure on the Pi, do not assume.** Peak memory while reindexing a few thousand entries; save latency while the embedding worker runs; argon2 time per login with the chosen parameters; cold-load size of the PWA; temperature and throttling under embedding load; time to restore from backup on a second machine. Each of these either confirms a choice above or tells you which one to revisit.

**Open decisions, with the default this report assumed.**

| Decision | Default assumed | Changes if |
| --- | --- | --- |
| Front end | Plain JavaScript with small modules | You prefer Svelte, which adds a build step on your Mac |
| Deployment route | Self-hosted runner on the Pi, deploy only | You want the smallest attack surface, so choose the pull-based deploy |
| Nginx | Included from the start | You want the first release minimal, so add it with the first static-file or rate-limit need |
| Cloudflare Access | In front of the hostname | You have no Cloudflare-managed domain, which also rules out a named tunnel |
| Embedding model | Small, on-device, loaded once | Memory measurements show it is too heavy; then compute vectors on demand or move them to a batch job |
| Backups | Nightly `.backup` copied off-device | You want near-zero data loss, so add Litestream |
