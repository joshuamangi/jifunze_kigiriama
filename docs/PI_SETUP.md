# Raspberry Pi setup: your manual steps, in order

This file is written for a Pi set up on 2026-10-11. The SD card was reflashed that day
with Raspberry Pi OS Lite 64-bit, Debian 13 "Trixie" (kernel 6.18, systemd 257, Nginx 1.26, SQLite
3.46, system Python 3.13), because the old Debian 11 install had lost its security updates. The
Pi has 1.8 GiB RAM and a 128 GB SD card; there is no Docker. Section A below was
already done on 2026-10-11 (see "Already done"). Anything that differs on your Pi, stop and ask.

**Network:** give the Pi a static address (`<pi-ip>` below), for example in NetworkManager
(`nmcli connection show`) rather than only a router reservation, which some routers ignore.

**Already done (2026-10-11):** fresh OS with the hostname, user and SSH key from Imager;
passwordless `sudo` for your user (`<your-user>` below); `apt full-upgrade`; unattended-upgrades; journald capped at
100M; Bluetooth disabled; Trixie's own `rpi-swap` zram swap left as it is (do not install
`zram-tools`, it conflicts); uv 0.13.0 in `~/.local/bin`; Python 3.11 in `/opt/python`; Nginx, sqlite3 and exfatprogs
installed (Nginx is **stopped and disabled** until step 13); user `jifunze` (group id **105**);
the directories from step 5.

**Layout chosen (Option A, "start now, don't touch the SSD"):**
- The **database lives on the SD card** at `/srv/jifunze/data`. This departs from CLAUDE.md
  ("data on a USB SSD, not microSD"). It is acceptable for a small dictionary with light writes
  *because every night's backup goes to the SSD and then off the Pi*. Move it to an SSD partition
  later (docs/BACKLOG.md).
- The **SSD stays exFAT with its existing files untouched.** It is mounted at `/mnt/ssd`
  and only the folder `jifunze-backups` on it is used by this project.
- Python 3.11 comes from a standalone build (`uv`) in `/opt/python`; the system Python is untouched.

Names: user `jifunze`, base directory `/srv/jifunze`, env file `/etc/jifunze/jifunze.env`.
Run commands on the Pi (`ssh <your-user>@<pi-ip>`) unless it says "on your Mac".

## A. Prepare the machine

1. **Cap the journal** so logs cannot fill the SD card. On a fresh Debian 13 install nothing else
   is needed here: Trixie ships its own zram swap (`rpi-swap`), so do not install `zram-tools`
   (it conflicts).
   ```
   sudo mkdir -p /etc/systemd/journald.conf.d
   printf '[Journal]\nSystemMaxUse=100M\nMaxRetentionSec=1month\n' | sudo tee /etc/systemd/journald.conf.d/jifunze.conf
   sudo journalctl --vacuum-size=100M
   sudo systemctl restart systemd-journald
   free -h
   ```
2. **Install Python 3.11 where the service user can read it.** (uv 0.13.0 is already in
   `~/.local/bin`; it was downloaded from the GitHub release and its checksum verified. Done.)
   ```
   sudo env UV_PYTHON_INSTALL_DIR=/opt/python /home/<your-user>/.local/bin/uv python install 3.11
   /opt/python/cpython-3.11-linux-aarch64-gnu/bin/python3.11 -c "import sqlite3, venv, ensurepip; sqlite3.connect(':memory:').enable_load_extension(True); print('python ok')"
   ls -ld /opt/python        # must be readable by everyone (drwxr-xr-x)
   rm -rf /tmp/pytest311
   ```
3. **Install packages.**
   ```
   sudo apt update
   sudo apt install -y nginx sqlite3 exfatprogs unattended-upgrades
   sudo dpkg-reconfigure -plow unattended-upgrades
   ```
   (`curl` is already installed. Done on 2026-10-11, including `apt full-upgrade`; Nginx is left
   stopped and disabled until step 13.)
