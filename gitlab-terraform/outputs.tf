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
  value       = gitlab_project_mirror.github.mirror_id
}
