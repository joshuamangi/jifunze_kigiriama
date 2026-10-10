# Backlog: things deliberately left for later

One place for everything that was postponed, each tied to the stage that does it. Tick a box when
done. Stage names and numbers follow `docs/IMPLEMENTATION.md`; this file adds work, it does not
change the stages there.

## Next: Stage 7 follow-up (small, do before Stage 8)
- [ ] **Admin "System status" screen.** Admin-only, reached from Settings like Admin Review (not in
      the bottom nav). Shows what `GET /api/admin/status` returns: database and WAL size, entries
      awaiting an embedding, last backup time, failed logins in the last 24 hours. Must render
      values as text (no `innerHTML`), use only theme tokens, 44px touch targets, no emoji.
      The "last backup" field reads "never" until Stage 8 runs a backup.
- [ ] **Manual browser checks for Stage 7** (needs you, in a browser): add an entry whose English
      meaning is `<img src=x onerror=alert(1)><script>alert(2)</script>` and confirm it shows as
      text; confirm dev tools reports a CSP violation for an injected inline `<script>`.
- [ ] Optional: an admin view of the `audit_log` table (recent events). No screen reads it yet.

## Stage 8: Pi packaging and deploy scripts
- [ ] `backup.sh` must `touch` the file at `BACKUP_STAMP_PATH` (default `data/last_backup`) after a
      verified backup, so the status screen shows the real time.
- [ ] Nginx: `client_header_timeout`, `client_body_timeout`, `limit_req` on `/api/login`, and a body
      cap matching `MAX_BODY_BYTES` (Uvicorn has no per-request read timeout).
- [ ] systemd unit: reuse the Uvicorn limits from the Makefile (`UVICORN_LIMITS`:
      `--limit-concurrency 64 --timeout-keep-alive 5 --timeout-graceful-shutdown 10
      --no-server-header --no-access-log`), plus `--uds` for the socket.
- [ ] Journald log size limits so the JSON request log cannot fill the SSD.

## On the Raspberry Pi (needs the hardware, cannot be done on the Mac)
- [ ] `make bench-argon2`: tune `ARGON2_MEMORY_KIB` / `ARGON2_TIME_COST` so a login takes a
      sensible time on the Pi 4.
- [ ] `make download-model`, then `make bench-embed` for fp32 vs qint8; choose `EMBED_MODEL`.
- [ ] Set `EMBEDDER=onnx`, run `make reindex`, and check memory use with the app running.
- [ ] Check `THREADPOOL_SIZE` (8 to 16) and `--limit-concurrency` under a little real load.
- [ ] Confirm the slow-database log lines (over 100 ms) are rare on the SSD; if not, find the query.
- [ ] Confirm `make audit` (needs network) runs on the Pi or in CI.

## Stage 9: GitHub Actions
- [ ] CI runs `make lint`, `make test`, and `make audit-deps` (pip-audit) plus the secret scan.

## Stage 10: Cloudflare Tunnel and Access
- [ ] Cloudflare Access email allow-list in front of the hostname; set `ALLOWED_ORIGINS` to it.
- [ ] Restore drill from a real backup before going live.

## Yours to fill in (not code)
- [ ] Noun classes and verb paradigms from Taylor's front matter, into the review file for
      `make import-grammar FILE=...`. Nothing is generated.
- [ ] Create the real accounts with `make create-user`.
