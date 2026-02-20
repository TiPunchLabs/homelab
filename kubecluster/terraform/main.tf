terraform {
  required_version = ">= 1.11.0"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.93.0"
    }
  }
}

provider "proxmox" {
  endpoint  = var.pm_api_url
  api_token = "${var.pm_api_token_id}=${var.pm_api_token_secret}"
  insecure  = true
}

# =============================================================================
# Control Plane Node (1 VM)
# - Plus de ressources pour etcd, kube-apiserver, scheduler, controller-manager
# =============================================================================
module "kubecluster_control_plane" {

  source = "../../modules/proxmox_vm_template"

  providers = {
    proxmox = proxmox
  }

  vm_count            = 1
  vm_template_id      = 9001
  vm_disk0_size       = 35
  vm_cpu_cores        = 2
  vm_memory           = 4096
  vm_name_prefix      = "kubecluster"
  vm_baseid           = 9040
  vm_ip_start         = 40
  vm_started          = var.vm_started
  project_description = "KubeCluster Control Plane Node"

}

# =============================================================================
# Worker Nodes (2 VMs)
# - Configuration optimisée pour workloads applicatifs
# =============================================================================
module "kubecluster_workers" {

  source = "../../modules/proxmox_vm_template"

  providers = {
    proxmox = proxmox
  }

  vm_count            = 2
  vm_template_id      = 9001
  vm_disk0_size       = 30
  vm_cpu_cores        = 1
  vm_memory           = 3584
  vm_name_prefix      = "kubecluster"
  vm_baseid           = 9041
  vm_ip_start         = 41
  vm_started          = var.vm_started
  project_description = "KubeCluster Worker Node"

}
