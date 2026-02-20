
# VM Dockhost - Plateforme de conteneurisation Docker

## 📋 Vue d'ensemble

**Dockhost** est une machine virtuelle dédiée hébergeant l'ensemble de l'infrastructure de conteneurisation Docker pour les applications et projets du homelab. Elle centralise le déploiement, l'orchestration et la gestion des conteneurs via Docker et Docker Compose.

---

## 🎯 Rôle et objectif

Cette VM a pour vocation de :

* **Héberger toutes les applications conteneurisées** du homelab
* **Centraliser la gestion Docker** en un point unique
* **Fournir un environnement isolé** pour les déploiements applicatifs
* **Faciliter le CI/CD** et les déploiements automatisés
* **Séparer les workloads applicatifs** de l'infrastructure Proxmox

---

## ⚙️ Spécifications techniques

### Ressources allouées

| Ressource          | Valeur        | Justification                                      |
| ------------------ | ------------- | -------------------------------------------------- |
| **vCPU**     | 3 cores       | 75% du serveur - Multi-conteneurs concurrent       |
| **RAM**      | 10 GB         | Confortable pour 10-15 conteneurs simultanés      |
| **Stockage** | 50 GB SSD     | Performance optimale pour images et volumes actifs |
| **OS**       | Ubuntu/Debian | Stabilité et compatibilité Docker                |
| **Réseau**  | Bridge        | Intégration réseau local avec IP statique        |

### Stockage détaillé

**Répartition du disque SSD (50GB) :**

```
/                    → 10 GB  (Système + logs)
/var/lib/docker      → 35 GB  (Images, volumes, conteneurs)
Swap                 → 2 GB   (Mémoire virtuelle)
Réservé système      → 3 GB   (Sécurité et maintenance)
```

**Performances SSD :**

* Démarrage rapide des conteneurs (<5s)
* Pull d'images optimisé
* I/O bases de données performant
* Latence minimale pour applications temps réel

---

## 🐳 Stack Docker

### Logiciels installés

* **Docker Engine** : Moteur de conteneurisation
* **Docker Compose** : Orchestration multi-conteneurs
* **Portainer** (optionnel) : Interface web de gestion
* **Watchtower** (optionnel) : Mise à jour automatique des images

### Architecture applicative

```
┌─────────────────────────────────────────┐
│         VM Dockhost (Ubuntu)             │
├─────────────────────────────────────────┤
│  Docker Engine + Docker Compose         │
├─────────────────────────────────────────┤
│  ┌─────────┐  ┌─────────┐  ┌─────────┐ │
│  │ Web App │  │   API   │  │Database │ │
│  └─────────┘  └─────────┘  └─────────┘ │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐ │
│  │ Reverse │  │Monitoring│ │  Cache  │ │
│  │  Proxy  │  │ Stack   │  │ (Redis) │ │
│  └─────────┘  └─────────┘  └─────────┘ │
└─────────────────────────────────────────┘
```

---

## 📦 Capacité et dimensionnement

### Conteneurs supportés

**Configuration actuelle permet d'héberger :**

* **10-15 conteneurs légers** (Alpine Linux, <100MB)
* **5-8 conteneurs moyens** (Node.js, Python, 200-500MB)
* **2-3 bases de données** avec volumes modérés (<5GB)

**Exemples d'applications déployables :**

| Application               | Type          | Taille estimée |
| ------------------------- | ------------- | --------------- |
| Portainer                 | Management    | ~300 MB         |
| Nginx Proxy Manager       | Reverse Proxy | ~200 MB         |
| PostgreSQL/MySQL          | Database      | ~2 GB           |
| API Backend (Node/Python) | Application   | ~500 MB         |
| Frontend (React/Vue)      | Application   | ~300 MB         |
| Redis                     | Cache         | ~100 MB         |
| Grafana                   | Monitoring    | ~400 MB         |
| Prometheus                | Monitoring    | ~500 MB         |
| GitLab Runner             | CI/CD         | ~400 MB         |
| Nextcloud                 | Cloud Storage | ~1-2 GB         |

**Total exemple réaliste : ~6-8 GB utilisés sur 35 GB disponibles**

---

## 🔧 Configuration réseau

### Paramètres réseau

* **Interface** : Bridge Proxmox (vmbr0)
* **IP statique** : 192.168.x.10 (à définir)
* **Gateway** : 192.168.x.1
* **DNS** : 192.168.x.1 ou 1.1.1.1
* **Ports exposés** : Selon applications déployées

