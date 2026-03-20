# 🔒 Understanding the WireGuard Role

> **Prerequisites**: Basic knowledge of VPN concepts, Linux networking, Ansible roles
> **Scope**: Explains every task, template, and configuration choice in the `wireguard` role
> **Role path**: `vpngate/ansible/roles/wireguard/`

------

## 🧠 Mental Model

```
┌─────────────────────────────────────────────────────────┐
│                    vpngate-50 (VM)                      │
│                   192.168.1.50                          │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │              WireGuard (kernel module)             │  │
│  │                                                   │  │
│  │  wg0 interface ─── 10.0.0.1/24 (VPN subnet)     │  │
│  │       │                                           │  │
│  │       │  UDP :51820                               │  │
│  │       │                                           │  │
│  │  iptables NAT ─── MASQUERADE on eth0             │  │
│  │  (ip_forward=1)                                   │  │
│  └───────────────────────────────────────────────────┘  │
│                         │                               │
│                    eth0 │ 192.168.1.50                  │
└─────────────────────────┼───────────────────────────────┘
                          │
           ┌──────────────┼──────────────┐
           │       LAN 192.168.1.0/24    │
           │  (proxmox, bastion, etc.)   │
           └─────────────────────────────┘
                          │
                     Internet
                          │
              ┌───────────┴───────────┐
              │   Peers (clients)     │
              │   10.0.0.2, .3, ...   │
              └───────────────────────┘
```

**In a nutshell**: WireGuard creates a virtual network interface (`wg0`) that encrypts all traffic between the server and its peers using public/private key pairs. The server acts as a gateway — it forwards traffic from VPN clients to the LAN and Internet via NAT masquerading.

------

## 📖 Table of Contents

