# 🏗️ ADR — Caddy (LXC 1070)

> **Document vivant** — Ce fichier regroupe les Architecture Decision Records (ADR) du sous-projet caddy.
> Chaque decision est numerotee, datee et immutable une fois acceptee. Pour revenir sur une decision, on en cree une nouvelle qui la remplace.

------

## 📖 Table des matieres

- [ADR-001 : HTTP only, pas de TLS](#adr-001--http-only-pas-de-tls)
- [ADR-002 : Domaines .internal au lieu de .local](#adr-002--domaines-internal-au-lieu-de-local)
- [ADR-003 : tls_insecure_skip_verify pour Proxmox](#adr-003--tls_insecure_skip_verify-pour-proxmox)
- [ADR-004 : IPs backends en clair dans group_vars](#adr-004--ips-backends-en-clair-dans-group_vars)

------

## ADR-001 : HTTP only, pas de TLS

| | |
|---|---|
| **Date** | 2026-03-27 |
| **Statut** | Accepte |
| **Decideurs** | xgueret |

### Contexte

Caddy active automatiquement HTTPS avec Let's Encrypt. Sur un LAN prive sans nom de domaine public, cette fonctionnalite est inutile et genere des erreurs de certificat. Le transport entre le client (laptop) et caddy-70 est deja securise par le tunnel VPN WireGuard (via vpngate-50).

### Decision

**Desactiver HTTPS (`auto_https off`) et servir uniquement en HTTP sur le port 80.**

### Justification

| Critere | HTTP only (choisi) | HTTPS auto-signe |
|---------|-------------------|------------------|
| Complexite | Aucune — configuration minimale | Generer et distribuer des certificats auto-signes |
| Securite transport | VPN WireGuard couvre le transport | Double chiffrement inutile |
| Compatibilite clients | Pas de warning certificat | Warning navigateur a chaque connexion |
| Maintenance | Zero | Rotation des certificats a gerer |

### Consequences

- Le Caddyfile utilise `auto_https off` dans le bloc global.
- Les sites ecoutent sur `:80` (pas de redirection HTTPS).
- Si un jour le reverse proxy est expose sur Internet, cette decision devra etre revisitee.

------

## ADR-002 : Domaines .internal au lieu de .local

| | |
|---|---|
| **Date** | 2026-03-27 |
| **Statut** | Accepte |
| **Decideurs** | xgueret |

### Contexte

Le reverse proxy Caddy local (Docker) utilisait des domaines `.local` (ex: `proxmox.local`). La migration vers le LXC caddy-70 est l'occasion de revoir la convention de nommage DNS.

### Decision

**Utiliser le TLD `.internal` (ex: `proxmox.internal`, `kandidat.internal`) au lieu de `.local`.**

### Justification

| Critere | `.internal` (choisi) | `.local` (ancien) |
|---------|---------------------|-------------------|
| Conflit mDNS | Aucun | `.local` est reserve par mDNS (RFC 6762) — conflit Avahi/Bonjour |
| Standard IANA | Reserve pour usage prive (RFC 6761) | Reserve pour multicast DNS, pas pour usage statique |
| Compatibilite | Resolu normalement par `/etc/hosts` ou DNS | Certains OS interceptent `.local` pour mDNS |
| Clarte | Indique clairement un service interne | Ambigue — local a quoi ? |

### Consequences

- Les domaines des 3 backends passent de `.local` a `.internal`.
- Le fichier `/etc/hosts` du laptop (via `laptop-bootstrap`) est mis a jour en consequence.
- Les anciens domaines `.local` restent pour les services Docker locaux (openwebui, portainer, etc.) qui ne sont pas dans le scope de cette migration.

------

## ADR-003 : tls_insecure_skip_verify pour Proxmox

| | |
|---|---|
| **Date** | 2026-03-27 |
| **Statut** | Accepte |
| **Decideurs** | xgueret |

### Contexte

Le backend Proxmox VE (192.168.1.100:8006) expose son interface web uniquement en HTTPS avec un certificat auto-signe. Caddy, en tant que reverse proxy, doit se connecter a ce backend en HTTPS mais ne peut pas valider le certificat.

### Decision

**Activer `tls_insecure_skip_verify` dans le transport HTTP du reverse proxy uniquement pour le backend Proxmox.**

### Justification

```
┌────────┐  HTTP   ┌──────────┐  HTTPS (self-signed)  ┌──────────────┐
│ Client │ ──────► │ Caddy-70 │ ────────────────────► │ Proxmox:8006 │
│ (VPN)  │  :80    │ (LXC)    │  skip verify          │ (hyperviseur)│
└────────┘         └──────────┘                        └──────────────┘
```

- Le certificat auto-signe de Proxmox ne peut pas etre valide par une CA publique.
- Deployer une CA interne pour un seul backend serait du sur-engineering.
- Le trafic Caddy → Proxmox reste sur le LAN prive (meme sous-reseau 192.168.1.0/24).
- L'option est activee uniquement pour ce backend, pas globalement.

### Consequences

- La connexion Caddy → Proxmox est chiffree (TLS) mais sans validation du certificat.
- Si d'autres backends HTTPS auto-signes sont ajoutes, l'option devra etre activee individuellement (pas de blanket skip).
- Si une CA interne est mise en place plus tard, cette decision pourra etre revisitee.

------

## ADR-004 : IPs backends en clair dans group_vars

| | |
|---|---|
| **Date** | 2026-03-27 |
| **Statut** | Accepte |
| **Decideurs** | xgueret |

### Contexte

Les adresses IP des backends (Proxmox, Kandidat, VPNGate) doivent etre configurees dans le Caddyfile. La question se pose de savoir si ces valeurs doivent etre chiffrees avec Ansible Vault.

### Decision

**Stocker les IPs des backends en clair dans `group_vars/caddy/all/main.yml`, sans chiffrement Vault.**

### Justification

| Critere | En clair (choisi) | Ansible Vault |
|---------|-------------------|---------------|
| Sensibilite | IPs privees (192.168.1.x) — non sensible | Chiffrement inutile pour des IPs LAN |
| Lisibilite | Visible directement dans le code | Necessite `ansible-vault view` pour chaque modification |
| Maintenance | Modification directe | Cycle encrypt/decrypt a chaque changement |
| Coherence | Meme approche que l'inventaire Ansible (IPs en clair) | Incoherent — l'inventaire expose deja les IPs |

### Consequences

- Les IPs sont visibles dans le repo Git (public sur GitHub mirror).
- Aucun risque de securite : les IPs privees (RFC 1918) ne sont pas routables depuis Internet.
- Les secrets reels (tokens API, mots de passe) restent dans Vault.

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
