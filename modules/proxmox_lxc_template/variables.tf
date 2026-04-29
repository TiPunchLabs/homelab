variable "project_description" {
  description = "Project description for the container"
  type        = string
}

variable "ct_target_node" {
  description = "Target Proxmox node name"
  type        = string
  default     = "proxmox"
}

variable "ct_count" {
  description = "Number of containers to create"
  type        = number
  default     = 1
}

variable "ct_name_prefix" {
  description = "Name prefix for containers"
  type        = string
  default     = "generic-ct"
}

variable "ct_baseid" {
  description = "Starting CTID"
  type        = number
}

variable "ct_ip_start" {
  description = "Last IP octet start (e.g., 70)"
  type        = number
}

variable "ct_template_file_id" {
  description = "LXC template file ID (e.g. local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst)"
  type        = string
}

variable "ct_os_type" {
  description = "OS type for Proxmox"
  type        = string
  default     = "ubuntu"
}

variable "ct_cpu_cores" {
  description = "Number of CPU cores"
  type        = number
  default     = 1
}

variable "ct_memory" {
  description = "RAM in MiB"
  type        = number
  default     = 512
}

variable "ct_disk_size" {
  description = "Rootfs size in GB"
  type        = number
  default     = 8
}

variable "ct_disk_storage" {
  description = "Datastore for rootfs"
  type        = string
  default     = "local-lvm"
}

variable "ct_ssh_keys" {
  description = "SSH public keys for root (copied to ansible user)"
  type        = list(string)
}

variable "ct_root_password" {
  description = "Root password for the container (from Vault)"
  type        = string
  sensitive   = true
}

variable "ct_unprivileged" {
  description = "Run as unprivileged container"
  type        = bool
  default     = true
}

variable "ct_nesting" {
  description = "Enable nesting feature"
  type        = bool
  default     = true
}

variable "ct_started" {
  description = "Start container after creation"
  type        = bool
  default     = true
}

variable "ct_start_on_boot" {
  description = "Start container on Proxmox boot"
  type        = bool
  default     = true
}

variable "ct_gateway" {
  description = "Default gateway"
  type        = string
  default     = "192.168.10.1"
}

variable "ct_netmask" {
  description = "Subnet mask"
  type        = string
  default     = "24"
}

variable "ct_dns_domain" {
  description = "DNS domain"
  type        = string
  default     = "local"
}

variable "ct_dns_servers" {
  description = "DNS servers"
  type        = list(string)
  default     = ["1.1.1.1", "8.8.8.8"]
}

variable "ct_ssh_private_key_path" {
  description = "Path to SSH private key for remote-exec provisioner"
  type        = string
}
