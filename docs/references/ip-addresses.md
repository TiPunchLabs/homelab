# IP address reference

## Main network (192.168.10.0/24)

### Physical equipment

| Equipment | IP | Description |
|------------|-----|-------------|
| **Proxmox VE** | 192.168.10.100 | Main hypervisor |
| **Gateway** | 192.168.10.254 | Router/Gateway |

### Proxmox VMs

| VM | VMID | IP | Usage |
|----|------|-----|-------|
| bastion-60 | 9060 | 192.168.10.60 | Bastion (GitLab Runner shell, Terraform, Ansible) |
| vpngate-50 | 9050 | 192.168.10.50 | WireGuard VPN Gateway |
| dockhost-90 | 9090 | 192.168.10.90 | Docker services (Portainer, GitLab Runner) |
| kubecluster-40 | 9040 | 192.168.10.40 | K8s Control Plane |
| kubecluster-41 | 9041 | 192.168.10.41 | K8s Worker |
| kubecluster-42 | 9042 | 192.168.10.42 | K8s Worker |

### Proxmox LXC Containers

| Container | CTID | IP | Usage |
|-----------|------|-----|-------|
| caddy-70 | 1070 | 192.168.10.70 | Caddy reverse proxy |
| dns-71 | 1071 | 192.168.10.71 | Pi-hole DNS |

### Important ports

| Service | Port | Protocol |
|---------|------|-----------|
| SSH | 22 | TCP |
| WireGuard VPN | 51820 | UDP |
| HTTP | 80 | TCP |
| HTTPS | 443 | TCP |
| Proxmox Web | 8006 | TCP/HTTPS |
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

## External access topology

The homelab LAN (`192.168.10.0/24`) is **not directly connected to the Internet**.
Traffic from Internet → homelab traverses two NAT layers:

```
INTERNET  (public IP ~ 90.36.x.x, Orange — dynamic)
   │
   ▼
┌──────────────────────────────────────┐
│  ISP box (Livebox)                   │
│  LAN: 192.168.1.0/24                 │
│  Admin: http://192.168.1.1           │
└──────────────────────────────────────┘
   │
   ▼  (WAN of mesh router = 192.168.1.10, DHCP — should be reserved by MAC)
┌──────────────────────────────────────┐
│  Mesh router (WERTMESH1800)          │
│  LAN: 192.168.10.0/24                │
│  Admin: http://192.168.10.1          │
└──────────────────────────────────────┘
   │
   ▼
   Homelab LAN (vpngate-50, dockhost-90, kubecluster, caddy-70, dns-71, ...)
```

### Port forwarding chain

To expose a service to the Internet, **two redirects** are required:

| Layer | From | To |
|-------|------|-----|
| Livebox | `WAN <proto> <port>` | `192.168.1.10:<port>` (mesh router) |
| Mesh router | `WAN <proto> <port>` | `192.168.10.X:<port>` (target host) |

**Current rules in production:**

| Service | Public port | Proto | Final destination |
|---------|-------------|-------|-------------------|
| WireGuard (wg-easy) | 51820 | UDP | `192.168.10.50:51820` (vpngate) |

A missing rule on either layer = silent drop. Symptom client-side:
`wg show` reports `0 B received, X B sent`.

---

## VM addressing plan

Convention: `192.168.10.{vm_ip_start}` where `vm_ip_start` is defined in Terraform.

```
.40-.49  : kubecluster (Kubernetes)
.50-.59  : vpngate (VPN gateway)
.60-.69  : bastion (control plane)
.70-.89  : LXC containers (caddy, pihole, ...)
.90-.99  : dockhost (Docker services)
```

---

## VM ID / IP mapping

The convention uses the following scheme:
- VM ID: `90XX`
- IP: `192.168.10.XX`

| ID range | IP range | Usage |
|----------|----------|-------|
| 9040-9049 | .40-.49 | kubecluster |
| 9050-9059 | .50-.59 | vpngate |
| 9060-9069 | .60-.69 | bastion |
| 1070-1089 | .70-.89 | LXC containers (caddy, pihole, ...) |
| 9090-9099 | .90-.99 | dockhost |

---

## SSH configuration

SSH aliases are configured in `~/.ssh/config`:

| Alias | IP | User | Key |
|-------|-----|------|-----|
| `pve` | 192.168.10.100 | ansible | `~/.ssh/proxmox` |
| `bastion-60` | 192.168.10.60 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `dockhost-90` | 192.168.10.90 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `kubecluster-40` | 192.168.10.40 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `kubecluster-41` | 192.168.10.41 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `kubecluster-42` | 192.168.10.42 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `vpngate-50` | 192.168.10.50 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `caddy-70` | 192.168.10.70 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
| `dns-71` | 192.168.10.71 | ansible | `~/.ssh/id_vm_proxmox_rsa` |
