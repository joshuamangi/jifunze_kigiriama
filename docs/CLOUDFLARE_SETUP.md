# Cloudflare Tunnel and Access: the steps only you can do

The app reaches the internet through an outbound Cloudflare Tunnel (no port is opened on your router),
and Cloudflare Access puts an email allow-list in front of it. The app can additionally verify the
Access token itself (`CF_ACCESS_*`, `app/access.py`), so a request that goes around Access is refused.
Written, **not yet run**; menu names in Cloudflare's dashboard move around, so look for the words
rather than the exact path. You need a domain whose DNS is on Cloudflare.

Two ways to create the Cloudflare side. Pick one; the Pi side is the same.

- **A. By hand (below)** : six commands and a few clicks.
- **B. Terraform** (`infra/terraform/`, optional): creates the tunnel, DNS record, Access application
  and allow-list policy. See "Option B" at the end.

## A. By hand, on your Mac

1. **Install and log in.** `brew install cloudflared`, then `cloudflared tunnel login`. A browser
   opens; choose your domain. This writes `~/.cloudflared/cert.pem`, which can manage your zone:
   treat it as a secret and delete it when you are done.
2. **Create the tunnel and note its id.**
   ```
   cloudflared tunnel create jifunze      # prints the tunnel id (a UUID) and writes ~/.cloudflared/<id>.json
   ```
   `<id>.json` is the tunnel's credential. It goes into the encrypted secrets file in step 4 and
   nowhere else. It must never be committed (`.gitignore` blocks it).
3. **Point the hostname at the tunnel.**
   ```
   cloudflared tunnel route dns jifunze jifunze.example.com
   ```
4. **Store the credential encrypted.** In `infra/ansible/`, with `sops secrets.sops.yaml` (see its
   README), paste the file's whole contents as the value of `cloudflared_credentials_json`. Then
   delete `~/.cloudflared/<id>.json` and `cert.pem` from your Mac if you do not need them.
5. **Create the Access application.** In the Cloudflare dashboard open Zero Trust, then Access, then
   Applications, and add a **Self-hosted** application:
   - Domain: your hostname (for example `jifunze.example.com`).
   - Session duration: 24 hours is a reasonable start.
   - Policy: action **Allow**, rule **Emails** with exactly the addresses of your small group.
     Nothing else (no "everyone", no email-domain rule unless you mean it).
   - Login method: One-time PIN by email is enough for a trusted group.
6. **Note two values for the app.** The application's **Audience (AUD) tag** (on its overview page),
   and your **team domain** (`<team>.cloudflareaccess.com`, in Zero Trust settings). They are not
   secret, but they are specific to you.

## On the Pi side (through Ansible)

In `infra/ansible/group_vars/all.yml` set:
```
cloudflared_enabled: true
cloudflared_tunnel_id: "<the UUID from step 2>"
cloudflared_version: "<a released version>"
cloudflared_deb_sha256: "<sha256 of cloudflared-linux-arm64.deb for that version>"
cf_access_enabled: true
cf_access_team_domain: "<team>.cloudflareaccess.com"
cf_access_aud: "<AUD tag from step 6>"
```
Look the version up on <https://github.com/cloudflare/cloudflared/releases> and take the checksum
from that release's notes (compare it with `shasum -a 256` of the file you downloaded). Do not guess
either value; the playbook refuses to run with an empty or malformed checksum.

Turn on `cf_access_enabled` **last**, after you have seen the site through the tunnel working: with it on,
the app answers 403 to any request without a valid Access token, so a wrong team domain or AUD locks
everyone out (fix: set it back to `false` and run the `app` role again). `/healthz` stays open for
the local health check. Nginx serves the static files in `web/` itself; those are protected by
Access at Cloudflare's edge, not by the app check.

Then `ansible-playbook site.yml --check --diff`, apply, and run the checks in `docs/GO_LIVE.md`.
Also set `ALLOWED_ORIGINS` (done for you: the env file uses `https://<jifunze_hostname>`).

## Manual deployment of the tunnel without Ansible

Copy `deploy/cloudflared/config.yml.j2` to `/etc/cloudflared/config.yml` with the two variables
filled in, the credentials JSON next to it (`root:cloudflared`, mode 0640), `cloudflared.service` to
`/etc/systemd/system/`, create the `cloudflared` system user, `sudo systemctl enable --now cloudflared`.

## Option B: Terraform

```
cd infra/terraform
export CLOUDFLARE_API_TOKEN=...       # a scoped token: edit tunnels, Access apps and policies (account),
                                      # and DNS (your zone only). The provider docs list the exact names.
cp terraform.tfvars.example terraform.tfvars   # git-ignored; fill in account_id, zone_id, hostname, emails
terraform init && terraform plan
terraform apply
terraform output tunnel_id
terraform output access_aud
terraform output -raw credentials_json   # paste into secrets.sops.yaml, then do not keep it anywhere else
```
The state file holds the tunnel secret. Keep it out of git (`.gitignore` covers `*.tfstate*`), on an
encrypted disk. Validated here with `terraform validate` against provider v5.27, never applied.

## Troubleshooting

- `journalctl -u cloudflared -n 50` on the Pi. "connection refused" to 127.0.0.1:8080 means Nginx is down.
- 502 from Cloudflare with the tunnel up: the app is down (`systemctl status jifunze`).
- Everyone gets 403 and the page says "access required": `cf_access_*` values are wrong, see above.
- Test the path from outside your network (phone on mobile data) before telling anyone.
