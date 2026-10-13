# The tunnel is locally managed: its ingress rules stay in git (deploy/cloudflared/config.yml.j2)
# and cloudflared on the Pi reads them from /etc/cloudflared/config.yml.
resource "random_id" "tunnel_secret" {
  byte_length = 32
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "jifunze" {
  account_id    = var.account_id
  name          = var.tunnel_name
  config_src    = "local"
  tunnel_secret = random_id.tunnel_secret.b64_std
}

# hostname -> tunnel. Proxied, so visitors reach Cloudflare (and Access) first.
resource "cloudflare_dns_record" "app" {
  zone_id = var.zone_id
  name    = var.hostname
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.jifunze.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1 # 1 = automatic
  comment = "Jifunze Kigiriama tunnel (managed by Terraform)"
}

resource "cloudflare_zero_trust_access_policy" "allow_listed_emails" {
  account_id = var.account_id
  name       = "Jifunze: allow-listed emails"
  decision   = "allow"
  include = [
    for address in var.allowed_emails : {
      email = { email = address }
    }
  ]
}

resource "cloudflare_zero_trust_access_application" "app" {
  account_id       = var.account_id
  name             = "Jifunze Kigiriama"
  type             = "self_hosted"
  domain           = var.hostname
  session_duration = var.session_duration

  policies = [{
    id         = cloudflare_zero_trust_access_policy.allow_listed_emails.id
    precedence = 1
  }]
}
