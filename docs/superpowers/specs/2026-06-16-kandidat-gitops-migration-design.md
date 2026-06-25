# 🦎 kandidat — Migration Ansible → full GitOps (Komodo)

> **Objectif** : faire de `kandidat` un déploiement **100 % GitOps** piloté par Komodo,
> sans aucun rôle Ansible de déploiement, avec `https://kandidat.internal` up et vérifiable.
> **Contrainte assumée** : coupure de service acceptée pendant la bascule, **mais les
> données de prod doivent être sauvegardées (`pg_dump`) puis réinjectées dans la base
> dédiée — aucune perte de données.**
> **Auteur** : Xavier Gueret · **Date** : 2026-06-16 · **Statut** : design (à valider)

------

## 📖 Contexte & état réel vérifié

`kandidat` est aujourd'hui déployé **via Ansible**, pas via Komodo. Chaîne actuelle :

```
push main (gitlab.com/tipunchlabs/kandidat)
  → CI: lint→test→security→build(:$SHA)→release→deploy
  → job deploy (runner `bastion`): ansible-playbook dockhost/ansible/deploy.yml --tags kandidat
  → rôle Ansible `kandidat` sur dockhost:
       1. CREATE USER/DATABASE dans le conteneur postgresql partagé (db-net)
       2. rend /opt/kandidat/docker-compose.yml depuis un .j2
       3. docker login registry + docker compose up
  → conteneur kandidat :8000 → Caddy (kandidat.internal) → Pi-hole DNS
```

Faits établis par investigation (API GitLab + lecture du code) :

| Fait | Vérification |
|---|---|
| Le repo GitLab `tipunchlabs/homelab-gitops` existe (id 81629969, privé, groupe TiPunchLabs) | `glab api projects/81629969` |
| …mais il est **VIDE** (`empty_repo: true`, 0 commit, pas de branche `main`) | `glab api .../repository/branches` → `[]` |
| Le dossier local `02-infrastructure/homelab-gitops/` **n'est pas un clone git** (pas de `.git`) | `ls -A` |
| Komodo ne déploie donc **aucun** workload GitOps aujourd'hui | repo source vide |
| Le Terraform `terraform/homelab-gitops/` est **sain** (state ↔ GitLab : `plan` = no changes) | `terraform plan` |
| `main` est protégée : **MR-only, no force-push** | `gitlab_branch_protection.main` |
| L'app kandidat crée son schéma au démarrage via `db.create_all()` (pas d'Alembic) | `services/database.py:130` |
| `config.py` : `DATABASE_URL` présent ⇒ PostgreSQL, sinon SQLite | `config.py` |
| kandidat stocke aussi des **fichiers sur disque** (`candidatures/*.md`) dans `FT_DATA_DIR=/app/data` — recherche hybride DB+fichiers | `services/search.py`, `config.py:4` |
| Ces fichiers vivent dans le **bind mount hôte** `/app/data/kandidat:/app/data` (compose Ansible actuel) | `roles/kandidat/templates/docker-compose.yml.j2:16` |
| Caddy route déjà `kandidat.internal → http://192.168.10.90:8000` (infra permanente) | `caddy/ansible/group_vars` |

------

## 🎯 Mental Model — architecture cible

```
DEV  01-projets/tipunchlabs/kandidat ──push main──▶ GitLab: tipunchlabs/kandidat
                                                          │
   CI kandidat: lint→test→security→build(:$SHA)→bump      │
        build : docker push registry.gitlab.com/tipunchlabs/kandidat:$SHA
        bump  : ouvre une MR sur homelab-gitops (tag→$SHA), auto-merge si CI verte
                                                          ▼
                                GitLab: tipunchlabs/homelab-gitops  (main protégée, MR-only)
                                                          │ webhook push (phase 2 TF)
                                                          ▼
                                Komodo Core (dockhost 192.168.10.90)
                                Stack "kandidat" ⇒ kandidat/compose.yaml
                                                          ▼
                          docker compose up (Periphery, dockhost)
                          ┌────────────────────────────────────────┐
                          │ kandidat (gunicorn :8000, publié 8000)  │
                          │    └─ DATABASE_URL ─▶ db                │
                          │ db = postgres:16 + volume kandidat-db   │
                          └────────────────────────────────────────┘
                                                          │ :8000
   Caddy LXC (infra permanente) : kandidat.internal ─▶ http://192.168.10.90:8000
   Pi-hole (infra permanente)   : résout kandidat.internal
                                                          ▼
                  ✅ VÉRIF : curl -k https://kandidat.internal → 200
```

