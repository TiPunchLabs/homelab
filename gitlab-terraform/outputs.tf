output "project_url" {
  description = "GitLab project URL"
  value       = gitlab_project.project.web_url
}

output "project_id" {
  description = "GitLab project ID"
  value       = gitlab_project.project.id
}
