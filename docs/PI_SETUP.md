# Raspberry Pi setup: your manual steps, in order

Everything the Pi needs is in git (`deploy/`, `requirements.lock`). These are the steps that only
you can do, once, in this order. Commands run on the Pi unless it says "on your Mac". Names used
throughout: user `jifunze`, base directory `/srv/jifunze`, env file `/etc/jifunze/jifunze.env`.

Stage 10 (Ansible) will automate steps 3 to 7. Do them by hand first so you know what they do.

## A. The machine

1. **Flash the OS.** Raspberry Pi Imager, *Raspberry Pi OS Lite (64-bit)*. In the settings
   dialog: set a hostname, create your admin user, **enable SSH with a public key only** (no
   password), set the time zone to `Africa/Nairobi` and your locale. Boot it, `ssh` in.
2. **Use the USB SSD for data.** The SRS writes constantly and would wear a microSD card. Plug in
   the SSD, then:
   ```
   lsblk                                   # find it, e.g. /dev/sda
   sudo mkfs.ext4 -L jifunze /dev/sda1     # DESTROYS everything on it; check the device first
   sudo mkdir -p /srv/jifunze
   sudo blkid /dev/sda1                    # copy the UUID
   ```
   Add to `/etc/fstab` (use your UUID): `UUID=XXXX-XXXX /srv/jifunze ext4 defaults,noatime,nofail 0 2`
   then `sudo mount -a && df -h /srv/jifunze`. The units refuse to start if this mount is missing,
   so an unplugged drive can never make the app create a database on the SD card.
3. **Install packages.**
   ```
   sudo apt update && sudo apt full-upgrade -y
   sudo apt install -y nginx sqlite3 curl python3-venv python3-pip unattended-upgrades
   sudo dpkg-reconfigure -plow unattended-upgrades
   ```
   Check `python3 --version` is 3.11 or newer (Bookworm ships 3.11).
4. **Create the service user and let Nginx reach its socket.**
   ```
   sudo adduser --system --group --home /srv/jifunze --no-create-home jifunze
   sudo usermod -aG jifunze www-data
   ```
5. **Create the directories.**
   ```
   sudo install -d -o jifunze -g jifunze -m 0755 /srv/jifunze/releases /srv/jifunze/incoming
   sudo install -d -o jifunze -g jifunze -m 0750 /srv/jifunze/data /srv/jifunze/backups /srv/jifunze/models
   sudo install -d -o root -g jifunze -m 0750 /etc/jifunze
   ```
6. **Let the deploy user restart the one service, and nothing else.** Create
   `/etc/sudoers.d/jifunze` with `sudo visudo -f /etc/sudoers.d/jifunze`:
   ```
   jifunze ALL=(root) NOPASSWD: /usr/bin/systemctl restart jifunze.service
   ```
   (`deploy.sh` runs as `jifunze` for now. Stage 9 may give the GitHub runner its own user.)
7. **Cap the logs.** `sudo mkdir -p /etc/systemd/journald.conf.d` and put in
   `/etc/systemd/journald.conf.d/jifunze.conf`: `[Journal]`, `SystemMaxUse=200M`,
   `MaxRetentionSec=1month`. Then `sudo systemctl restart systemd-journald`.

## B. The first release

8. **Write the environment file.** On the Pi: copy `deploy/jifunze.env.example` to
   `/etc/jifunze/jifunze.env` (`sudo install -m 0640 -o root -g jifunze ... `), then fill in
   `SESSION_SECRET` (the command is in the file), your public hostname in `ALLOWED_ORIGINS` and
   `APP_BASE_URL`, and the SMTP and `ALERT_EMAIL` lines. Leave `EMBEDDER=fake` for now.
9. **Build the first tarball, on your Mac** (Stage 9 will do this in CI). From the repo, on a
   clean commit:
   ```
   git archive --format=tar.gz -o jifunze-v0.1.0.tar.gz HEAD \
     app web migrations scripts deploy pyproject.toml requirements.lock
   shasum -a 256 jifunze-v0.1.0.tar.gz
   scp jifunze-v0.1.0.tar.gz YOURUSER@PI:/tmp/
   ```
   On the Pi: `sudo install -o jifunze -g jifunze /tmp/jifunze-v0.1.0.tar.gz /srv/jifunze/incoming/`
   and compare the checksum with the one on your Mac.