**Principe** : Komodo possède tout le cycle de vie applicatif (app **+ sa base**).
Ansible ne déploie plus rien pour kandidat. Caddy/Pi-hole restent l'infra de routage
partagée (inchangée).

------

## 📝 Décisions de conception (actées)

| # | Décision | Justification |
|---|---|---|
| D1 | **PostgreSQL dédié** dans le Stack (`db` postgres:16 + volume `kandidat-db`). On quitte `db-net`. | kandidat devient self-contained et 100 % reproductible ; supprime le seul bout non-GitOps-able (bootstrap user/DB). Données migrées par **`pg_dump` (base partagée) → restore (base dédiée)** ; `create_all()` est idempotent (no-op si les tables sont déjà restaurées). |
| D6 | **Fichiers disque préservés via réutilisation du bind mount hôte** : le compose GitOps remonte le même chemin `/app/data/kandidat:/app/data`. | Les `candidatures/*.md` restent physiquement sur dockhost et survivent à la bascule **sans migration de fichiers** ; seule la base est dump/restore. Zéro risque sur les fichiers. |
| D2 | **Bump via MR auto-merge** : la CI ouvre une MR sur homelab-gitops, GitLab auto-merge dès CI verte. | Respecte la branch protection `main` (MR-only). Git = version exacte déployée, rollback = `git revert`. |
| D3 | **Claude produit les artefacts + runbook** ; l'utilisateur exécute Komodo UI / push GitLab / dockhost. | Komodo/GitLab/dockhost hors de portée directe de l'agent. |
| D4 | `terraform/homelab-gitops/` **reste à son emplacement** (volontaire ; le mettre dans `homelab-gitops/` polluerait le repo pull-é). | Documenté dans son README/BACKLOG. Incohérence de nommage seulement, non fonctionnelle. |
| D5 | Seed initial du repo = **kandidat uniquement** (+ README racine). | YAGNI ; poc-hello/portail-client traités séparément plus tard. |

------

## 🏗️ Section 0 — Prérequis bloquant : amorcer le repo vide

Le repo GitLab est vide et le dossier local n'est pas un clone. Avant toute migration :

1. Relier `02-infrastructure/homelab-gitops/` au remote `git@gitlab.com:tipunchlabs/homelab-gitops.git`
   (`git init -b main` + `git remote add origin …`, ou re-clone propre puis report du contenu).
2. Construire le **commit initial** = `README.md` racine + `kandidat/` (voir artefacts).
3. Comme `main` est protégée MR-only : pousser via une **branche + MR** (le premier push peut
   nécessiter un déverrouillage temporaire de la protection, ou un push initial autorisé au mainteneur).
4. `terraform/homelab-gitops/` n'est pas touché.

> ⚠️ Distinction clé : Terraform gère le **contenant** (projet, protection, deploy token) — sain.
> Le **contenu** (compose files) relève de git et manque entièrement. Section 0 comble ce trou.

------

## 📦 Artefacts produits (par Claude)

| Fichier | Action | Détail |
|---|---|---|
| `homelab-gitops/kandidat/compose.yaml` | créer | services `kandidat` (image `:$SHA`, `8000:8000`, healthcheck, `${SECRET_KEY}`, `DATABASE_URL=postgresql://kandidat:${DB_PASSWORD}@db:5432/kandidat`, **bind mount `/app/data/kandidat:/app/data`** pour les fichiers) + `db` (postgres:16, volume `kandidat-db`, healthcheck) |
| `homelab-gitops/kandidat/.env.example` | créer | placeholders `SECRET_KEY`, `DB_PASSWORD` |
| `homelab-gitops/kandidat/README.md` | créer/réécrire | doc GitOps exacte |
| `homelab-gitops/README.md` (racine) | créer | index des Stacks |
| `kandidat/.gitlab-ci.yml` | modifier | **supprimer** le stage `deploy` (Ansible) ; **ajouter** un stage `bump` (clone homelab-gitops, MAJ tag via `yq`, MR + auto-merge avec `HOMELAB_GITOPS_TOKEN`) |
| `homelab/dockhost/ansible/roles/kandidat/` | supprimer (`trash`) | rôle de déploiement obsolète |
| `homelab/dockhost/ansible/deploy.yml` | modifier | retirer le rôle `kandidat`, son tag, et `kandidat` de l'assoc `db-net` |
| `homelab/dockhost/ansible/group_vars/dockhost/vault/*` | modifier | retirer `vault_kandidat_*` (secret_key, db_password, database_url, registry creds) |
| `02-infrastructure/CLAUDE.md` | corriger | table des apps : kandidat = full GitOps (réel) |

