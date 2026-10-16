# Go-live checklist

Work top to bottom and tick as you go. Do not tell anyone the address until every box is ticked.
Each line says how to check it. "Not run yet" items are rehearsals nobody has done on the real Pi.

## 1. The code
- [ ] Tests green on the commit you are releasing: `make lint test audit` locally, and the CI run on
      the pull request or tag is green.
- [ ] `git status` is clean, you are deploying a tagged release (`vX.Y.Z`), and the release has its
      checksum asset.

## 2. The machine
- [ ] `docs/PI_SETUP.md` sections A to C are done, or `ansible-playbook site.yml --check --diff` was
      read and the playbook applied (`infra/ansible/README.md`).
- [ ] `deploy/healthcheck.sh` prints `app: ok` and no `WARN: under-voltage`.
- [ ] Firewall: from another computer on the network, `nc -vz <pi-ip> 80`, `8080` and `8000` all
      fail; SSH works only from the addresses in `ssh_allowed_cidrs`. On the Pi: `sudo nft list ruleset`
      shows `policy drop` on input.
- [ ] SSH is key-only: `ssh -o PubkeyAuthentication=no <user>@<pi-ip>` is refused.
- [ ] No default or shared passwords: the Pi's login uses a key, `/etc/jifunze/jifunze.env` has a
      generated `SESSION_SECRET` (not empty), and no account was created with a throwaway password.
      `sudo grep -c '^SESSION_SECRET=.\{40,\}' /etc/jifunze/jifunze.env` prints 1.
- [ ] Unplugged-SSD guard (PI_SETUP step 19) and the failure-alert email (step 20) both work.

## 3. Accounts
- [ ] Your admin account exists (`scripts/create_user.py --role admin`, PI_SETUP step 14) and you can
      sign in. `PASSWORD_MIN_LENGTH` is 12 or more.
- [ ] Other accounts are created by you for each person; there is no sign-up. Anyone who forgets a
      password gets `scripts/reset_password.py` (PI_SETUP section E).
- [ ] You tried to reach an admin page (Settings, then Review) as a normal member and were refused.

## 4. Cloudflare
- [x] Tunnel up (2026-10-16): `systemctl status cloudflared` is active; `journalctl -u cloudflared -n 20` shows
      registered connections.
- [ ] **Access, from outside your network** (phone on mobile data, private window):
  - [x] An address that is on the allow-list gets the email code and then the login page.
  - [x] An address that is **not** on the list is refused and receives nothing useful (2026-10-16:
        a second address that is not on the list was never sent a code). Try a real second email you control.
  - [x] `curl -si https://<hostname>/` without signing in does not return the app (a Cloudflare
        login or 403, never the Jifunze page).
- [x] The app's own gate (live since v0.1.0, 2026-10-16): with `cf_access_enabled: true`, `curl -si https://<hostname>/healthz`
      still answers (Access aside), and a request that reaches the app without the token gets 403.
      If you cannot test this from outside, `curl -si http://127.0.0.1:8080/api/me` on the Pi must be 403.
- [ ] `ALLOWED_ORIGINS` is `https://<hostname>`; signing in and adding an entry works through the
      public address. (Signing in through Access with the gate on is verified; adding an entry has
      not been tried yet.)

## 5. Backups and restore
- [x] A backup has run: the nightly timer and every deploy write a new file to
      `/mnt/ssd/jifunze-backups` (seen 2026-10-16). Also look at the System status screen once.
- [x] **Restore drill passed once** on a real backup (2026-10-16, `docs/RESTORE_DRILL.md`). That backup
      had 0 entries, so it proved the mechanism, not real data: run it again with `--expect entries=<n>`
      once the dictionary has content.
- [ ] Off-device copy: `BACKUP_COPY_COMMAND` is set and a copy arrived on the other machine, or you
      have written down that you accept the SSD being on the same Pi.

