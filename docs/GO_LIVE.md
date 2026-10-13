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
- [ ] Tunnel up: `systemctl status cloudflared` is active; `journalctl -u cloudflared -n 20` shows
      registered connections.
- [ ] **Access, from outside your network** (phone on mobile data, private window):
  - [ ] An address that is on the allow-list gets the email code and then the login page.
  - [ ] An address that is **not** on the list is refused and receives nothing useful. Try a real
        second email you control.
  - [ ] `curl -si https://<hostname>/` without signing in does not return the app (a Cloudflare
        login or 403, never the Jifunze page).
- [ ] The app's own gate: with `cf_access_enabled: true`, `curl -si https://<hostname>/healthz`
      still answers (Access aside), and a request that reaches the app without the token gets 403.
      If you cannot test this from outside, `curl -si http://127.0.0.1:8080/api/me` on the Pi must be 403.
- [ ] `ALLOWED_ORIGINS` is `https://<hostname>`; signing in and adding an entry works through the
      public address.

## 5. Backups and restore
- [ ] A backup has run: `sudo systemctl start jifunze-backup.service`, a new file is in
      `/mnt/ssd/jifunze-backups`, and the System status screen shows the time.
- [ ] **Restore drill passed once** on a real backup: `docs/RESTORE_DRILL.md`, with `--expect` counts
      copied from the live app.
- [ ] Off-device copy: `BACKUP_COPY_COMMAND` is set and a copy arrived on the other machine, or you
      have written down that you accept the SSD being on the same Pi.

## 6. Deploy and rollback
- [ ] The runner is limited (`docs/RUNNER_SETUP.md` "Check it"): `sudo -u ghrunner sudo -n systemctl
      restart jifunze.service` works; `sudo -u ghrunner sudo -n true` fails; `id ghrunner` shows
      no `sudo` group.
- [ ] GitHub settings: `production` environment has required reviewers, fork pull requests need
      approval, the default token is read-only, the runner is limited to this repository. A deploy
      waits for your approval before it starts.
- [ ] A normal deploy of the release went live (`deploy.sh` prints "release vX is live").
- [ ] **Rollback rehearsal (not run yet):** prove a bad release leaves the old one running. On your
      Mac, from a clean checkout of the release:
      ```
      git archive --format=tar.gz -o bad.tar.gz HEAD app web migrations scripts deploy pyproject.toml requirements.lock
      ```
      Unpack it, add the line `raise RuntimeError("rollback rehearsal")` at the top of `app/main.py`, repack
      as `jifunze-vX.Y.Z-rollbacktest.tar.gz`, copy it to `/srv/jifunze/incoming/` on the Pi, and run
      `sudo -u jifunze /srv/jifunze/current/deploy/deploy.sh vX.Y.Z-rollbacktest`. Expected: the health
      check fails, `deploy.sh` rolls back, `readlink /srv/jifunze/current` is the previous release, the
      site still works. Delete the test release folder afterwards.

## 7. Monitoring
- [ ] The failure email arrives when a unit fails (PI_SETUP step 20).
- [ ] Optional but planned: Pi observability (`docs/BACKLOG.md`).

## After go-live
Tell the group the address and give each person their username and the password you set. The app
has no self-service password change, so a new password means `scripts/reset_password.py` run by you.
Note the go-live date here.
