# Backlog: things deliberately left for later

One place for everything that was postponed, each tied to the stage that does it. Tick a box when
done. Stage names and numbers follow `docs/IMPLEMENTATION.md`; this file adds work, it does not
change the stages there.

## Stage 7 follow-up (done)
- [x] Admin "System status" screen (Settings > System status).
- [ ] Manual browser checks for Stage 7 (needs you): add an entry whose English meaning is
      `<img src=x onerror=alert(1)><script>alert(2)</script>` and confirm it shows as text; confirm
      dev tools reports a CSP violation for an injected inline `<script>`.
- [ ] Optional: an admin view of the `audit_log` table. No screen reads it yet.

## Stage 8: Pi packaging and deploy scripts (written and tested here; needs the Pi to verify)
- [x] `backup.sh` touches `BACKUP_STAMP_PATH` after a verified backup.
- [x] Nginx timeouts, login `limit_req`, body cap; the systemd unit reuses the Uvicorn limits.
- [x] Journald size limit (PI_SETUP step 7).
- [ ] Work through `docs/PI_SETUP.md` sections A to C on the Pi, in order. Checks that exist only
      there: `sudo nginx -t`, `systemd-analyze verify` and `security`, the sandbox with the real
      model (SystemCallFilter, `/proc/cpuinfo`), `healthcheck.sh` power and temperature, the
      failure-alert email, one real deploy and one deliberately failing deploy.
- [ ] Stage 9 decision: `deploy.sh` runs as the `jifunze` service user for now. Decide whether the
      GitHub runner gets its own user (it would then need group access to `data/` and the env file).
- [x] `make check-nginx` passed on the Mac (nginx:stable, 2026-10-10). Still run `sudo nginx -t` on the Pi.

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