## 6. Deploy and rollback
- [x] The runner is limited (`docs/RUNNER_SETUP.md` "Check it"; verified 2026-10-16): `sudo -u ghrunner
      sudo -n systemctl restart jifunze.service` and `... reset-failed jifunze.service` work;
      `sudo -u ghrunner sudo -n true` and `... systemctl stop jifunze.service` fail; `id ghrunner`
      shows no `sudo` group.
- [x] GitHub settings (read back from the API 2026-10-15): `production` environment has required reviewers, fork pull requests need
      approval, the default token is read-only, the runner is limited to this repository. A deploy
      waits for your approval before it starts.
- [x] A normal deploy of the release went live (v0.1.0, v0.1.1 and v0.1.2 on 2026-10-16;
      `deploy.sh` prints "release vX is live").
- [x] **Rollback rehearsal passed** (2026-10-16, v0.1.2 as the good release): a deliberately crashing
      release left the old one running. The site was down for about 33 seconds. Procedure, so it can be
      repeated after a change to `deploy/` or the unit files:

      On the Mac, from a clean checkout (`vX.Y.Z` is the release that is live):
      ```
      mkdir -p /tmp/rb/src
      git archive vX.Y.Z app web migrations scripts deploy pyproject.toml requirements.lock | tar -x -C /tmp/rb/src
      { echo 'raise RuntimeError("rollback rehearsal: deliberately broken")'; cat /tmp/rb/src/app/main.py; } > /tmp/rb/main.py
      mv /tmp/rb/main.py /tmp/rb/src/app/main.py
      COPYFILE_DISABLE=1 tar -czf /tmp/rb/jifunze-rollbacktest.tar.gz -C /tmp/rb/src app web migrations scripts deploy pyproject.toml requirements.lock
      scp /tmp/rb/jifunze-rollbacktest.tar.gz <pi>:/tmp/
      ```
      Break `app/main.py`, not `app/__init__.py` or `app/migrate.py`: the migration step imports
      `app.config` and `app.db` only, so the failure must come *after* the switch, where the rollback
      lives. On the Pi, as `ghrunner` (the user the GitHub workflow deploys as):
      ```
      sudo install -o ghrunner -g jifunze -m 0664 /tmp/jifunze-rollbacktest.tar.gz /srv/jifunze/incoming/
      sudo -u ghrunner /srv/jifunze/current/deploy/deploy.sh rollbacktest
      ```
      Expected: steps 1 to 4 pass; `5/9 switch`, `6/9 restart`, then `health check FAILED after 15
      attempt(s)`, `health check failed: rolling back`, `rollback: current -> releases/vX.Y.Z`, `app: ok`,
      and a last line `ERROR: release rollbacktest failed its health check; the previous release is back`
      with a non-zero exit. That error is the pass condition. Then clean up (the rollback swapped
      `previous`, so set it back to the release that was `previous` before):
      ```
      sudo -u ghrunner rm -rf /srv/jifunze/releases/rollbacktest /srv/jifunze/incoming/jifunze-rollbacktest.tar.gz
      rm -f /tmp/jifunze-rollbacktest.tar.gz
      echo vPREV | sudo -u ghrunner tee /srv/jifunze/previous
      ```
      Why the unit file and `deploy/lib.sh` matter here: a release that crashes on start makes systemd give
      up after `StartLimitBurst=5` starts (about 20 seconds with `RestartSec=3`) and refuse every later
      start, including the rollback's. `restart_service` therefore runs `systemctl reset-failed` first, and
      the sudo rules allow exactly that verb. Without it this rehearsal ends in `ROLLBACK FAILED`.

## 7. Monitoring
- [ ] The failure email arrives when a unit fails (PI_SETUP step 20).
- [ ] Optional but planned: Pi observability (`docs/BACKLOG.md`).

## After go-live
Tell the group the address and give each person their username and the password you set. The app
has no self-service password change, so a new password means `scripts/reset_password.py` run by you.
Note the go-live date here.
