# Reference des adresses IP

## Reseau principal (192.168.1.0/24)

### Equipements physiques

| Equipement | IP | Description |
|------------|-----|-------------|
| **Proxmox VE** | 192.168.1.26 | Hyperviseur principal |
| **NAS Synology** | 192.168.1.93 | Stockage reseau |
| **Gateway** | 192.168.1.254 | Routeur/Gateway |

### VMs Proxmox

| VM | VMID | IP | Usage |
|----|------|-----|-------|
| bastion-60 | 9060 | 192.168.1.60 | Bastion (GitLab Runner shell, Terraform, Ansible) |
| dockhost-50 | 9050 | 192.168.1.50 | Docker services (Portainer, GitLab Runner) |
| kubecluster-40 | 9040 | 192.168.1.40 | K8s Control Plane |
| kubecluster-41 | 9041 | 192.168.1.41 | K8s Worker |
| kubecluster-42 | 9042 | 192.168.1.42 | K8s Worker |

### Ports importants

| Service | Port | Protocole |
|---------|------|-----------|
| SSH | 22 | TCP |
| HTTP | 80 | TCP |
| HTTPS | 443 | TCP |
| Proxmox Web | 8006 | TCP/HTTPS |
| Synology DSM | 5000 | TCP/HTTP |
| Portainer Agent | 9001 | TCP |

---

## Reseau Vagrant/libvirt (192.168.122.0/24)

### Cluster Kubernetes local

| VM | IP | Role |
|----|-----|------|
| k8s-controlplan | 192.168.122.70 | Control Plane |
| k8s-node1 | 192.168.122.71 | Worker |
| k8s-node2 | 192.168.122.72 | Worker |

### NodePorts exposes

| Service | NodePort | Acces |
|---------|----------|-------|
| Traefik | 30928 | http://192.168.122.71:30928 |
| Prometheus | 30928 | Via Host header |
| Grafana | 30928 | Via Host header |
| AlertManager | 30928 | Via Host header |

---

## Plan d'adressage des VMs

Convention : `192.168.1.{vm_ip_start}` ou `vm_ip_start` est defini dans Terraform.

```
.40-.49  : Cluster kubecluster (Kubernetes)
.50-.59  : Cluster dockhost (Docker services)
.60-.69  : Bastion (plan de controle)
```

---

## Correspondance VM ID / IP

La convention utilise le schema suivant :
- VM ID : `90XX`
- IP : `192.168.1.XX`

| Plage ID | Plage IP | Usage |
|----------|----------|-------|
| 9040-9049 | .40-.49 | kubecluster |
| 9050-9059 | .50-.59 | dockhost |
| 9060-9069 | .60-.69 | bastion |

---

## Configuration SSH

Les alias SSH sont configures dans `~/.ssh/config` :

| Alias | IP | User | Cle |
|-------|-----|------|-----|
| `pve` | 192.168.1.26 | root | `~/.ssh/id_proxmox` |
| `bastion-60` | 192.168.1.60 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `dockhost-50` | 192.168.1.50 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `kubecluster-40` | 192.168.1.40 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `kubecluster-41` | 192.168.1.41 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `kubecluster-42` | 192.168.1.42 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `nas` | 192.168.1.93 | xgueret | `~/.ssh/id_nas` |
