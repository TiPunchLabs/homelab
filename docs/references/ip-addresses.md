# IP address reference

## Main network (192.168.1.0/24)

### Physical equipment

| Equipment | IP | Description |
|------------|-----|-------------|
| **Proxmox VE** | 192.168.1.100 | Main hypervisor |
| **NAS Synology** | 192.168.1.93 | Network storage |
| **Gateway** | 192.168.1.254 | Router/Gateway |

### Proxmox VMs

| VM | VMID | IP | Usage |
|----|------|-----|-------|
| bastion-60 | 9060 | 192.168.1.60 | Bastion (GitLab Runner shell, Terraform, Ansible) |
| dockhost-50 | 9050 | 192.168.1.50 | Docker services (Portainer, GitLab Runner) |
| kubecluster-40 | 9040 | 192.168.1.40 | K8s Control Plane |
| kubecluster-41 | 9041 | 192.168.1.41 | K8s Worker |
| kubecluster-42 | 9042 | 192.168.1.42 | K8s Worker |

### Important ports

| Service | Port | Protocol |
|---------|------|-----------|
| SSH | 22 | TCP |
| HTTP | 80 | TCP |
| HTTPS | 443 | TCP |
| Proxmox Web | 8006 | TCP/HTTPS |
| Synology DSM | 5000 | TCP/HTTP |
| Portainer Agent | 9001 | TCP |

---

## Vagrant/libvirt network (192.168.122.0/24)

### Local Kubernetes cluster

| VM | IP | Role |
|----|-----|------|
| k8s-controlplan | 192.168.122.70 | Control Plane |
| k8s-node1 | 192.168.122.71 | Worker |
| k8s-node2 | 192.168.122.72 | Worker |

### Exposed NodePorts

| Service | NodePort | Access |
|---------|----------|-------|
| Traefik | 30928 | http://192.168.122.71:30928 |
| Prometheus | 30928 | Via Host header |
| Grafana | 30928 | Via Host header |
| AlertManager | 30928 | Via Host header |

---

## VM addressing plan

Convention: `192.168.1.{vm_ip_start}` where `vm_ip_start` is defined in Terraform.

```
.40-.49  : kubecluster cluster (Kubernetes)
.50-.59  : dockhost cluster (Docker services)
.60-.69  : Bastion (control plane)
```

---

## VM ID / IP mapping

The convention uses the following scheme:
- VM ID: `90XX`
- IP: `192.168.1.XX`

| ID range | IP range | Usage |
|----------|----------|-------|
| 9040-9049 | .40-.49 | kubecluster |
| 9050-9059 | .50-.59 | dockhost |
| 9060-9069 | .60-.69 | bastion |

---

## SSH configuration

SSH aliases are configured in `~/.ssh/config`:

| Alias | IP | User | Key |
|-------|-----|------|-----|
| `pve` | 192.168.1.100 | ansible | `~/.ssh/proxmox` |
| `bastion-60` | 192.168.1.60 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `dockhost-50` | 192.168.1.50 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `kubecluster-40` | 192.168.1.40 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `kubecluster-41` | 192.168.1.41 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `kubecluster-42` | 192.168.1.42 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `nas` | 192.168.1.93 | xgueret | `~/.ssh/id_nas` |