4. **Create the service user.**
   ```
   sudo adduser --system --group --home /srv/jifunze --no-create-home jifunze
   sudo usermod -aG jifunze www-data
   getent group jifunze          # note the number (the gid) for step 6; it is 105 on this Pi
   ```
5. **Create the directories** (all on the SD card except `backups`, which gets the SSD in step 6).
   ```
   sudo install -d -o jifunze -g jifunze -m 0755 /srv/jifunze /srv/jifunze/releases /srv/jifunze/incoming
   sudo install -d -o jifunze -g jifunze -m 0750 /srv/jifunze/data /srv/jifunze/models /srv/jifunze/backups
   sudo install -d -o root -g jifunze -m 0750 /etc/jifunze
   ```
6. **Mount the SSD (exFAT, nothing is formatted) and give the backups folder to the app.**
   Plug the SSD into the Pi. Check it before touching anything:
   ```
   lsblk -f                      # expect sda1 with FSTYPE exfat and about 1 TB
   sudo blkid /dev/sda1          # copy the UUID="XXXX-XXXX" value
   sudo mkdir -p /mnt/ssd
   sudo mount -t exfat -o ro /dev/sda1 /mnt/ssd && ls /mnt/ssd | head   # read-only look first
   sudo umount /mnt/ssd
   ```
   If you see your files, add two lines to `/etc/fstab` (`sudo nano /etc/fstab`), using your UUID,
   your user id from `id -u` (usually 1000) and the jifunze gid from step 4:
   ```
   UUID=XXXX-XXXX  /mnt/ssd  exfat  uid=1000,gid=JIFUNZE_GID,dmask=0007,fmask=0117,noatime,nofail,x-systemd.device-timeout=10  0  0
   /mnt/ssd/jifunze-backups  /srv/jifunze/backups  none  bind,nofail,x-systemd.requires-mounts-for=/mnt/ssd  0  0
   ```
   Then:
   ```
   sudo mount /mnt/ssd
   mkdir /mnt/ssd/jifunze-backups
   sudo mount /srv/jifunze/backups
   findmnt /srv/jifunze/backups       # must show the bind mount
   sudo -u jifunze touch /srv/jifunze/backups/.test && sudo -u jifunze rm /srv/jifunze/backups/.test
   ```
   Notes: an exFAT disk has no per-file permissions (the mount options above decide who can write);
   the backup units can only reach `/srv/jifunze/backups`, not your photos. **Always `sudo umount
   /srv/jifunze/backups /mnt/ssd` before unplugging**, or exFAT may be flagged dirty
   (`sudo fsck.exfat /dev/sda1` fixes that). The backup job refuses to run if the SSD is not
   mounted, so it never fills the SD card.
7. **Let the deploy user restart the one service (and clear its failed state), and nothing else.** Create
   `/etc/sudoers.d/jifunze` with `sudo visudo -f /etc/sudoers.d/jifunze`:
   ```
   jifunze ALL=(root) NOPASSWD: /usr/bin/systemctl restart jifunze.service, /usr/bin/systemctl reset-failed jifunze.service
   ```
   `reset-failed` matters after a release that crashes on start: systemd gives up after five tries and
   refuses further starts, including the rollback's, until it is cleared (`deploy/lib.sh` does it).
   (`deploy.sh` runs as `jifunze` for manual deploys. The GitHub runner uses its own user: see `docs/RUNNER_SETUP.md`.)

## B. The first release

8. **Write the environment file.** Copy `deploy/jifunze.env.example` to
   `/etc/jifunze/jifunze.env` (`sudo install -m 0640 -o root -g jifunze deploy/jifunze.env.example /etc/jifunze/jifunze.env`),
   then fill in `SESSION_SECRET` (the command is in the file), your public hostname in
   `ALLOWED_ORIGINS` and `APP_BASE_URL`, and the SMTP and `ALERT_EMAIL` lines. Leave `EMBEDDER=fake`
   for now. The defaults already match this Pi (`JIFUNZE_PYTHON`, `EMBED_MODEL=qint8`,
   `BACKUP_REQUIRE_MOUNT=1`).
