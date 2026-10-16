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

## The Pi: decisions and follow-ups
- [x] Option A chosen 2026-10-11: database on the SD card, backups on the exFAT SSD, Python 3.11
      from `/opt/python` (uv). CLAUDE.md still says "data on a USB SSD, not microSD" and "Pi 4
      (4GB)"; this Pi has 2 GB and no ext4 SSD yet. Ask before editing CLAUDE.md.
- [ ] Work through `docs/PI_SETUP.md` from step 1. Step 10 (install every dependency with the lock
      file on this Pi) is the likeliest place for a surprise.
- [ ] Later (option B): move the SSD to an ext4 partition for `/srv/jifunze` plus a data partition
      (optionally LUKS) and a reserve, then move `DATABASE_PATH` off the SD card. Needs enough
      temporary space to copy the existing files off first.
- [ ] Off-device copy of backups (`BACKUP_COPY_COMMAND`) to another machine.
- [ ] Simple observability for the Pi once Stage 10 is finished: `node_exporter` (or a small push
      script), CPU/load, memory, temperature and throttling (`vcgencmd`), disk, and an alert.
      Keep it small: this Pi has 2 GB.
- [ ] Hardware: check heatsink/fan and a 5V/3A supply.

## Stage 9: GitHub Actions
- [x] CI runs `make lint`, `make test`, `make audit-deps` (pip-audit), the secret scan and the front-end size budget (`.github/workflows/ci.yml`, written 2026-10-11, not yet run on GitHub).
- [x] Stage 9 decision taken: the runner gets its own `ghrunner` user in group `jifunze` (docs/RUNNER_SETUP.md).
- [x] CI green on GitHub; RUNNER_SETUP worked through on the Pi (2026-10-14/15). It needed one fix
      the docs had missed: `/srv/jifunze` itself must be group-writable (see "first deploy" below).
- [x] GitHub settings, read back from the API on 2026-10-15: `production` has a required reviewer and only
      tag `v*` may deploy; fork PR approval is "all external contributors"; default token is read-only;
      the runner is registered to this repo only.
- [ ] The repository is PUBLIC (the older notes said private). Decide: keep, or go private (environment
      protection may need a paid plan then). Public also means GitHub's free ARM64 hosted runners are
      available, so an ARM64 CI job is possible if wanted.
- [ ] Protect `main` (require a pull request and the `test` check). Optional.
- [ ] Checksum in the release only guards against corruption. Add artifact attestation if you want tamper-evidence.

## Stage 10: Cloudflare Tunnel, Access and infrastructure as code
Built 2026-10-13; applied to the Pi and Cloudflare 2026-10-14 to 16.
- [x] Access JWT middleware (`app/access.py`, `CF_ACCESS_*`), tested with a local key pair; live since v0.1.0
      (a request without a token gets 403, `/healthz` stays open).
- [x] `deploy/cloudflared/` config and sandboxed unit; tunnel running on the Pi (4 connections), site
      reachable at https://kigiriama.techjamaa.com only through Cloudflare Access.
- [x] `infra/ansible/` applied (all roles, including SSH hardening and the nftables firewall), secrets in
      `secrets.sops.yaml` (sops + age). Confirm the age private key (`~/.config/sops/age/keys.txt`) is
      backed up outside this Mac: without it the secrets file cannot be opened.
- [x] `infra/terraform/` written and validated, deliberately not used (the Cloudflare side was done by hand).
- [x] `scripts/restore_drill.py` / `make restore-drill`; docs written.
- [x] First deploy through GitHub Actions: v0.1.0 live on 2026-10-16 (after fixing the base-directory
      permission; the first attempt failed safely at step 5/9 and left v0.0.2 running).
- [x] Restore drill on a real Pi backup passed on 2026-10-16. That backup had 0 entries, so re-run it with
      `--expect entries=<n>` once the dictionary has content.
- [x] Refusal test (2026-10-16): an email that is not on the Access allow-list is never sent a code.
- [x] Login through Access works with the app's own gate on (checked after v0.1.0 went live).
- [x] Rollback rehearsal passed 2026-10-16 (about 33 s outage). It found that a crash-looping release made
      the rollback's restart fail (systemd start limit); fixed in v0.1.2 with `reset-failed` (#70).
- [ ] Failure alerts do not work yet: `ALERT_EMAIL` is empty on the Pi, so `notify_failure.py` exits 1 and
      nobody is told when the app dies. Gmail + app password chosen; see the alerts PR and `docs/GO_LIVE.md`
      section 7.
- [ ] Delete `~/.cloudflared/*.json`, `cert.pem` and `cert.pem.old-2025` from the Mac.
- [ ] Off-device copy of the backups (`BACKUP_COPY_COMMAND`); the SSD is in the same Pi.
- [ ] Decide whether Nginx should also check the Access token for static files (`auth_request`); today those
      rely on Cloudflare Access at the edge only.
- [ ] `ansible-pull` is documented but unrun; it needs sops installed on the Pi and puts the age key there.
- [ ] Old releases v0.0.1 and v0.0.2 belong to `jifunze` and are not group-writable. The deploy script now
      only warns if it cannot prune them; `sudo chmod -R g+w` on them lets the runner remove them.

## Yours to fill in (not code)
- [ ] Noun classes and verb paradigms from Taylor's front matter, into the review file for
      `make import-grammar FILE=...`. Nothing is generated.
- [ ] Create the real accounts with `make create-user`.
