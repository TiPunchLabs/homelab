resource "gitlab_project" "project" {
  name         = var.project_name
  namespace_id = var.gitlab_namespace_id
  description  = var.project_description

  visibility_level = var.visibility_level

  issues_access_level = "enabled"
  wiki_access_level   = "enabled"

  topics = ["homelab", "proxmox", "terraform", "ansible", "docker", "kubernetes", "infrastructure-as-code"]
}

# =============================================================================
# Branch Protection - Require CI to pass before merge
# =============================================================================
# =============================================================================
# Push Mirror - GitLab -> GitHub (read-only)
# =============================================================================
resource "gitlab_project_push_mirror" "github" {
  project                 = gitlab_project.project.id
  url                     = "https://${var.github_mirror_owner}:${var.github_mirror_token}@github.com/${var.github_mirror_owner}/${var.project_name}.git"
  keep_divergent_refs     = false
  only_protected_branches = true
}

# Provider 19.0 renamed gitlab_project_mirror to gitlab_project_push_mirror
# (identical resource). The state is moved on the next apply, no recreation.
moved {
  from = gitlab_project_mirror.github
  to   = gitlab_project_push_mirror.github
}

# =============================================================================
# Branch Protection - Require CI to pass before merge
# =============================================================================
resource "gitlab_branch_protection" "main" {
  project          = gitlab_project.project.id
  branch           = "main"
  allow_force_push = false

  # Provider 19 treats gitlab.com as EE (/version: enterprise=true) and rejects
  # push_access_level/merge_access_level there: use the allowed_to_* lists.
  allowed_to_push = [
    { access_level = "maintainer" },
  ]
  allowed_to_merge = [
    { access_level = "maintainer" },
  ]
}
