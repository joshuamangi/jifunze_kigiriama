terraform {
  required_version = ">= 1.6"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.27"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

# The API token comes from the environment, never from a file in git:
#   export CLOUDFLARE_API_TOKEN=...   (see docs/CLOUDFLARE_SETUP.md for the permissions it needs)
provider "cloudflare" {}
