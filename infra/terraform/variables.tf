variable "account_id" {
  description = "Cloudflare account id (dashboard sidebar, or `cloudflared tunnel list`)."
  type        = string
}

variable "zone_id" {
  description = "Zone id of the domain that holds the hostname."
  type        = string
}

variable "hostname" {
  description = "Public hostname for the app, e.g. jifunze.example.com."
  type        = string
}

variable "allowed_emails" {
  description = "Email addresses that may pass Cloudflare Access. Everyone else is refused."
  type        = list(string)

  validation {
    condition     = length(var.allowed_emails) > 0
    error_message = "allowed_emails must list at least one address, or nobody could get in."
  }
}

variable "tunnel_name" {
  description = "Name of the tunnel as shown in the Zero Trust dashboard."
  type        = string
  default     = "jifunze"
}

variable "session_duration" {
  description = "How long an Access login lasts before the email check is asked again."
  type        = string
  default     = "24h"
}