9. **Build the first tarball, on your Mac** (Stage 9 will do this in CI). From the repo, on a
   clean commit:
   ```
   git archive --format=tar.gz -o jifunze-v0.1.0.tar.gz HEAD \
     app web migrations scripts deploy pyproject.toml requirements.lock
   shasum -a 256 jifunze-v0.1.0.tar.gz
   scp jifunze-v0.1.0.tar.gz <your-user>@<pi-ip>:/tmp/
   ```
   On the Pi: `sudo install -o jifunze -g jifunze /tmp/jifunze-v0.1.0.tar.gz /srv/jifunze/incoming/`
   and compare the checksum (`sha256sum`) with the one from your Mac.
10. **Prove the dependencies install on this Pi before deploying.** This is the step most likely to
    surprise us (aarch64 wheels on an older glibc). Nothing is installed system-wide:
    ```
    mkdir /tmp/boot && tar -xzf /srv/jifunze/incoming/jifunze-v0.1.0.tar.gz -C /tmp/boot deploy requirements.lock
    /opt/python/cpython-3.11-linux-aarch64-gnu/bin/python3.11 -m venv /tmp/boot/venv
    /tmp/boot/venv/bin/pip install --require-hashes --no-deps -r /tmp/boot/requirements.lock
    /tmp/boot/venv/bin/python -c "import onnxruntime, sqlite_vec, argon2, tokenizers, numpy, sqlite3; c=sqlite3.connect(':memory:'); c.enable_load_extension(True); sqlite_vec.load(c); print('imports ok', c.execute('select vec_version()').fetchone())"
    ```
    If any line fails, **stop and paste the error to me**; do not work around it.
    Afterwards `rm -rf /tmp/boot/venv`.
11. **Install the units and Nginx files** (from the tarball):
    ```
    sudo cp /tmp/boot/deploy/systemd/* /etc/systemd/system/
    sudo cp /tmp/boot/deploy/nginx/jifunze.conf /etc/nginx/conf.d/
    sudo mkdir -p /etc/nginx/snippets
    sudo cp /tmp/boot/deploy/nginx/jifunze-proxy.conf /tmp/boot/deploy/nginx/jifunze-security-headers.conf /etc/nginx/snippets/
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo systemctl daemon-reload
    sudo nginx -t
    ```
    This Pi has Nginx 1.26; the config was syntax-checked against current Nginx, so this
    `nginx -t` is the check that matters (run it as root: `sudo nginx -t`).
12. **Deploy it.** Rehearse, then do it (as `jifunze`, so file ownership is right):
    ```
    sudo -u jifunze /tmp/boot/deploy/deploy.sh --dry-run v0.1.0
    sudo -u jifunze /tmp/boot/deploy/deploy.sh v0.1.0
    ```
    Expected: nine numbered steps, "first deploy: nothing to back up", then
    "release v0.1.0 is live". If the health check fails the release stays unswitched or is rolled
    back; read `journalctl -u jifunze -n 50`.
13. **Start Nginx and enable everything.**
    ```
    sudo systemctl enable --now nginx
    sudo systemctl enable jifunze.service
    sudo systemctl enable --now jifunze-reminders.timer jifunze-backup.timer jifunze-optimize.timer
    systemctl list-timers 'jifunze-*'
    ```
14. **Create your admin account.**
    ```
    cd /srv/jifunze/current && sudo -u jifunze bash -c \
      'set -a; . /etc/jifunze/jifunze.env; set +a; PYTHONPATH=. .venv/bin/python scripts/create_user.py --username YOU --role admin'
    ```

## C. Check it works (these checks exist only on the Pi)

15. `/srv/jifunze/current/deploy/healthcheck.sh` prints `app: ok`, then power and temperature.
    Any `WARN: under-voltage` means a better power supply, before anything else (a bus-powered
    1 TB SSD makes this more likely).
16. `curl -si http://127.0.0.1:8080/healthz` returns `{"status":"ok"}` with the security headers;
    `curl -si http://127.0.0.1:8080/` returns the page with the same headers.
