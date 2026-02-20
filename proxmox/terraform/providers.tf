terraform {
  required_version = ">= 1.11.0"
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.11.1"
    }
  }
}

provider "github" {
  token = var.github_token
  owner = var.github_owner
}
