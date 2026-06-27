# OVH Provider Documentation:
# https://registry.terraform.io/providers/ovh/ovh/latest

terraform {
  required_version = ">= 1.11.0"
  required_providers {
    ovh = {
      source  = "ovh/ovh"
      version = "~> 2.0"
    }
  }
}

provider "ovh" {
  endpoint           = var.ovh_endpoint
  application_key    = var.ovh_application_key
  application_secret = var.ovh_application_secret
  consumer_key       = var.ovh_consumer_key
}
