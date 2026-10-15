# Self-hosted GitHub runner on the Pi (Stage 9)

The runner is what lets `deploy.yml` run `deploy.sh` on the Pi. It makes an outbound connection to
GitHub, so nothing new is opened to the internet. Written here, **not yet run on the Pi**: work
through it on the Pi in order and tell me where it differs.

## What the runner may do

- Run as its own user, `ghrunner`: no password, no shell login, not in the `sudo` group.
- Write to `/srv/jifunze/releases`, `incoming`, `data` and `backups` through the `jifunze` group
  (deploy.sh unpacks releases, backs up and migrates the database as this user).
- `sudo` for exactly one command: `systemctl restart jifunze.service`.
- Run **only** the `deploy` job. CI runs on GitHub's hosted runners, never here.

**The repository is public, so a self-hosted runner is only safe if no untrusted code can reach it.** `deploy.yml` is triggered only by a published release or a manual run (both need write access), never by a pull request, and must stay that way. Also set Settings -> Actions -> General -> Fork pull request workflows to "Require approval for all external contributors".

Anyone who can run a workflow on this runner can run code as `ghrunner`, and so can change the live
database. That is why the repository is private, the job needs `production` approval, and
`deploy.yml` has no pull request trigger.

## Install

1. Needs `gh` (the workflow downloads the release with it) and `sha256sum` (already there):
   ```
   sudo apt install -y gh
   ```
2. Create the user and give it the group:
   ```
   sudo adduser --system --group --home /home/ghrunner --shell /bin/bash ghrunner
   sudo usermod -aG jifunze ghrunner
   ```
3. Let the group write where deploy.sh writes (the `jifunze` user keeps ownership; new files stay in
   the `jifunze` group because of the setgid bit):
   ```
   sudo chmod 2775 /srv/jifunze
   cd /srv/jifunze
   sudo chmod 2775 releases incoming
   sudo chmod 2770 data backups
   sudo chmod g+rw data/* 2>/dev/null || true
   ```
   The base directory itself needs it too: `deploy.sh` creates the `current` symlink and the
   `previous` file there. Without it the first deploy dies at step 5/9 with
   `ln: failed to create symbolic link '/srv/jifunze/current.new.NNN': Permission denied`.
   Releases made by hand before the runner existed belong to `jifunze` and are not group-writable;
   if you want the runner to be able to prune them later:
   `sudo chmod -R g+w /srv/jifunze/releases/<old-release>`.
   The environment file (`/etc/jifunze/jifunze.env`, `root:jifunze`) is already group-readable.
   If `backups` is the exFAT mount, group write comes from the `uid=`/`gid=`/`umask=` options in
   `/etc/fstab` (PI_SETUP step 6), not from `chmod`; check `sudo -u ghrunner touch backups/.t`.
4. The sudo rule, replacing the one for `jifunze` from PI_SETUP step 7 only if you want the
   service user to lose it (the app itself never calls sudo):
   ```
   sudo visudo -f /etc/sudoers.d/jifunze-runner
   ghrunner ALL=(root) NOPASSWD: /usr/bin/systemctl restart jifunze.service
   ```
   `deploy/rollback.sh` uses the same single command.
5. Register the runner. In GitHub: repository **Settings -> Actions -> Runners -> New self-hosted
   runner**, Linux, ARM64. Copy the download and `config.sh` commands it shows, and run them as
   `ghrunner` (`sudo -iu ghrunner`) in `/home/ghrunner/actions-runner`. When `config.sh` asks:
   - labels: leave the defaults (`self-hosted`, `Linux`, `ARM64`); the workflow matches those
   - name: any label you like, e.g. `jifunze-pi`
   - work folder: default `_work`
6. Install it as a service that runs as `ghrunner` (not as root):
   ```
   cd /home/ghrunner/actions-runner
   sudo ./svc.sh install ghrunner
   sudo ./svc.sh start
   sudo ./svc.sh status
   ```
   The service should get `UMask=0002` so releases are group-writable and readable by `jifunze`:
   `sudo systemctl edit actions.runner.*.service` and add `[Service]` / `UMask=0002`, then
   `sudo ./svc.sh stop && sudo ./svc.sh start`.
7. Python: `deploy.sh` reads `JIFUNZE_PYTHON` from `/etc/jifunze/jifunze.env`, so the runner needs
   no Python of its own.

## Check it

- GitHub shows the runner **Idle** under Settings -> Actions -> Runners.
- `sudo -u ghrunner sudo -n systemctl restart jifunze.service` works; the same with
  `systemctl stop jifunze.service` or `sudo -n true` asks for a password and fails.
- `sudo -u ghrunner id` lists the `jifunze` group but not `sudo`.
- The runner can write everywhere `deploy.sh` writes (each line must print nothing and succeed):
  `for d in . releases incoming data backups; do sudo -u ghrunner sh -c "touch /srv/jifunze/$d/.t && rm /srv/jifunze/$d/.t" || echo "ghrunner cannot write /srv/jifunze/$d"; done`
- Memory: the runner idles at roughly 100 MB and the Pi has 2 GB. Watch `free -m` during the first
  real deploy; if it is tight, stop the runner between deploys (`sudo ./svc.sh stop`).

## Remove it

```
cd /home/ghrunner/actions-runner
sudo ./svc.sh stop && sudo ./svc.sh uninstall
sudo -u ghrunner ./config.sh remove --token <token from Settings -> Actions -> Runners -> remove>
sudo rm /etc/sudoers.d/jifunze-runner
sudo deluser ghrunner && sudo rm -rf /home/ghrunner
```
Then delete the runner in GitHub if it still appears. Releases and data under `/srv/jifunze` are
untouched.
