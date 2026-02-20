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
# Branch Protection - Require CI to pass before merge
# =============================================================================
resource "github_branch_protection" "main" {
  repository_id = github_repository.repo.node_id
  pattern       = "main"

  required_status_checks {
    strict   = true
    contexts = ["Ansible Lint", "Terraform Lint", "Shell Lint", "Security Check"]
  }

  required_pull_request_reviews {
    dismiss_stale_reviews           = true
    required_approving_review_count = 0
  }

  enforce_admins = false
}
