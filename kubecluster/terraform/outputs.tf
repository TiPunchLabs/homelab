output "control_plane" {
  description = "Control Plane nodes"
  value = {
    names = module.kubecluster_control_plane.vm_names
    ips   = module.kubecluster_control_plane.vm_ips_output
    ids   = module.kubecluster_control_plane.vm_ids
  }
}

output "workers" {
  description = "Worker nodes"
  value = {
    names = module.kubecluster_workers.vm_names
    ips   = module.kubecluster_workers.vm_ips_output
    ids   = module.kubecluster_workers.vm_ids
  }
}

output "cluster_summary" {
  description = "Cluster summary"
  value       = <<-EOT

    KubeCluster Cluster:
    ─────────────────────────────────────────
    Control Plane: ${join(", ", module.kubecluster_control_plane.vm_names)} (${join(", ", module.kubecluster_control_plane.vm_ips_output)})
    Workers:       ${join(", ", module.kubecluster_workers.vm_names)} (${join(", ", module.kubecluster_workers.vm_ips_output)})
    ─────────────────────────────────────────
  EOT
}
