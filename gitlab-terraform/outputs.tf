output "project_url" {
  description = "GitLab project URL"
  value       = gitlab_project.project.web_url
}

output "project_id" {
  description = "GitLab project ID"
  value       = gitlab_project.project.id
}

output "mirror_id" {
  description = "GitLab push mirror ID"
  value       = gitlab_project_push_mirror.github.mirror_id
}

output "homelab_runner_id" {
  description = "ID of the homelab project runner"
  value       = gitlab_user_runner.homelab.id
}

output "homelab_runner_token" {
  description = "Authentication token (glrt-) of the homelab runner, for the dockhost vault"
  value       = gitlab_user_runner.homelab.token
  sensitive   = true
}
