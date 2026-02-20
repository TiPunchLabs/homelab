output "repository_url" {
  description = "URL du depot GitHub"
  value       = local.repo_exists ? data.github_repository.existing_repo.html_url : github_repository.repo.html_url
}