### Gestion des ports

Les conteneurs communiquent via :

* **Réseau Docker interne** (bridge custom)
* **Reverse proxy** (Nginx/Traefik) pour exposition externe
* **Port mapping** sélectif selon besoins

---

## 🛡️ Sécurité et maintenance

### Bonnes pratiques implémentées

1. **Isolation réseau** : Réseaux Docker séparés par projet
2. **Volumes persistants** : Données hors conteneurs
3. **Logs centralisés** : Rotation automatique (max 10MB/fichier)
4. **Updates automatiques** : Watchtower pour images critiques
5. **Backups réguliers** : Snapshots Proxmox + export volumes

### Monitoring

```bash
# Ressources système
htop
docker stats

# Espace disque
df -h /var/lib/docker
docker system df

# Logs
docker logs -f <container_name>
journalctl -u docker -f
```

### Nettoyage régulier

```bash
# Supprimer conteneurs/images/volumes inutilisés
docker system prune -a --volumes

# Nettoyer images danglings
docker image prune -a

# Supprimer logs anciens
journalctl --vacuum-time=7d
```

---

## 🚀 Déploiement et gestion

### Provisioning initial

1. **Création VM** via Terraform (template Ubuntu cloud-init)
2. **Installation Docker** via Ansible/cloud-init
3. **Configuration réseau** statique
4. **Déploiement Portainer** (optionnel)
5. **Setup Docker Compose** pour stacks applicatives

### Workflow de déploiement

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Git Commit   │────▶│  CI/CD       │────▶│  Dockhost VM  │
│ (docker-     │     │  Pipeline    │     │  (Deploy)    │
│  compose.yml)│     │              │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
```

---

## 📈 Évolutivité

### Limites actuelles

**Limite RAM** : 10 GB

* Permet ~15 conteneurs légers simultanés
* Au-delà : risque d'OOM (Out Of Memory)

**Limite stockage** : 50 GB SSD

* Suffisant pour 10-15 applications
* Nettoyage régulier nécessaire

### Options d'extension futures

1. **Scale vertical** : Augmenter RAM/CPU si serveur Proxmox évolue
2. **Disque HDD secondaire** : Monter `/mnt/data` pour backups/archives
3. **Migration K8s** : Si besoin d'orchestration avancée
4. **Cluster Docker Swarm** : Si haute disponibilité requise

---

## 📝 Métadonnées Terraform

```hcl
vm_count            = 1
vm_template_id      = 9001
vm_disk0_size       = 50      # GB SSD
vm_cpu_cores        = 3
vm_memory           = 10240   # MB (10GB)
vm_name_prefix      = "dockhost"
vm_baseid           = 9010
vm_ip_start         = 10
project_description = "VM for dockhost project - All Docker apps"
```

---

## 🎯 Cas d'usage principaux

### 1. Développement et test

* Environnements isolés par projet
* Tests d'intégration
* Validation pre-production

### 2. Applications de production

* Services web internes
* APIs REST/GraphQL
* Bases de données légères

### 3. Outils DevOps

* CI/CD runners
* Monitoring et alerting
* Gestion de secrets

### 4. Services personnels

* Cloud privé (Nextcloud)
* Media server (Jellyfin)
* Home automation

---

## ⚠️ Limitations connues

1. **Pas de haute disponibilité** : VM unique = SPOF (Single Point of Failure)
2. **Pas d'autoscaling** : Ressources fixes
3. **Backup manuel** : Snapshots Proxmox à planifier
4. **Monitoring basique** : Nécessite stack externe (Grafana/Prometheus)

---

## 🔗 Intégrations

* **Proxmox** : Hyperviseur et gestion infrastructure
* **Git** : Versionning des docker-compose.yml
* **Ansible** : Configuration automatisée (optionnel)
* **Terraform** : Provisioning IaC
* **Traefik/Nginx** : Reverse proxy et SSL

---

## 📚 Documentation associée

* Configuration Terraform : `main.tf`
* Variables : `variables.tf`
* Docker Compose stacks : `/opt/docker/stacks/`
* Backups : Snapshots Proxmox hebdomadaires

---

*Document généré le 12/10/2025*

*Version : 1.0*

*Environnement : Homelab Proxmox*
