output "tunnel_id" {
  description = "Goes in cloudflared_tunnel_id (infra/ansible/group_vars/all.yml)."
  value       = cloudflare_zero_trust_tunnel_cloudflared.jifunze.id
}

output "access_aud" {
  description = "Goes in CF_ACCESS_AUD (cf_access_aud in group_vars/all.yml)."
  value       = cloudflare_zero_trust_access_application.app.aud
}

output "credentials_json" {
  description = "Put this in secrets.sops.yaml as cloudflared_credentials_json. Also stored in the state file."
  sensitive   = true
  value = jsonencode({
    AccountTag   = var.account_id
    TunnelID     = cloudflare_zero_trust_tunnel_cloudflared.jifunze.id
    TunnelSecret = random_id.tunnel_secret.b64_std
  })
}