10. **Install the units and Nginx files** (from the tarball, as the deploy scripts do not exist on
    the Pi yet):
    ```
    mkdir /tmp/boot && tar -xzf /srv/jifunze/incoming/jifunze-v0.1.0.tar.gz -C /tmp/boot deploy
    sudo cp /tmp/boot/deploy/systemd/* /etc/systemd/system/
    sudo cp /tmp/boot/deploy/nginx/jifunze.conf /etc/nginx/conf.d/
    sudo mkdir -p /etc/nginx/snippets
    sudo cp /tmp/boot/deploy/nginx/jifunze-proxy.conf /tmp/boot/deploy/nginx/jifunze-security-headers.conf /etc/nginx/snippets/
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo systemctl daemon-reload
    ```
11. **Deploy it.** First rehearse, then do it (as `jifunze`, so file ownership is right):
    ```
    sudo -u jifunze /tmp/boot/deploy/deploy.sh --dry-run v0.1.0
    sudo -u jifunze /tmp/boot/deploy/deploy.sh v0.1.0
    ```
    Expected: nine numbered steps, "first deploy: nothing to back up", then
    "release v0.1.0 is live". If the health check fails you are told so and the release stays
    unswitched or rolled back; read `journalctl -u jifunze -n 50`.
12. **Start Nginx and enable everything.**
    ```
    sudo nginx -t && sudo systemctl enable --now nginx && sudo systemctl reload nginx
    sudo systemctl enable jifunze.service
    sudo systemctl enable --now jifunze-reminders.timer jifunze-backup.timer jifunze-optimize.timer
    systemctl list-timers 'jifunze-*'
    ```
13. **Create your admin account.**
    ```
    cd /srv/jifunze/current && sudo -u jifunze bash -c \
      'set -a; . /etc/jifunze/jifunze.env; set +a; PYTHONPATH=. .venv/bin/python scripts/create_user.py --username YOU --role admin'
    ```

## C. Check it works (these checks exist only on the Pi)

14. `/srv/jifunze/current/deploy/healthcheck.sh` prints `app: ok`, then power and temperature.
    Any `WARN: under-voltage` means a better power supply, before anything else.
15. `curl -si http://127.0.0.1:8080/healthz` returns `{"status":"ok"}` with the security headers;
    `curl -si http://127.0.0.1:8080/` returns the page with the same headers.
16. Stop the app (`sudo systemctl stop jifunze`) and load `http://127.0.0.1:8080/`: the
    maintenance page appears. Start it again.
17. Run a backup now: `sudo systemctl start jifunze-backup.service`, then
    `ls -l /srv/jifunze/backups` and open the System status screen: "Last backup" shows the time.
18. **Test the failure alert:** `sudo systemctl start jifunze-failure@jifunze-backup.service`.
    You should get the email. If not, check `ALERT_EMAIL` and `SMTP_*` and `journalctl -u 'jifunze-failure@*'`.
19. **Sandbox check:** `systemd-analyze security jifunze.service` (score only; lower is tighter).
    If the app dies with `SIGSYS` or cannot read CPU info once the real model is on, loosen
    `SystemCallFilter` in `deploy/systemd/jifunze.service` and note why.
20. `sudo nginx -t` (this is the syntax check that could not run on the Mac) and
    `systemd-analyze verify /etc/systemd/system/jifunze*.service /etc/systemd/system/jifunze*.timer`.

## D. Measure, then choose (see docs/BACKLOG.md)

21. `bench_argon2.py` and `bench_embed.py` (from `/srv/jifunze/current`, with the env file loaded as in
    step 13). Set `ARGON2_*` and `EMBEDDER`/`EMBED_MODEL` in the env file, `sudo systemctl restart jifunze`.
    For the real model: run `scripts/download_model.py`, set `EMBEDDER=onnx`, run `scripts/reindex.py`,
    and watch `systemctl status jifunze` for memory against `MemoryMax=1G`.

## E. When things go wrong

- **Bad deploy:** `deploy.sh` rolls back by itself if the health check fails. To go back by hand:
  `sudo -u jifunze /srv/jifunze/current/deploy/rollback.sh`. Running it again rolls forward.
- **Restore the database from a backup** (rollback never restores data): `sudo systemctl stop jifunze`;
  `cp` the chosen `/srv/jifunze/backups/app-*.db` over `/srv/jifunze/data/app.db`; delete
  `app.db-wal` and `app.db-shm` next to it; `sudo chown jifunze:jifunze` the file;
  `sudo systemctl start jifunze`. Stage 10 adds a full restore drill.
- **Release rule:** migrations must be backward compatible (add in one release, remove in a later
  one), so the previous code always runs on the new schema.
