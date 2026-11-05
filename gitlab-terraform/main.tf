resource "gitlab_project" "project" {
  name         = var.project_name
  namespace_id = var.gitlab_namespace_id
  description  = var.project_description

  visibility_level = var.visibility_level

  issues_access_level = "enabled"
  wiki_access_level   = "enabled"

  # A red pipeline (e.g. Renovate !59) must not be mergeable.
  only_allow_merge_if_pipeline_succeeds = true

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

# =============================================================================
# Homelab runner - fallback for the GitLab.com compute quota (dockhost-90)
# =============================================================================
# Tagged only: it never picks untagged jobs, so GitLab.com stays the default.
# Jobs reach it through RUNNER_ROUTE=homelab, a project CI/CD variable written
# by runner-quota on dockhost. That variable is operational state and is
# deliberately NOT managed here (it changes every month).
resource "gitlab_user_runner" "homelab" {
  runner_type     = "project_type"
  project_id      = gitlab_project.project.id
  description     = "homelab-dockhost-90 (docker executor, quota fallback)"
  tag_list        = ["homelab-dockhost"]
  untagged        = false
  locked          = true
  access_level    = "not_protected"
  maximum_timeout = 3600
}
