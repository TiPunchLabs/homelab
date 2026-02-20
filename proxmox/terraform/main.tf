resource "github_repository" "this" {
  name        = var.repository_name
  description = var.repository_description
  visibility  = var.visibility
}