1. [Why WireGuard](#-1-why-wireguard)
2. [Role Structure](#-2-role-structure)
3. [Tasks Walkthrough](#-3-tasks-walkthrough)
4. [Template Breakdown](#-4-template-breakdown-wg0confj2)
5. [Variables Reference](#-5-variables-reference)
6. [Security Choices](#-6-security-choices)
7. [Adding a Peer](#-7-adding-a-peer)
8. [Troubleshooting](#-8-troubleshooting)

------

## 🎯 1. Why WireGuard

| Criteria | WireGuard | OpenVPN |
|---|---|---|
| **Codebase** | ~4,000 lines (kernel module) | ~100,000 lines (userspace) |
| **Performance** | Near-native (in-kernel) | Slower (TUN/TAP + userspace) |
| **Crypto** | Modern, fixed (Curve25519, ChaCha20, Poly1305) | Configurable (TLS, many ciphers) |
| **Config complexity** | Minimal (one file) | Complex (PKI, certs, CA) |
| **Attack surface** | Tiny | Large |
| **Roaming** | Built-in (IP changes transparent) | Reconnection needed |
| **Resource usage** | Minimal (ideal for 512 MB VM) | Higher |

> **Analogy**: OpenVPN is like a Swiss army knife — flexible but heavy. WireGuard is like a scalpel — does one thing, does it perfectly.

------

## 🏗️ 2. Role Structure

```
wireguard/
├── defaults/main.yml      # Default variables (overridable in group_vars)
├── tasks/main.yml         # 9 tasks in execution order
├── templates/wg0.conf.j2  # WireGuard configuration template
└── handlers/main.yml      # Service restart handler
```

------

## 📝 3. Tasks Walkthrough

The role executes 9 tasks in a deliberate order. Here's why each exists and the choices behind it.

### Task 1 — Install WireGuard

```yaml
- name: Install WireGuard
  ansible.builtin.apt:
    name: wireguard
    state: present
    update_cache: true
```

**What it does**: Installs the `wireguard` package (userspace tools + kernel module).

**Why `update_cache: true`**: Ensures the package index is fresh. On a newly provisioned VM, the apt cache may be empty or stale. Without this, `apt` could fail to find the package.

**Why no version pin**: WireGuard is stable and backward-compatible. The kernel module is part of Linux since 5.6 — Ubuntu 24.04 ships it natively. The package mainly provides `wg` and `wg-quick` CLI tools.

------

### Task 2 — Enable IPv4 Forwarding

```yaml
- name: Enable IPv4 forwarding
  ansible.posix.sysctl:
    name: net.ipv4.ip_forward
    value: '1'
    sysctl_set: true
    reload: true
```

**What it does**: Sets `net.ipv4.ip_forward = 1` in `/etc/sysctl.conf` and applies it immediately.

**Why it's needed**: By default, Linux drops packets not destined for its own interfaces. A VPN server must forward packets between the `wg0` interface (VPN tunnel) and `eth0` (LAN/Internet). Without this, peers can connect but can't reach anything beyond the server.

**Why `ansible.posix.sysctl`**: More robust than a raw `sysctl -w` command — it persists across reboots and is idempotent.

------

### Tasks 3-4 — Generate and Save Server Private Key

```yaml
- name: Generate server private key
  ansible.builtin.command:
    cmd: wg genkey
    creates: /etc/wireguard/server_private.key
  register: wg_genkey
  no_log: true

- name: Save server private key
  ansible.builtin.copy:
    content: "{{ wg_genkey.stdout }}"
    dest: /etc/wireguard/server_private.key
    owner: root
    group: root
    mode: '0600'
  when: wg_genkey.changed
  no_log: true
```

**What it does**: Generates a Curve25519 private key using `wg genkey`, then saves it to disk.

**Why `creates:` guard**: The `creates` parameter makes the task idempotent — if the key file already exists, the command is skipped. This prevents generating a new key on every playbook run, which would invalidate all peer configurations.

**Why two tasks instead of one**: `wg genkey` outputs to stdout. We need to capture it (`register`), then write it to a file separately. A single `shell` command with redirect (`wg genkey > file`) would not be idempotent and would overwrite existing keys.

**Why `no_log: true`**: Prevents the private key from appearing in Ansible output or logs. This is a security requirement — private keys must never be exposed.

**Why `mode: '0600'`**: Read/write for root only. WireGuard refuses to start if the config (which contains the private key) is world-readable.

------

### Task 5 — Read Server Private Key

```yaml
- name: Read server private key
  ansible.builtin.slurp:
    src: /etc/wireguard/server_private.key
  register: wg_private_key
  no_log: true
```

**What it does**: Reads the private key file content into an Ansible variable (base64-encoded).

**Why `slurp` instead of `command: cat`**: `slurp` is the Ansible-native way to read file content from a remote host. It returns base64-encoded data, which is safer for transport. Using `cat` via `shell`/`command` would work but triggers ansible-lint warnings and is less portable.

**Why this task exists at all**: The key might have been generated in a previous playbook run (task 3 skipped due to `creates:`). We need the key value for the template regardless of whether it was just generated or already existed.

------

### Tasks 6-7 — Generate and Save Server Public Key

```yaml
- name: Generate server public key
  ansible.builtin.shell:
    cmd: set -o pipefail && cat /etc/wireguard/server_private.key | wg pubkey
    executable: /bin/bash
  register: wg_pubkey
  changed_when: false
  no_log: true

- name: Save server public key
  ansible.builtin.copy:
    content: "{{ wg_pubkey.stdout }}"
    dest: /etc/wireguard/server_public.key
    owner: root
    group: root
    mode: '0644'
```

**What it does**: Derives the public key from the private key using `wg pubkey`, then saves it.

**Why `shell` instead of `command`**: The pipe (`|`) requires a shell. `command` doesn't support pipes.

**Why `set -o pipefail`**: ansible-lint `risky-shell-pipe` rule. Without `pipefail`, if `cat` fails, the exit code of the pipe is only from `wg pubkey` (which might succeed with empty input). `pipefail` ensures any failure in the pipeline is caught.

**Why `executable: /bin/bash`**: `pipefail` is a bash feature, not POSIX `sh`. We must explicitly request bash.

**Why `changed_when: false`**: Deriving a public key from a private key is a pure function — same input always gives same output. The task doesn't modify state, so we tell Ansible it never "changed" anything.

**Why `mode: '0644'` for the public key**: Public keys are not secrets. They need to be readable so you can share them with peers. This is by design — WireGuard's security model relies on the private key staying secret, not the public key.

------

### Task 8 — Deploy WireGuard Configuration

```yaml
- name: Deploy WireGuard configuration
  ansible.builtin.template:
    src: wg0.conf.j2
    dest: "/etc/wireguard/{{ wireguard_interface }}.conf"
    owner: root
    group: root
    mode: '0600'
  notify: Restart wireguard
```

**What it does**: Renders the Jinja2 template into the WireGuard config file.

**Why `notify` instead of immediate restart**: Ansible handlers run at the end of the play, and only if the task actually changed the file. This prevents unnecessary restarts when the config hasn't changed (idempotency).

**Why `mode: '0600'`**: The config contains the private key in cleartext. WireGuard's `wg-quick` refuses to load configs with insecure permissions.

------

### Task 9 — Enable and Start WireGuard

```yaml
- name: Enable and start WireGuard
  ansible.builtin.systemd:
    name: "wg-quick@{{ wireguard_interface }}"
    enabled: true
    state: started
```

**What it does**: Starts the WireGuard tunnel and enables it to survive reboots.

**Why `wg-quick@`**: WireGuard uses systemd template units. `wg-quick@wg0` tells systemd to manage the interface `wg0` using `/etc/wireguard/wg0.conf`. This pattern supports multiple interfaces (`wg0`, `wg1`, etc.).

**Why `state: started` (not `restarted`)**: On first run, we want to start the service. On subsequent runs, if the config hasn't changed, we don't want to disrupt active connections. The `notify: Restart wireguard` handler handles restarts only when the config template changes.

------

## 🔧 4. Template Breakdown — `wg0.conf.j2`

```ini
# Ansible managed — do not edit manually

[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = <server-private-key>
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

[Peer]
# laptop
PublicKey = <peer-public-key>
AllowedIPs = 10.0.0.2/32
```

### Section `[Interface]`

| Directive | Value | Purpose |
|---|---|---|
| `Address` | `10.0.0.1/24` | VPN IP of the server. `/24` defines the VPN subnet (254 peers max) |
| `ListenPort` | `51820` | UDP port WireGuard listens on (default, IANA registered) |
| `PrivateKey` | From `slurp` | Server's Curve25519 private key |
| `PostUp` | iptables rules | Applied when the interface comes up |
| `PostDown` | iptables rules | Applied when the interface goes down (cleanup) |

### NAT Masquerading Explained

```
PostUp = iptables -A FORWARD -i %i -j ACCEPT;
         iptables -t nat -A POSTROUTING -o <eth0> -j MASQUERADE
```

- **`FORWARD -i %i -j ACCEPT`**: Allow packets arriving on the WireGuard interface to be forwarded (needed because default `FORWARD` policy is often `DROP`)
- **`MASQUERADE`**: Rewrite the source IP of VPN packets to the server's LAN IP. This makes VPN traffic appear to originate from vpngate-50 (192.168.1.50), allowing it to reach the LAN and Internet without additional routing

> **Analogy**: MASQUERADE is like a post office forwarding service — mail (packets) from VPN clients gets a new return address (server's IP) so replies come back to the server, which forwards them back through the tunnel.

**Why `%i`**: WireGuard substitutes `%i` with the interface name (`wg0`). This is a `wg-quick` convention, not an Ansible variable.

**Why dynamic interface detection**: `{{ ansible_facts["default_ipv4"]["interface"] }}` resolves to the actual NIC name (e.g., `eth0`, `ens18`). Hardcoding `eth0` would break on VMs where the interface has a different name.

### Section `[Peer]`

Each peer is rendered from the `wireguard_peers` list variable:

```yaml
wireguard_peers:
  - name: laptop
    public_key: "abc123..."
    allowed_ips: "10.0.0.2/32"
    persistent_keepalive: 25
```

| Field | Required | Purpose |
|---|---|---|
| `name` | No | Comment label for readability |
| `public_key` | Yes | Peer's public key (generated on the client) |
| `allowed_ips` | Yes | IP(s) this peer is allowed to use. `/32` = single IP |
| `persistent_keepalive` | No | Sends a keepalive packet every N seconds (useful behind NAT) |

------

## 📊 5. Variables Reference

### Defaults (`defaults/main.yml`)

| Variable | Default | Description |
|---|---|---|
| `wireguard_port` | `51820` | UDP listening port |
| `wireguard_interface` | `wg0` | Virtual interface name |
| `wireguard_address` | `10.0.0.1/24` | Server's VPN IP and subnet |
| `wireguard_dns` | `1.1.1.1, 8.8.8.8` | DNS servers pushed to peers |
| `wireguard_persistent_keepalive` | `25` | Default keepalive interval (seconds) |
| `wireguard_peers` | `[]` | List of peer configurations |

### Group Vars Override (`group_vars/vpngate/all/main.yml`)

The group vars explicitly set `wireguard_port`, `wireguard_interface`, `wireguard_address`, and `wireguard_dns`. These take precedence over defaults, making the configuration visible and auditable at the inventory level.

------

## 🔐 6. Security Choices

### Key Generation On-Server

Keys are generated directly on the VM, not in Ansible Vault. This is a deliberate choice:

| Approach | Pros | Cons |
|---|---|---|
| **Generate on server** (chosen) | Key never transits the network, never stored in git | Must SSH to read public key |
| Store in Vault | Centralized, reproducible | Key transits SSH, stored in git (encrypted), rotation harder |

### `no_log` on Key Tasks

Every task that handles the private key has `no_log: true`. This prevents key leakage in:
- Terminal output during playbook execution
- Ansible callback logs
- CI/CD pipeline logs

### File Permissions

```
server_private.key  → 0600 (root only)
server_public.key   → 0644 (public, shareable)
wg0.conf            → 0600 (contains private key)
```

### UFW Integration

The `security_hardening` role opens only two ports:
- **22/tcp** — SSH administration
- **51820/udp** — WireGuard tunnel

All other incoming traffic is denied by default.

------

## ✅ 7. Adding a Peer

### Step 1 — Generate Keys on the Client

```bash
# On the client machine
wg genkey | tee private.key | wg pubkey > public.key
```

### Step 2 — Add the Peer to Group Vars or Vault

```yaml
# group_vars/vpngate/all/main.yml (or vault for sensitive setups)
wireguard_peers:
  - name: laptop
    public_key: "aBcDeFgHiJkLmNoPqRsTuVwXyZ="
    allowed_ips: "10.0.0.2/32"
    persistent_keepalive: 25
```

### Step 3 — Run the Playbook

```bash
cd vpngate
ansible-playbook ansible/deploy.yml --tags wireguard
```

### Step 4 — Configure the Client

```ini
# /etc/wireguard/wg0.conf on the client
[Interface]
PrivateKey = <client-private-key>
Address = 10.0.0.2/24
DNS = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey = <server-public-key>    # from /etc/wireguard/server_public.key on vpngate-50
Endpoint = <your-public-ip>:51820
AllowedIPs = 0.0.0.0/0            # Route all traffic through VPN
PersistentKeepalive = 25
```

> 💡 **Note**: To retrieve the server's public key: `ssh vpngate-50 sudo cat /etc/wireguard/server_public.key`

------

## 🔧 8. Troubleshooting

| Symptom | Diagnostic | Fix |
|---|---|---|
| Peer can't connect | `sudo wg show` on server — peer not listed | Check peer's `Endpoint` and server's UFW (port 51820/udp) |
| Peer connected but no Internet | `sysctl net.ipv4.ip_forward` — returns 0 | Re-run playbook or `sysctl -w net.ipv4.ip_forward=1` |
| Peer connected but can't reach LAN | `iptables -t nat -L` — no MASQUERADE rule | Check PostUp rules in wg0.conf, restart wg-quick |
| Handshake but no data | `sudo wg show` — check `transfer` counters | Verify `AllowedIPs` on both sides match |
| Config rejected at startup | `journalctl -u wg-quick@wg0` | Usually a permissions issue (config not 0600) or malformed key |
| Playbook fails on key gen | Check `/etc/wireguard/` exists | `mkdir -p /etc/wireguard` (should exist after apt install) |

**Useful commands on vpngate-50**:

```bash
# Show active WireGuard status
sudo wg show

# Show interface details
ip addr show wg0

# Check forwarding
sysctl net.ipv4.ip_forward

# Check NAT rules
sudo iptables -t nat -L -v

# Check WireGuard logs
sudo journalctl -u wg-quick@wg0 -f
```

------

## 📚 Resources

- [WireGuard Official Documentation](https://www.wireguard.com/)
- [WireGuard Whitepaper (Jason Donenfeld)](https://www.wireguard.com/papers/wireguard.pdf)
- [Ansible `ansible.posix.sysctl` module](https://docs.ansible.com/ansible/latest/collections/ansible/posix/sysctl_module.html)
- [wg-quick(8) man page](https://man7.org/linux/man-pages/man8/wg-quick.8.html)

------

> **Document created on**: 2026-03-19
> **Author**: Claude Code
> **Version**: 1.0