> ✅ **À conserver** : la règle UFW `port 8000` dans `group_vars/dockhost/all/main.yml`
> (Caddy en a besoin pour atteindre kandidat). Caddy et Pi-hole **inchangés**.

------

## 🔐 Secrets : Ansible Vault → Komodo Core

| Aujourd'hui (Vault) | Demain |
|---|---|
| `vault_kandidat_secret_key` | Komodo secret `SECRET_KEY` |
| `vault_kandidat_db_password` | Komodo secret `DB_PASSWORD` (utilisé par `db` ET dans `DATABASE_URL`) |
| `vault_kandidat_database_url` | ❌ supprimé (reconstruit dans le compose) |
| `vault_kandidat_registry_user/password` | Config **auth registry GitLab privé** dans Komodo (pull image) |
| — (nouveau) | `HOMELAB_GITOPS_TOKEN` : variable CI GitLab (write sur homelab-gitops) pour ouvrir la MR de bump |

------

## 🔄 Cutover (coupure assumée, **données préservées**) & vérification

> **Légende** — chaque étape est étiquetée par qui l'exécute :
> **👤 TOI** = action manuelle de ta part (commande à lancer, clic dans Komodo/GitLab UI, dockhost) ·
> **🤖 CLAUDE** = produit/modifie des fichiers dans le repo · **⚙️ AUTO** = se déclenche tout seul (Komodo/CI).
> Le **plan d'implémentation** (étape suivante, `writing-plans`) détaillera **chaque action 👤 TOI** :
> commande exacte, ce qu'il faut cliquer/saisir, sortie attendue, et comment vérifier que c'est bon
> avant de passer à la suite.

1. **👤 TOI — 💾 Sauvegarde** : `pg_dump` de la base `kandidat` depuis le conteneur `postgresql` partagé, **AVANT toute coupure** (voir « Sauvegarde & restauration » ci-dessous). Vérifier l'intégrité du dump.
2. **👤 TOI** — Komodo : ajouter secrets `SECRET_KEY`, `DB_PASSWORD` + config auth registry GitLab privé.
3. **👤 TOI** — Exécuter Section 0 : pousser `README.md` + `kandidat/` sur homelab-gitops (branche + MR).
4. **👤 TOI** — Komodo UI : créer le Stack `kandidat` (repo homelab-gitops, file `kandidat/compose.yaml`, auto-sync ON).
5. **👤 TOI** — Terraform phase 2 : renseigner `TF_VAR_komodo_webhook_url` (avec le Stack ID) + `komodo_webhook_secret`, `terraform apply` → crée le webhook.
6. **👤 TOI** — Couper l'ancien : sur dockhost `docker compose -f /opt/kandidat/docker-compose.yml down` ; merger la CI sans le stage `deploy`.
7. **⚙️ AUTO** — Komodo déploie → la base `db` postgres dédiée démarre **vide**.
8. **👤 TOI — ♻️ Restauration** : injecter le dump dans la base dédiée (voir ci-dessous). `create_all()` devient alors un no-op (tables déjà restaurées).
9. **👤 TOI — ✅ Vérif déploiement** : Stack *healthy* dans Komodo ; `docker ps` montre `kandidat` + `db` ; `curl -k https://kandidat.internal` → 200.
10. **👤 TOI — ✅ Vérif données** : comptage de lignes des tables clés == dump source (aucune perte).
11. **👤 TOI — ✅ Vérif boucle GitOps** : un `git push` sur kandidat → CI `bump` → MR auto-merge → webhook → Komodo redéploie automatiquement.
12. **🤖 CLAUDE + 👤 TOI** — Cleanup : Claude supprime le rôle Ansible kandidat + wiring `deploy.yml` + `vault_kandidat_*` ; toi tu pousses homelab. **⚠️ Ne pas supprimer `/app/data/kandidat` sur dockhost** (fichiers réutilisés par le Stack).

### 💾 Sauvegarde & restauration des données

