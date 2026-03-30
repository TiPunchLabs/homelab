# 🏗️ ADR — Pi-hole DNS (LXC 1071)

> **Document vivant** — Ce fichier regroupe les Architecture Decision Records (ADR) du sous-projet pihole.
> Chaque decision est numerotee, datee et immutable une fois acceptee. Pour revenir sur une decision, on en cree une nouvelle qui la remplace.

------

## 📖 Table des matieres

- [ADR-001 : Pi-hole natif au lieu de Docker](#adr-001--pi-hole-natif-au-lieu-de-docker)

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
