# GitLab Provider Documentation:
# https://registry.terraform.io/providers/gitlabhq/gitlab/latest

terraform {
  required_version = ">= 1.11.0"
  required_providers {
    gitlab = {
      source  = "gitlabhq/gitlab"
      version = "~> 18.0"
    }
  }
}

provider "gitlab" {
  token = var.gitlab_token
}
