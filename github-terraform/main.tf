resource "github_repository" "repo" {
  name        = var.repository_name
  description = var.repository_description
  visibility  = var.visibility

  has_issues   = true
  has_projects = true
  has_wiki     = true

  topics = ["homelab", "proxmox", "terraform", "ansible", "docker", "kubernetes", "infrastructure-as-code"]
}

# =============================================================================
# Branch Protection - Minimal (read-only mirror, allow force push for GitLab mirror)
# =============================================================================
resource "github_branch_protection" "main" {
  repository_id       = github_repository.repo.node_id
  pattern             = "main"
  enforce_admins      = false
  allows_force_pushes = true
}
