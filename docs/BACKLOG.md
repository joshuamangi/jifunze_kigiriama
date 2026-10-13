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
- [ ] Push, open a test PR and confirm CI is green; then work through docs/RUNNER_SETUP.md on the Pi.
- [ ] GitHub settings (see the Stage 9 report): `production` environment with required reviewers, fork PR approval, default workflow token read-only, runner restricted to this repo.
- [ ] No ARM64 CI job: the repo is private, and GitHub's free ARM64 hosted runners are for public repos. The Pi deploy is the first ARM64 run.
- [ ] Checksum in the release only guards against corruption. Add artifact attestation if you want tamper-evidence.

## Stage 10: Cloudflare Tunnel, Access and infrastructure as code
Written 2026-10-13 and validated on the Mac only. None of it has run against the Pi or Cloudflare.
- [x] Access JWT middleware (`app/access.py`, `CF_ACCESS_*`), tested with a local key pair.
- [x] `deploy/cloudflared/` config template and sandboxed unit.
- [x] `infra/ansible/` (`ansible-lint --profile production` clean, `--syntax-check` passes).
- [x] `infra/terraform/` (`terraform validate` passes against provider v5.27). Optional.
- [x] `scripts/restore_drill.py` / `make restore-drill`; `docs/CLOUDFLARE_SETUP.md`,
      `docs/RESTORE_DRILL.md`, `docs/GO_LIVE.md`.
- [ ] Generate the age key, fill `.sops.yaml`, create `infra/ansible/secrets.sops.yaml`
      (`infra/ansible/README.md`). Back up the private key.
- [ ] Fill `group_vars/all.yml` and `inventory/hosts.yml`; run `ansible-playbook site.yml --check --diff`
      against the Pi and read it. Likely surprises: the mount options on the exFAT SSD, the firewall
      rule for your network, the `uv` path.
- [ ] Cloudflare steps in `docs/CLOUDFLARE_SETUP.md` (tunnel, DNS, Access application, email allow-list).
      Then `cloudflared_enabled`, and last `cf_access_enabled`.
- [ ] Look up the cloudflared release and its sha256 (never guessed in the repo).
- [ ] Restore drill from a real Pi backup, rollback rehearsal, and the rest of `docs/GO_LIVE.md`.
- [ ] Decide whether Nginx should also check the Access token for static files (`auth_request`);
      today those rely on Cloudflare Access at the edge only.
- [ ] `ansible-pull` is documented but unrun; it needs sops installed on the Pi and puts the age key there.

## Yours to fill in (not code)
- [ ] Noun classes and verb paradigms from Taylor's front matter, into the review file for
      `make import-grammar FILE=...`. Nothing is generated.
- [ ] Create the real accounts with `make create-user`.
