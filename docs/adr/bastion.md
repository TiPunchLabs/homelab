# 🏗️ ADR — Bastion (VM 9060)

> **Document vivant** — Ce fichier regroupe les Architecture Decision Records (ADR) du sous-projet bastion.
> Chaque decision est numerotee, datee et immutable une fois acceptee. Pour revenir sur une decision, on en cree une nouvelle qui la remplace.

------

## 📖 Table des matieres

- [ADR-001 : Bastion dans le monorepo homelab](#adr-001--bastion-dans-le-monorepo-homelab)
- [ADR-002 : Mise a jour du bastion depuis le workstation](#adr-002--mise-a-jour-du-bastion-depuis-le-workstation)
- [ADR-003 : Runner GitHub Actions natif et auto-sync](#adr-003--runner-github-actions-natif-et-auto-sync)

------

## ADR-001 : Bastion dans le monorepo homelab

| | |
|---|---|
| **Date** | 2026-03-07 |
| **Statut** | Accepte |
| **Decideurs** | xgueret |

### Contexte

Le bastion (VM 9060) est le plan de controle de l'infrastructure homelab : il execute les commandes Terraform et les playbooks Ansible pour toutes les autres VMs (dockhost, kubecluster, proxmox). La question se pose de savoir si son code IaC doit vivre dans un repo separe ou rester dans le monorepo `homelab`.

### Decision

**Garder le bastion dans le monorepo homelab.**

### Justification

| Critere | Monorepo (choisi) | Repo separe |
|---------|-------------------|-------------|
| Module TF partage (`proxmox_vm_template`) | Reference locale directe | Necessite versionning ou duplication |
| Scripts partages (`ansible-vault-pass.sh`) | Disponibles directement | A dupliquer ou externaliser |
| CI/CD | Un seul workflow unifie | Deux pipelines a maintenir |
| Commits atomiques (module + consommateurs) | Oui | Non, coordination inter-repos |
| Conventions (linting, pre-commit, pyproject) | Une seule source | Risque de divergence |
| Securite / permissions fines | Non necessaire (projet solo) | Utile en equipe |

Le pattern est coherent avec les pratiques IaC courantes (GitOps, Terraform monorepos) ou le plan de controle cohabite avec les workloads dans le meme repo.

### Consequences

- Le bastion est bootstrappe depuis le workstation (terraform apply + ansible-playbook), puis clone le monorepo dans `~/homelab` pour operer les autres VMs.
- Un commit casse sur un autre sous-projet (ex: dockhost/) n'affecte pas le fonctionnement du bastion deja deploye, car le `git pull` est manuel.
- Si le projet passe en equipe, cette decision pourra etre revisitee (voir separation par CODEOWNERS ou repo dedie).

------

## ADR-002 : Mise a jour du bastion depuis le workstation

| | |
|---|---|
| **Date** | 2026-03-07 |
| **Statut** | Accepte |
| **Decideurs** | xgueret |

### Contexte

Apres le bootstrap initial, le bastion doit pouvoir etre mis a jour (nouveaux secrets, nouvelles cles SSH, nouveau tooling). Deux approches possibles :

1. **Depuis le workstation** : executer `ansible-playbook bastion/ansible/deploy.yml` comme pour n'importe quelle autre VM.
2. **Self-update depuis le bastion** : SSH sur le bastion, `git pull`, puis `ansible-playbook --connection=local`.

### Decision

**Mettre a jour le bastion depuis le workstation (option 1).**

### Justification

```
┌─────────────┐    ansible-playbook     ┌────────────┐
│ Workstation  │ ─────────────────────► │ Bastion-60 │
│ (controleur) │    SSH (port 22)       │ (cible)    │
└─────────────┘                         └────────────┘
```

- **Coherence** : meme pattern two-stage que dockhost et kubecluster. Le workstation est l'unique point d'execution Ansible pour le provisioning.
- **Simplicite** : pas de logique de self-management (git pull + ansible-playbook local) a implementer et maintenir sur le bastion.
- **Reproductibilite** : l'etat du bastion est entierement defini par le code sur le workstation, pas par un `git pull` potentiellement desynchronise.
- **Securite** : le bastion n'a pas besoin d'un token GitHub pour pull le repo (clone HTTPS en lecture seule suffit pour l'usage operationnel).

### Consequences

- Le workflow de mise a jour est : modifier le code localement, push sur GitHub, puis `ansible-playbook bastion/ansible/deploy.yml` depuis le workstation.
- Le clone `~/homelab` sur le bastion sert uniquement a l'execution operationnelle (terraform/ansible sur les autres VMs), pas a la mise a jour du bastion lui-meme.
- Pour mettre a jour le code operationnel sur le bastion, il faut soit relancer le role tooling (qui fait `git clone/pull`), soit SSH manuellement pour `git pull`.

------

## ADR-003 : Runner GitHub Actions natif et auto-sync

| | |
|---|---|
| **Date** | 2026-03-07 |
| **Statut** | Accepte |
| **Decideurs** | xgueret |

### Contexte

Le clone `~/homelab` sur bastion-60 sert a l'execution operationnelle (terraform/ansible sur les autres VMs). Sa mise a jour necessite un `git pull` manuel, ce qui cree un risque de desynchronisation entre le code sur GitHub et celui execute par le bastion.

Deux approches pour automatiser la synchronisation :
1. **Runner Docker** : GitHub Actions runner conteneurise (comme sur dockhost).
2. **Runner natif** : GitHub Actions runner installe directement via systemd.

### Decision

**Runner natif (systemd) avec workflow de sync declenche sur push to main.**

### Justification

| Critere | Runner natif (choisi) | Runner Docker |
|---------|----------------------|---------------|
| Prerequis | Aucun — installation directe | Necessite Docker (absent sur bastion) |
| Ressources | Leger — un seul processus systemd | Overhead Docker daemon sur une VM 2C/2GB |
| Coherence | Adapte au profil du bastion (VM legere, pas de conteneurs) | Pattern dockhost, inadapte ici |
| Maintenance | Mise a jour manuelle du binaire runner | Mise a jour via tag image Docker |

```
┌──────────┐   push to main   ┌──────────────┐   workflow    ┌────────────┐
│  GitHub   │ ───────────────► │ GitHub       │ ────────────► │ Bastion-60 │
│  (repo)   │                  │ Actions      │  self-hosted  │ ~/homelab  │
└──────────┘                   └──────────────┘   runner      │ git reset  │
                                                              └────────────┘
```

Le workflow `sync-bastion.yml` :
- Se declenche uniquement sur `push` to `main` (pas sur `pull_request` — securite)
- Cible le runner via le label `bastion`
- Execute `git fetch + git reset --hard` car le clone bastion est read-only

Le meme PAT que dockhost (`vault_github_runner_pat`) est reutilise pour l'enregistrement du runner au niveau organisation.

### Consequences

- Le clone `~/homelab` sur bastion est automatiquement synchronise a chaque push sur main.
- Le runner est enregistre au niveau organisation (TiPunchLabs), pas au niveau repo.
- **Securite** : le repo etant public, les workflows de fork PR ne doivent pas s'executer sur les self-hosted runners. Verifier dans GitHub Settings > Actions > General que "Fork pull request workflows" est desactive.
- La mise a jour de la version du runner est manuelle (modifier `github_runner_version` dans les defaults et relancer le playbook).

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