**Sauvegarde** (base partagée, avant coupure) — format custom, sans propriétaire pour faciliter le restore :

```bash
# Sur dockhost — dump compressé de la base kandidat
docker exec postgresql pg_dump -U postgres -d kandidat \
  --format=custom --no-owner --no-privileges \
  -f /tmp/kandidat.dump
docker cp postgresql:/tmp/kandidat.dump ./kandidat-2026-06-16.dump
# Vérifier : liste des objets du dump
pg_restore --list ./kandidat-2026-06-16.dump | head
```

**Restauration** (base dédiée du Stack, après déploiement) :

```bash
# Copier le dump dans le conteneur db du Stack kandidat
docker cp ./kandidat-2026-06-16.dump <stack>-db-1:/tmp/kandidat.dump
# Restaurer dans la base kandidat (rôle kandidat déjà créé par POSTGRES_DB/USER)
docker exec <stack>-db-1 pg_restore -U kandidat -d kandidat \
  --no-owner --role=kandidat --clean --if-exists /tmp/kandidat.dump
```

> Ordre sûr : restaurer **avant** que l'app n'écrive. `--clean --if-exists` rend le restore
> rejouable ; `create_all()` au démarrage ne fait rien si les tables existent déjà.
>
> 📁 **Fichiers disque** : aucune action de migration. Le nouveau Stack remonte le même
> bind mount hôte `/app/data/kandidat`, donc les `candidatures/*.md` sont déjà là. Seule
> précaution : ne pas supprimer `/app/data/kandidat` sur dockhost pendant le cleanup.

### Critères de succès
- ✅ `kandidat.internal` up et vérifiable (`curl -k` → 200)
- ✅ **Données de prod restaurées** : comptages de lignes identiques au dump source ; fichiers `candidatures/*.md` toujours présents et trouvables par la recherche
- ✅ kandidat 100 % GitOps : aucun rôle Ansible de déploiement ; git = source de vérité ; rollback = `git revert`
- ✅ boucle push-code → redeploy automatique fonctionnelle
- ✅ `deploy.yml` ne référence plus `kandidat`

### Tests
- **Sauvegarde/restauration** : `pg_restore --list` du dump OK ; après restore, comptage de lignes des tables clés == source.
- **Bump** : valider sur un commit jetable que la MR s'ouvre et auto-merge.
- **Rollback** : `git revert` du commit de bump sur homelab-gitops → Komodo redéploie l'image précédente.
- **Schéma** : `create_all()` au démarrage est bien un no-op sur base restaurée (pas de doublon/erreur).

------

## ⚠️ Hors périmètre (assumé)

- **Caddy + Pi-hole** : infra de reverse-proxy/DNS partagée (Ansible). kandidat a juste besoin qu'elle existe ; elle est inchangée.
- **Backup *récurrent* du volume `kandidat-db`** : une stratégie de sauvegarde continue du postgres dédié reste à définir. La présente migration ne couvre que le **dump/restore ponctuel de bascule** (données préservées). Noté, non traité ici.
- **Normalisation du nommage `terraform/homelab-gitops/`** : cosmétique, hors sujet.
- **poc-hello / portail-client** : brouillons locaux, migrés séparément plus tard.

------

## 🧯 Risques & points d'attention

| Risque | Mitigation |
|---|---|
| Perte de données **base** lors de la bascule (base partagée → base dédiée) | **`pg_dump` avant coupure + `pg_restore` après déploiement** ; dump conservé hors conteneur ; vérif par comptage de lignes. |
| Perte des **fichiers disque** (`candidatures/*.md`) | Bind mount hôte `/app/data/kandidat` **réutilisé** tel quel par le Stack (D6) ; ne pas supprimer ce chemin au cleanup. |
| Premier push bloqué par la branch protection `main` | Pousser via branche + MR ; déverrouillage temporaire si besoin pour le commit initial. |
| `HOMELAB_GITOPS_TOKEN` = secret write sur le repo GitOps | Token à portée minimale (write_repository sur ce seul projet) ; stocké en variable CI masquée. |
| Double déploiement transitoire (Ansible CI encore actif pendant la bascule) | Merger la suppression du stage `deploy` AVANT/lors de la création du Stack Komodo. |
| `cloudflared`/exposition publique | Non applicable à kandidat (interne via Caddy uniquement). |

------

> **Document de design — à valider avant rédaction du plan d'implémentation.**