17. Stop the app (`sudo systemctl stop jifunze`) and load `http://127.0.0.1:8080/`: the
    maintenance page appears. Start it again.
18. Run a backup now: `sudo systemctl start jifunze-backup.service`, then
    `ls -l /srv/jifunze/backups`, and check the file is on the SSD (`ls -l /mnt/ssd/jifunze-backups`).
    Open the System status screen: "Last backup" shows the time.
19. **Prove the unplugged-SSD guard:** `sudo umount /srv/jifunze/backups`, run
    `sudo systemctl start jifunze-backup.service`; it must FAIL (and email you), not write to the
    SD card. Then `sudo mount /srv/jifunze/backups`.
20. **Test the failure alert:** `sudo systemctl start jifunze-failure@jifunze-backup.service.service`
    (the instance is the full unit name, so it ends in `.service.service`; with one `.service` the script
    prints its usage line and exits 2).
    You should get the email (setting it up with Gmail: `docs/GO_LIVE.md` section 7). If not, check `ALERT_EMAIL` and `SMTP_*` and
    `journalctl -u 'jifunze-failure@*'`.
21. **Sandbox check:** `systemd-analyze security jifunze.service` (a score; lower is tighter).
    If the app dies with `SIGSYS` or cannot read CPU info once the real model is on, loosen
    `SystemCallFilter` in `deploy/systemd/jifunze.service` and note why. This Pi has systemd 257;
    the units only use directives it supports, but `systemd-analyze verify /etc/systemd/system/jifunze*.service /etc/systemd/system/jifunze*.timer` confirms it.
22. **Memory:** `systemctl status jifunze` and `free -h` with the app idle. The limits are
    `MemoryHigh=450M` / `MemoryMax=600M`.

## D. Measure, then choose (see docs/BACKLOG.md)

23. Run `bench_argon2.py` and `bench_embed.py` (from `/srv/jifunze/current`, env file loaded as in
    step 14). Set `ARGON2_*` and `EMBEDDER` in the env file, then `sudo systemctl restart jifunze`.
    For the real model: `scripts/download_model.py`, set `EMBEDDER=onnx` (keep `EMBED_MODEL=qint8`),
    run `scripts/reindex.py`, and watch memory against `MemoryMax=600M`. If it does not fit, stay
    on `EMBEDDER=fake` (Meaning search off; everything else works) and tell me.
24. **Second copy of the backups (recommended).** The SSD is on the same Pi. To copy each backup
    to another machine, give the `jifunze` user an SSH key and set in the env file
    `BACKUP_COPY_COMMAND=scp -q "$1" USER@<other-host>:/path/for/backups/`. Ask me to walk
    through it when you are ready.

## E. When things go wrong

- **Bad deploy:** `deploy.sh` rolls back by itself if the health check fails. By hand:
  `sudo -u jifunze /srv/jifunze/current/deploy/rollback.sh`. Running it again rolls forward.
- **Restore the database from a backup** (rollback never restores data): `sudo systemctl stop jifunze`;
  `cp` the chosen `/srv/jifunze/backups/app-*.db` over `/srv/jifunze/data/app.db`; delete
  `app.db-wal` and `app.db-shm` next to it; `sudo chown jifunze:jifunze` the file;
  `sudo systemctl start jifunze`. Stage 10 adds a full restore drill.
- **SD card failing:** restore on a new card from the latest file on the SSD (or the second copy).
- **Forgot a password, or want a different one:** on the Pi, from `/srv/jifunze/current`:
  `sudo -u jifunze bash -c 'set -a; . /etc/jifunze/jifunze.env; set +a; PYTHONPATH=. .venv/bin/python scripts/reset_password.py --username NAME'`
  (needs a terminal: use `ssh -t`). It asks for the new password twice, applies
  `PASSWORD_MIN_LENGTH`, signs that account out everywhere and writes an audit entry. Locally:
  `make reset-password NAME=...`.
- **Release rule:** migrations must be backward compatible (add in one release, remove in a later
  one), so the previous code always runs on the new schema.
