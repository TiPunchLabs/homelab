terraform {
  required_version = ">= 1.11.0"

  # GitLab-managed state of project tipunchlabs/homelab (id 80082616), state "dockhost".
  # Credentials come from TF_HTTP_USERNAME / TF_HTTP_PASSWORD, never from this file.
  backend "http" {
    address        = "https://gitlab.com/api/v4/projects/80082616/terraform/state/dockhost"
    lock_address   = "https://gitlab.com/api/v4/projects/80082616/terraform/state/dockhost/lock"
    unlock_address = "https://gitlab.com/api/v4/projects/80082616/terraform/state/dockhost/lock"
    lock_method    = "POST"
    unlock_method  = "DELETE"
    retry_wait_min = 5
  }
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.96.0"
    }
  }
}

provider "proxmox" {
  endpoint  = var.pm_api_url
  api_token = "${var.pm_api_token_id}=${var.pm_api_token_secret}"
  insecure  = true
}
