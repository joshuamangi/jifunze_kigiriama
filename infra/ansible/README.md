# Ansible: rebuild the Pi from git

`site.yml` sets up the machine described in `docs/PI_SETUP.md` (Debian 13, 2 GB, database on the SD
card, backups on the exFAT SSD, Python 3.11 in `/opt/python`). It is idempotent: running it twice
changes nothing the second time. **Written and validated on the Mac only** (`--syntax-check`,
`ansible-lint --profile production`, template rendering). It has not been run against the Pi: do the
`--check` run below first and read the diff.

## What it does, and does not do

| Role (tag) | What |
| --- | --- |
| `base` | packages, unattended security updates, journald 100M cap, Python 3.11 via `uv` |
| `user` | `jifunze` user and group, `/srv/jifunze/*` directories, `/etc/jifunze`, the one-command sudoers rule |
| `ssd` | mounts the SSD by UUID (`noatime`), bind-mounts `jifunze-backups` into `/srv/jifunze/backups` |
| `runner` | `gh`, the `ghrunner` user, its one-command sudoers rule |
| `nginx` | the Stage 8 site and snippets, default site removed, `nginx -t` before any reload |
| `app` | the Stage 8 units and timers, `/etc/jifunze/jifunze.env` from variables and secrets |
| `cloudflared` | pinned arm64 `.deb` (checksum verified), tunnel user, config, credentials, unit |
| `ssh` | key-only SSH for one user, refused if that user has no key |
| `firewall` | nftables, drop all inbound except loopback, replies, ICMP and SSH from your addresses |

It never: formats or erases the SSD, deploys application code (that is `deploy.sh` / GitHub Actions),
registers the GitHub runner (needs a token: `docs/RUNNER_SETUP.md`), logs in to Cloudflare, or
creates user accounts. SSH and the firewall run last so a failure earlier cannot lock you out.

## One-time setup on your Mac

```
brew install ansible sops age
cd infra/ansible
ansible-galaxy collection install -r requirements.yml -p collections
cp inventory/hosts.example.yml inventory/hosts.yml     # fill in the Pi's address and your login
```
Then edit `group_vars/all.yml`: set every value marked REQUIRED (`ssh_admin_user`,
`ssh_allowed_cidrs`, `ssd_uuid`, `allowed_origins`, `app_base_url`). `ssh_allowed_cidrs` is IPv4 only; SSH over IPv6
is blocked.

## Secrets: sops + age

The secrets file holds the session secret, the SMTP password and the Cloudflare tunnel credentials.
Only the **encrypted** file is committed (`tests/test_infra.py` fails if a plaintext one appears).

1. Make a key pair. **The private key never goes in git, a chat, or this folder.**
   ```
   mkdir -p ~/.config/sops/age
   age-keygen -o ~/.config/sops/age/keys.txt        # prints "Public key: age1..."
   chmod 600 ~/.config/sops/age/keys.txt
   ```
   Keep a copy of `keys.txt` in your password manager. **If you lose it the secrets file cannot be
   opened**; you would regenerate the values (new session secret signs everyone out; recreate the
   tunnel credentials).
2. Put the public key (`age1...`) in `.sops.yaml`, replacing the placeholder.
3. Create and encrypt the file:
   ```
   cp secrets.example.yaml secrets.sops.yaml
   $EDITOR secrets.sops.yaml                        # real values
   sops --encrypt --in-place secrets.sops.yaml
   ```
   Edit later with `sops secrets.sops.yaml`. Encrypting needs only the public key, but decrypting
   (and Ansible, through `community.sops`) must be told where the private key is. **On macOS sops
   does not look in `~/.config`** (its default there is `~/Library/Application Support/sops/age/`),
   so set this once and keep it:
   ```
   echo 'export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"' >> ~/.zshrc && source ~/.zshrc
   ```
   Without it, `sops --decrypt` fails with "identity did not match any of the recipients".

## Run it

```
ansible-playbook site.yml --syntax-check
ansible-playbook site.yml --check --diff          # changes nothing; read every difference
ansible-playbook site.yml                          # apply
ansible-playbook site.yml --tags nginx,app         # just some roles
```
Keep a second SSH session open the first time the `ssh` and `firewall` roles run.
`--check` is a good preview but not exact on a brand-new machine: a step that depends on an earlier
step's result (a package that is not installed yet) can only be predicted, not proven.

## ansible-pull (optional)

The Pi pulls this repo and applies it to itself. Needs `ansible`, `git` and `sops` on the Pi, the age
private key at `/root/.config/sops/age/keys.txt` (mode 600), and a read-only deploy key for the
repository (it is private). Not run yet.
```
sudo ansible-pull -U git@github.com:joshuamangi/jifunze_kigiriama.git -C main \
  -i localhost, -c local -e jifunze_hosts=localhost infra/ansible/site.yml
```
Prefer pushing from the Mac: with pull, anyone who can push to `main` can change the machine, and
the age key then lives on it. The sops binary is not in Debian's repositories; download a release
and verify its checksum, the way `docs/PI_SETUP.md` does for `uv`.
