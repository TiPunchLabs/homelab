variable "project_description" {
  description = "Project description for the VM"
  type        = string
}

variable "vm_target_node" {
  description = "Target node name"
  type        = string
  default     = "proxmox"
}

variable "vm_count" {
  description = "Number of VMs to create"
  type        = number
  default     = 1
}


variable "vm_name_prefix" {
  description = "value of the vm name"
  type        = string
  default     = "generic-vm"
}

variable "vm_baseid" {
  description = "value of the vm id"
  type        = number
}

# Le numéro de départ pour les IPs
variable "vm_ip_start" {
  description = "The starting number for the IP addresses (e.g., 20)"
  type        = number
}


variable "vm_template_id" {
  description = "id of the vm template"
  type        = number
}


variable "vm_memory" {
  description = "value of the vm memory size (in MiB)"
  type        = number
  default     = 2048
}

variable "vm_cpu_cores" {
  description = "Number of CPU cores"
  type        = number
  default     = 1
}

variable "vm_netmask" {
  description = "The subnet mask for the VM"
  type        = string
  default     = "24"
}

variable "vm_gateway" {
  description = "The default gateway for the VM"
  type        = string
  default     = "192.168.10.1"
}

variable "vm_disk0_size" {
  description = "Size of the primary disk, in GiB (number, e.g. 30)"
  type        = number
}

variable "vm_disk0_storage" {
  description = "Name of the storage for the primary disk"
  type        = string
  default     = "local-lvm"
}

variable "vm_dns_domain" {
  description = "DNS domain for the VM"
  type        = string
  default     = "local"
}

variable "vm_dns_servers" {
  description = "List of DNS servers for the VM"
  type        = list(string)
  default     = ["1.1.1.1", "8.8.8.8"]
}

variable "vm_started" {
  description = "Whether the VM should be started (true) or stopped (false)"
  type        = bool
  default     = true
}

variable "vm_ssh_user" {
  description = "Cloud-init SSH user account name"
  type        = string
  default     = "ansible"
}

variable "vm_ssh_keys" {
  description = "List of SSH public keys for cloud-init user"
  type        = list(string)
}

# -----------------------------------------------------------------------------
# Options avancees. Chaque defaut reproduit le comportement anterieur du module :
# ne rien fournir laisse la VM strictement identique a ce qu'elle etait.
# -----------------------------------------------------------------------------

variable "vm_memory_floating" {
  description = "Minimum memory in MiB when ballooning is enabled (0 = ballooning disabled)"
  type        = number
  default     = 0
}

variable "vm_disk0_discard" {
  description = "Pass discard/TRIM requests to the underlying storage ('on' or 'ignore')"
  type        = string
  default     = "ignore"
}

variable "vm_disk0_ssd" {
  description = "Expose the primary disk to the guest as an SSD"
  type        = bool
  default     = false
}

variable "vm_disk0_iothread" {
  description = "Use a dedicated iothread for the primary disk. Proxmox n'applique ce flag qu'avec un controleur virtio-scsi-single : positionner aussi vm_scsi_hardware"
  type        = bool
  default     = false
}

variable "vm_scsi_hardware" {
  description = "SCSI controller model (e.g. 'virtio-scsi-single'). null conserve celui herite du template"
  type        = string
  default     = null
}

variable "vm_on_boot" {
  description = "Start the VM automatically when the Proxmox node boots. null conserve le defaut du provider"
  type        = bool
  default     = null
}

variable "vm_startup" {
  description = "Startup order and delays on node boot. null laisse la VM hors de la sequence de demarrage"
  type = object({
    order      = number
    up_delay   = number
    down_delay = number
  })
  default = null
}

variable "vm_network_devices" {
  description = "Network interfaces to manage explicitly. Liste vide = interfaces heritees du clone (comportement anterieur)"
  type = list(object({
    bridge   = string
    model    = optional(string, "virtio")
    firewall = optional(bool, false)
  }))
  default = []
}
