# Jifunze Kigiriama

A self-hosted, mobile-first web app (PWA) for learning Kigiriama (Giriama, ISO 639-3 `nyf`), a
Mijikenda language of the Kilifi/Malindi coast, Kenya. You build the word list entry by entry, and
the app turns it into spaced-repetition practice. It runs on a Raspberry Pi and is shared with a
small trusted group.

**Kigiriama content comes only from entries you type or from the verified sources in
[CLAUDE.md](CLAUDE.md). Nothing is generated or translated by a model.**

Stack: Python 3.11, FastAPI, SQLite with `sqlite-vec`, plain HTML/CSS/JS. Search embeddings use the
English side only (all-MiniLM-L6-v2 via ONNX Runtime).

## Where to read what

| File | What it is |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Project rules, data model, teaching model, auth and design rules. Read first. |
| [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md) | The staged build guide (stages 0 to 10). Wins over `docs/BUILD_PLAN.md`. |
| [docs/PI_SETUP.md](docs/PI_SETUP.md) | Your manual steps, in order, for the Raspberry Pi. |
| [docs/BACKLOG.md](docs/BACKLOG.md) | Everything postponed, with checkboxes. |

## 1. Run it on your computer

You need Python 3.11. The Makefile looks for `/opt/homebrew/bin/python3.11`; if yours is elsewhere,
add `PYTHON=/path/to/python3.11` to each `make install` line.

```
make install                  # creates .venv and installs the dependencies and dev tools
cp .env.example .env          # local settings; .env is never committed
make migrate                  # creates or updates the SQLite database (data/app.db)
make seed                     # optional: the 12 verified number words from CLAUDE.md
make create-user NAME=yourname ROLE=admin
make run                      # http://127.0.0.1:8000, reloads on code changes
```

Notes:

- `make create-user` asks for a password. There is no self sign-up: the admin creates every account.
- `.env` defaults to `EMBEDDER=fake`, which needs no model download (Meaning search is then only
  approximate). To use the real model: `make download-model`, set `EMBEDDER=onnx` in `.env`, then
  `make reindex`.
- Set `APP_TIMEZONE` (for example `Africa/Nairobi`) so "today", the streak and reminder times are
  right. It defaults to UTC.
- Before the first real run, set a long `SESSION_SECRET`
  (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). It is required when `APP_ENV=prod`.

## 2. Check your changes

```
make test        # the test suite
make lint        # ruff, formatting and shellcheck on deploy/*.sh
make audit       # dependency vulnerabilities (needs network) and a secret scan
```

Run `make test` before every commit. Every bug fix gets a test.

## 3. Put it on the Raspberry Pi

The target is a Raspberry Pi 4 (2 GB works). Follow
[docs/PI_SETUP.md](docs/PI_SETUP.md) top to bottom; replace the `<pi-ip>` and `<your-user>` placeholders with your own values. In short:

1. **Prepare the machine**: cap the journal, install Python 3.11 into `/opt/python`,
   install Nginx and SQLite, create the `jifunze` user and `/srv/jifunze`, mount the backup SSD,
   allow the one restart permission.
2. **First release**: write `/etc/jifunze/jifunze.env` from `deploy/jifunze.env.example`, build the
   tarball on your computer with `git archive`, copy it over, prove the dependencies install, copy
   in the systemd and Nginx files, then run `deploy/deploy.sh`.
3. **Check it**: health check, security headers, maintenance page, a backup onto the SSD, and the
   failure-alert email.
4. **Measure, then choose**: `make bench-argon2`, `make bench-embed`, and whether the real
   embedding model fits the 600 MB memory limit.

Production layout: Cloudflare Tunnel, then Nginx on `127.0.0.1:8080`, then Uvicorn on a Unix
socket. The app is reachable from the internet, so every route except login, `/healthz` and static
assets needs a session. Stages 9 and 10 (GitHub Actions deploys, the tunnel, and Cloudflare Access)
are not done yet; see [docs/BACKLOG.md](docs/BACKLOG.md).

The Pi runs Raspberry Pi OS Lite 64-bit (Debian 13 "Trixie"), reflashed on 2026-10-11 because its
old Debian 11 install no longer got security updates. Steps 1 to 5 of `PI_SETUP.md` are already
done on it; continue from step 6 (the SSD).

## Useful commands

```
make migrate                  # apply new migrations (never edit one that has been applied)
make send-reminders ARGS=...  # send or print reminder emails
make import-grammar FILE=...  # load the hand-checked noun-class and verb-paradigm review file
make lock                     # regenerate requirements.lock (needs uv); review the diff
make check-nginx              # nginx -t on the real config in Docker
```

## Security basics

- Never commit `.env`, tunnel credentials or the SQLite file.
- Passwords are hashed with argon2. Session cookies are HttpOnly, Secure and SameSite=Lax.
  State-changing requests need the `X-Requested-With: jifunze` header and a matching `Origin`.
- Admin routes check the role on the server.
