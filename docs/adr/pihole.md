# 🏗️ ADR — Pi-hole DNS (LXC 1071)

> **Document vivant** — Ce fichier regroupe les Architecture Decision Records (ADR) du sous-projet pihole.
> Chaque decision est numerotee, datee et immutable une fois acceptee. Pour revenir sur une decision, on en cree une nouvelle qui la remplace.

------

## 📖 Table des matieres

- [ADR-001 : Pi-hole natif au lieu de Docker](#adr-001--pi-hole-natif-au-lieu-de-docker)
- [ADR-002 : Template LXC reference par ID au lieu de download_file](#adr-002--template-lxc-reference-par-id-au-lieu-de-download_file)

------

## ADR-001 : Pi-hole natif au lieu de Docker

| | |
|---|---|
| **Date** | 2026-03-30 |
| **Statut** | Accepte |
| **Decideurs** | xgueret |

### Contexte

Pi-hole peut etre deploye de deux facons sur un LXC : installation native via le script officiel, ou conteneur Docker. Le choix impacte la complexite, les ressources, et la coherence avec le reste de l'infrastructure.

### Decision

**Installer Pi-hole nativement (script officiel + setupVars.conf), sans Docker.**

### Justification

| Critere | Pi-hole natif (choisi) | Pi-hole Docker |
|---------|----------------------|----------------|
| Coherence | Pattern LXC natif (comme caddy-70) | Docker dans LXC unprivileged = complexe (nesting, cgroups) |
| Ressources | ~50 MiB RAM | ~150 MiB RAM (overhead Docker daemon) |
| Installation | Script officiel + setupVars.conf (unattended) | docker-compose.yml + image |
| Mise a jour | `pihole -up` | Pull image Docker |
| Complexite Ansible | Wrapper autour du script + templates | Role Docker + docker-compose template |

### Consequences

- L'installation est pilotee par Ansible avec un `setupVars.conf` pre-genere pour le mode unattended.
- La mise a jour se fait via `pihole -up` (pas via apt).
- Docker n'est pas installe sur ce LXC, coherent avec le pattern caddy-70.
- Si un jour Docker est necessaire sur ce LXC, cette decision pourra etre revisitee.

------

## ADR-002 : Template LXC reference par ID au lieu de download_file

| | |
|---|---|
| **Date** | 2026-03-30 |
| **Statut** | Accepte |
| **Decideurs** | xgueret |

### Contexte

Le template LXC Ubuntu 24.04 (`ubuntu-24.04-standard_24.04-2_amd64.tar.zst`) est deja present sur le datastore Proxmox, telecharge et gere par le state Terraform de `caddy/`. Declarer une seconde ressource `proxmox_virtual_environment_download_file` dans `pihole/` echoue systematiquement :

1. **Sans `overwrite_unmanaged`** : le provider refuse de creer un fichier qui existe deja.
2. **Avec `overwrite_unmanaged = true`** : le provider tente de supprimer puis re-telecharger, mais le token Terraform n'a pas `Datastore.Allocate` (permission refusee).
3. **Import** : la ressource `download_file` ne supporte pas `terraform import`.

Chaque sous-projet LXC utilisant un state Terraform local independant, il n'y a pas de mecanisme natif de partage de state entre caddy/ et pihole/.

### Decision

**Referencer le template par son ID statique (`local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst`) au lieu de declarer une ressource `download_file`.**

### Justification

| Critere | ID statique (choisi) | download_file par projet | Remote backend + remote_state |
|---------|---------------------|-------------------------|-------------------------------|
| Simplicite | Une seule ligne, aucune ressource | Conflit quand le fichier existe deja | Backend a configurer (GitLab managed state, S3) |
| Permissions | Aucune permission supplementaire | Necessite `Datastore.Allocate` pour delete/recreate | Idem download_file |
| Maintenance | Modifier un string si le template change | Automatique mais fragile (conflits inter-states) | Plus robuste mais complexite operationnelle |
| Coherence | Le template est un prerequis d'infra, pas un livrable par projet | Chaque projet gere sa propre copie (duplication) | Partage propre mais sur-engineering pour un projet solo |

### Consequences

- Le template doit etre pre-existant sur Proxmox avant le `terraform apply` de pihole/. En pratique, il est deja la depuis le provisioning de caddy/.
- Si le template Ubuntu est mis a jour (nouvelle version), il faudra modifier le string dans chaque `main.tf` qui le reference. C'est rare (une fois par release Ubuntu LTS).
- Si le projet evolue vers un remote backend (GitLab managed state), cette decision pourra etre revisitee en faveur d'un `terraform_remote_state` partage.

------

<!-- Template pour les prochains ADR :

## ADR-XXX : Titre de la decision

| | |
|---|---|
| **Date** | YYYY-MM-DD |
| **Statut** | Propose / Accepte / Remplace par ADR-YYY |
| **Decideurs** | xgueret |

### Contexte

Quel probleme ou quelle question se pose ?

### Decision

Quelle option a ete choisie ?

### Justification

Pourquoi cette option plutot qu'une autre ? (tableau comparatif, diagramme, arguments)

### Consequences

Quels sont les effets de cette decision ? (positifs, negatifs, points d'attention)

-->
