# Structure du sous-projet Dockhost

## Vue d'ensemble

Le sous-projet `dockhost/` suit le pattern **two-stage deployment** : Terraform provisionne la VM, Ansible configure les services via Docker Compose.

```
dockhost/
│
├── README.md                           # Documentation du sous-projet
├── docs.md                             # Notes techniques
├── ansible.cfg                         # Configuration Ansible locale
│
├── terraform/                          # Stage 1 : Provisionnement VM
│   ├── main.tf                         # Resource VM (module proxmox_vm_template)
│   ├── variables.tf                    # Variables Terraform
│   ├── outputs.tf                      # Outputs (IP, VMID)
│   ├── providers.tf                    # Provider bpg/proxmox
│   ├── terraform.tfvars.example        # Exemple de variables (jamais commiter le .tfvars)
│   └── .terraform.lock.hcl            # Lock des providers
│
└── ansible/                            # Stage 2 : Configuration services
    ├── deploy.yml                      # Playbook principal
    ├── inventory.yml                   # Inventaire (dockhost-50)
    ├── requirements.yml                # Collections Ansible requises
    │
    ├── group_vars/
    │   └── dockhost/
    │       ├── all/
    │       │   └── main.yml            # Variables partagees (UFW, securite)
    │       └── vault/
    │           ├── config.yml          # Secrets chiffres (tokens, passwords)
    │           └── proxmox.yml         # Credentials Proxmox (chiffre)
    │
    └── roles/                          # Roles Ansible (ordre d'execution)
        ├── motd/                       # [1] Message of the Day
        │   ├── defaults/main.yml
        │   ├── tasks/main.yml
        │   └── templates/motd.j2
        │
        ├── docker/                     # [2] Docker Engine + Compose plugin
        │   ├── vars/main.yml
        │   ├── tasks/
        │   │   ├── main.yml
        │   │   └── install_docker_docker_compose_plugin.yml
        │   └── handlers/main.yml
        │
        ├── portainer_agent/            # [3] Agent Portainer (port 9001)
        │   ├── tasks/main.yml
        │   ├── handlers/main.yml
        │   └── templates/docker-compose.yml.j2
        │
        ├── postgresql/                 # [4] PostgreSQL 17.4 (port 5432)
        │   ├── defaults/main.yml       #     Variables par defaut (tuning, image)
        │   ├── tasks/main.yml
        │   ├── handlers/main.yml
        │   └── templates/
        │       ├── docker-compose.yml.j2
        │       ├── postgresql.conf.j2  #     Configuration performance
        │       └── pg_hba.conf.j2      #     Regles d'authentification
        │
        ├── security_hardening/         # Hardening SSH + UFW
        │   └── tasks/
        │       ├── main.yml
        │       ├── ssh.yml
        │       └── ufw.yml
        │
        ├── github_runner/              # [5] GitHub Actions Runner
        │   ├── defaults/main.yml
        │   ├── tasks/main.yml
        │   ├── handlers/main.yml
        │   └── templates/docker-compose.yml.j2
        │
        └── gitlab_runner/              # [6] GitLab Runner
            ├── defaults/main.yml
            ├── tasks/main.yml
            ├── handlers/main.yml
            └── templates/
                ├── docker-compose.yml.j2
                └── config.toml.j2      # Configuration GitLab Runner
```

---

## Pattern d'un role Docker

Chaque role qui deploie un service Docker suit la meme structure :

```
role_name/
├── defaults/main.yml               # Variables par defaut (image, tag, digest, ports)
├── tasks/main.yml                   # 1. Creer repertoire  2. Templater  3. Deployer
├── handlers/main.yml                # Handler: restart via docker_compose_v2
└── templates/
    └── docker-compose.yml.j2        # Template Docker Compose
```

### Flux d'execution d'un role

```
defaults/main.yml          tasks/main.yml                    templates/
     │                          │                                  │
     │  Variables par defaut    │  1. file: creer /opt/<role>/     │
     └─────────────────────────►│  2. template: docker-compose ◄──┘
                                │  3. docker_compose_v2: deploy
                                │
                                ▼
                         handlers/main.yml
                              │
                              ▼
                    docker_compose_v2: restarted
                    (declenche par notify)
```

---

## Arborescence sur la VM (runtime)

Fichiers deployes sur `dockhost-50` (192.168.1.50) :

```
/
├── opt/                                    # Fichiers d'installation (docker-compose)
│   ├── portainer/agent/
│   │   └── docker-compose.yml
│   ├── postgresql/
│   │   ├── docker-compose.yml
│   │   └── config/
│   │       ├── postgresql.conf
│   │       └── pg_hba.conf
│   ├── github-runner/
│   │   └── docker-compose.yml
│   └── gitlab-runner/
│       ├── docker-compose.yml
│       └── config/config.toml
│
└── app/data/                               # Donnees persistantes des services
    └── postgresql/                         # Donnees PostgreSQL (owner: 999:999)
```

---

## Secrets et variables

### Fichiers vault (chiffres avec Ansible Vault)

| Fichier | Contenu |
|---------|---------|
| `vault/config.yml` | Credentials user, SSH keys, tokens runners, password PostgreSQL |
| `vault/proxmox.yml` | Credentials API Proxmox |

### Variables partagees (`all/main.yml`)

| Variable | Description |
|----------|-------------|
| `app_group` | Groupe Unix pour les donnees applicatives |
| `app_data_path` | Chemin des donnees persistantes (`/app/data`) |
| `security_*` | Configuration SSH hardening et UFW |
| `security_open_ports` | Ports ouverts dans UFW (22, 5432, 9001) |

---

## Ordre d'execution du playbook

Le playbook `deploy.yml` execute les roles dans cet ordre :

```
Pre-tasks
  └── Creer groupe app_data
  └── Creer /app/data/
       │
       ▼
[1] motd                    # Message of the Day
[2] docker                  # Docker Engine + Compose
[3] portainer_agent         # Agent Portainer (port 9001)
[4] postgresql              # PostgreSQL 17.4 (port 5432)
[5] github_runner           # GitHub Actions Runner
[6] gitlab_runner           # GitLab Runner
```

> **Note** : Chaque role peut etre execute independamment via son tag :
> `ansible-playbook ansible/deploy.yml --tags postgresql`
