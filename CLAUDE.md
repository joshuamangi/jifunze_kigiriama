# Jifunze Kigiriama

Self-hosted, mobile-first PWA for learning Kigiriama (Giriama, ISO 639-3 `nyf`, a Mijikenda language of the Kilifi/Malindi coast, Kenya). Runs on a Raspberry Pi 4 (4GB), exposed to a small trusted group through a Cloudflare Tunnel. The owner learns the language and builds the database entry by entry.

## The one rule that overrides everything

**Never invent, translate, "correct", or complete Kigiriama text.** No model, including you, has reliable Kigiriama competence. Kigiriama content comes only from (a) entries the user typed, (b) verified sources listed below. If asked for Kigiriama you can't source, say so and leave a TODO. Do not guess spellings, plurals, noun-class prefixes or verb forms.

Test fixtures and seed data may use only verified words: mwenga=1, hiri=2, hahu=3, inne=4, tsano=5, handahu=6, fungahe=7, nane=8, chenda=9, kumi=10, "kumi na hahu"=13, "mirongo miiri"=20 (Omniglot).

## Spelling in UI and docs

Use **Kigiriama** (language) and **Giriama** (people/adjective), never "Kigiryama"/"Giryama". Exception: the archive.org item id `giryamavocabula01taylgoog` and Taylor's 1891 book title, which are quoted as published.

## Stack

- Raspberry Pi OS 64-bit, data on a USB SSD (not microSD: SRS writes wear it).
- Python 3.11+, FastAPI + Uvicorn (one worker). Dev: `127.0.0.1:8000`. Production: Uvicorn on a Unix socket behind Nginx on `127.0.0.1:8080`.
- Staged build guide: `docs/IMPLEMENTATION.md` (supersedes `docs/BUILD_PLAN.md`). If it and this file disagree, stop and ask.
- SQLite + `sqlite-vec` for vector search.
- Embeddings: small GGUF model (~90MB, MiniLM-class) run locally. **Embed the English side only**; embedding models don't know Kigiriama.
- Frontend: plain HTML/CSS/JS (or Svelte) PWA: manifest, service worker, installable. Mobile-first at 390px wide.
- Remote access: `cloudflared` named tunnel -> Nginx `http://127.0.0.1:8080` -> Unix socket -> Uvicorn. systemd services for app and tunnel; Ansible for the machine; secrets with `sops` + `age`; deploys via GitHub Actions to a self-hosted runner on the Pi.
- Email reminders: a scheduled job (systemd timer or cron) on the Pi.

## Data model (keep these invariants)

- `entries`: id, giriama, english, category, source_type (own|dictionary|proverb|scripture), `verification_status` (pending|unverified|self_corrected|native_verified), created_by, created_at, updated_at.
- `entry_vec`: sqlite-vec table keyed by entry id, holds the embedding of `english` only.
- `user_progress`: user_id, entry_id, interval, ease_factor, due_date, last_reviewed. **SRS state lives here, never on `entries`**, because entries are shared across users.
- `users`: id, username, password_hash (argon2/bcrypt), role (admin|member).
- `noun_classes`, `verb_paradigms`: grammar rules extracted once from Taylor's dictionary front matter, then hand-checked. Rules are data, not code.
- Moderation reuses `verification_status`: member submissions start as `pending`, are invisible to others until an admin approves in the review queue.
- Editing an entry in place is a first-class feature (the owner expects to fix wrong words). Keep an edit history rather than silent overwrites.

SQLite stores; it does not "learn". Teaching logic lives in app code that combines grammar rules + words into drills.

## Teaching model

Three layers: Lexicon (words) / Grammar rules (tables above) / App logic (drills). Difficulty ladder, 8 tiers: Sounds & orthography -> Core vocabulary -> Noun classes -> Verb morphology -> Proverbs -> Single verses -> Short passages -> Guided reading. Review scheduling is SM-2 style. Daily session target is about 20 minutes. Home screen suggests the category with the fewest entries.

## Verified sources (the only Kigiriama sources)

- Taylor, *Giryama Vocabulary and Collections* (1891), archive.org `giryamavocabula01taylgoog` (OCR text is noisy: always flag low-confidence parses for human check).
- *African Aphorisms / Methali za Kiswahili*, maktaba.org: Giriama/Nyika proverbs start around p.150.
- eBible.org Giriama New Testament (public domain) with World English Bible for parallel English. **No Old Testament is freely available digitally.**
- Radio Kaya (radiokaya.co.ke), Global Recordings Network audio.

## Auth and exposure

The app is reachable from the public internet through the tunnel, so:

- Every route except `/login`, static assets and `/healthz` requires a session.
- Hashed passwords (argon2/bcrypt), HttpOnly + Secure + SameSite=Lax session cookie, login rate limiting.
- No self sign-up: the admin creates accounts (small trusted group).
- Admin routes check `role == 'admin'` server-side; hiding the UI is not enough.
- Preferred hardening: put Cloudflare Access (email allow-list) in front of the hostname as a second gate.
- Never commit `.env`, `~/.cloudflared/*.json` credentials, or the SQLite file.

## Design system

Theme tokens are in `docs/theme.css` (dark default, `.theme-root.light` override, hsl fallback plus oklch). Use only those CSS variables, not hard-coded colors.

- Font: **Kodchasan** (400/500/600/700), antialiased.
- Icons: hand-drawn stroke SVGs, no emoji.
- Touch targets at least 44px. Real `<button>` and `<a>` elements.
- Bottom nav, 5 items: Home, Add, Learn, Culture, Settings. Login has no nav. Admin Review is reached from Settings, not the nav.
- Don't invent stats, users or placeholder text.
- The clickable prototype (Claude Design artifact) is the visual reference for screen layout.

## Commands

<!-- Fill in once the project exists; keep them exact. -->
- Install: `make install` (Python 3.11 venv in `.venv`, deps from `pyproject.toml`)
- Run dev: `make run` (uvicorn with reload on 127.0.0.1:8000)
- Test: `make test`
- Lint: `make lint`
- Secret scan: `make audit-secrets`

## Working agreements

- Plan first for anything touching the schema, auth, or SRS; then implement in small steps.
- Run tests after changes. Add a test for every bug fixed.
- Migrations are numbered SQL files in `migrations/`; never edit an applied migration.
- Don't add dependencies without saying why: the Pi has 4GB RAM and everything shares it.
- Ask before deleting data, changing the DB schema destructively, or touching tunnel/systemd config.
