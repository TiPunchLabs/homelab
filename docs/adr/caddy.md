# 🏗️ ADR — Caddy (LXC 1070)

> **Document vivant** — Ce fichier regroupe les Architecture Decision Records (ADR) du sous-projet caddy.
> Chaque decision est numerotee, datee et immutable une fois acceptee. Pour revenir sur une decision, on en cree une nouvelle qui la remplace.

------

## 📖 Table des matieres

- [ADR-001 : HTTP only, pas de TLS](#adr-001--http-only-pas-de-tls) — *remplace par ADR-006*
- [ADR-002 : Domaines .internal au lieu de .local](#adr-002--domaines-internal-au-lieu-de-local)
- [ADR-003 : tls_insecure_skip_verify pour Proxmox](#adr-003--tls_insecure_skip_verify-pour-proxmox)
- [ADR-004 : IPs backends en clair dans group_vars](#adr-004--ips-backends-en-clair-dans-group_vars)
- [ADR-005 : Restriction de l'API admin aux reseaux prives](#adr-005--restriction-de-lapi-admin-aux-reseaux-prives)
- [ADR-006 : HTTPS interne opt-in par backend](#adr-006--https-interne-opt-in-par-backend)

------

## ADR-001 : HTTP only, pas de TLS

> ⚠️ **Remplace par [ADR-006](#adr-006--https-interne-opt-in-par-backend) (2026-08-24).** Conserve pour l'historique — ne decrit plus l'etat du systeme.

| | |
|---|---|
| **Date** | 2026-03-27 |
| **Statut** | Remplace par ADR-006 |
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

## ADR-005 : Restriction de l'API admin aux reseaux prives

| | |
|---|---|
| **Date** | 2026-06-27 |
| **Statut** | Accepte |
| **Decideurs** | xgueret |

### Contexte

Depuis l'exposition publique de `portail-client.tipunchlabs.fr` (vhost ACME DNS-01 OVH), les routes `/api/admin*` de l'application sont joignables depuis Internet. L'application protege ces routes par un Bearer token, mais cette protection est la seule barriere : une regression applicative, un token fuite ou une route oubliee suffit a exposer l'administration au monde entier.

Le vhost interne `portail-client.internal` pose la meme question, meme si sa surface est limitee au LAN et au VPN.

### Decision

**Ajouter un flag opt-in `restrict_admin_lan` par backend. Quand il est actif, le Caddyfile ne sert `/api/admin*` que depuis les plages RFC 1918 et la loopback ; toute autre source recoit un 403 avant d'atteindre l'upstream.**

Le flag est active sur les deux vhosts `portail-client` (interne et public).

### Justification

```
Internet ──► Livebox :443 ──► Caddy-70 ──┬─ /api/admin*  + IP publique ──► 403 (Caddy)
                                          │
LAN / VPN ──────────────────────────────► ├─ /api/admin*  + RFC1918   ──► upstream ──► Bearer token
                                          │
                                          └─ tout le reste            ──► upstream
```

| Critere | Filtrage `remote_ip` dans Caddy (choisi) | Bearer token seul | Regle UFW / firewall |
|---------|------------------------------------------|-------------------|----------------------|
| Granularite | Par chemin (`/api/admin*`) | Par chemin, cote applicatif | Par port uniquement — impossible de distinguer les routes |
| Resistance a une regression applicative | Le 403 tombe avant l'upstream | Aucune — une route oubliee est exposee | N/A |
| Couplage au code applicatif | Aucun | Total | Aucun |
| Cout | Un matcher par vhost | Deja en place | Ne repond pas au besoin |

Le filtrage est une **couche 1** : il ne remplace pas le Bearer token (couche 2), il fait en sorte qu'une defaillance de la couche 2 ne soit pas immediatement exploitable depuis Internet.

L'ordre des directives Caddy place `respond` avant `reverse_proxy`, donc une requete bloquee ne touche jamais le backend.

### Consequences

- Le flag est **opt-in** (`default(false)`) : les backends existants (`proxmox`, `vpngate`, `kandidat`) ne changent pas de comportement.
- L'administration du portail n'est plus possible depuis Internet — il faut passer par le VPN WireGuard. C'est le comportement voulu.
- Le filtrage repose sur l'IP source vue par Caddy. Il reste correct tant que le port forwarding de la box fait du DNAT sans proxy intermediaire. Si un CDN ou un proxy amont etait ajoute devant Caddy, toutes les requetes arriveraient avec l'IP du proxy et il faudrait basculer sur `trusted_proxies` + `X-Forwarded-For`.
- Le test depuis le LAN ne valide que le cas passant ; verifier le 403 demande une source publique reelle (4G, host externe).

------

## ADR-006 : HTTPS interne opt-in par backend

| | |
|---|---|
| **Date** | 2026-08-24 |
| **Statut** | Accepte — **remplace ADR-001** |
| **Decideurs** | xgueret |

### Contexte

ADR-001 (2026-03-27) tranchait « HTTP only, pas de TLS » : le tunnel WireGuard couvrait deja le transport, et sans nom de domaine public il n'existait aucun moyen d'obtenir un certificat sans warning navigateur.

Trois choses ont change depuis :

1. **Des applications avec un besoin reel de TLS sont arrivees derriere Caddy.** `portail-client` pose un cookie de session `Secure` (login par magic-link) qui ne fonctionne pas en HTTP ; `hermes` demande des identifiants sur son dashboard ; `kandidat` expose des CV, des contacts et une cle d'API LLM. Le chiffrement s'arretait au VPN alors que ces flux traversent encore le LAN en clair jusqu'au navigateur.
2. **Le cout de maintenance invoque par ADR-001 n'existe pas.** `tls internal` fait emettre **et renouveler** les certificats par la CA locale de Caddy, sans intervention. Il n'y a pas de « rotation a gerer ».
3. **Le warning navigateur est evitable.** Importer la CA root de Caddy dans le magasin de confiance du client le supprime — une operation ponctuelle par machine, documentee dans `caddy/docs/runbook-https-internal.md`.

Dans les faits la decision avait deja derive : `tls_internal: true` etait en place sur `proxmox`, `kandidat`, `portail-client` et `hermes`. ADR-001 ne decrivait plus l'etat du systeme.

### Decision

**Remplacer « HTTP only » par un HTTPS interne opt-in par backend, pilote par le flag `tls_internal` dans `caddy_backends`.**

- Par defaut (flag absent), un backend reste servi en HTTP sur `:80` — c'est le comportement historique, inchange.
- Le flag est active sur les backends qui manipulent des identifiants ou des donnees personnelles.
- Caddy sert alors le vhost avec sa **CA locale** et redirige automatiquement `:80` vers `:443`.

> 💡 **Note** : `.internal` est un TLD reserve (RFC 6761 / RFC 8375). **Aucune CA publique n'emettra jamais** pour ces noms — la CA locale de Caddy n'est pas un repli faute de mieux, c'est la seule option techniquement possible. Le cas d'un vrai certificat Let's Encrypt est traite separement, sur un nom public (`portail-client.tipunchlabs.fr`, ACME DNS-01 OVH).

Etat au 2026-08-24 :

| Mode | Backends |
|---|---|
| **HTTPS** (`tls_internal: true`) | `proxmox`, `kandidat`, `portail-client`, `hermes` |
| **HTTP** (defaut) | `vpngate`, `portainer`, `pihole`, `openwebui`, `excalidraw`, `komodo`, `miniboard` |
| **HTTPS public** (`tls_public`, ACME DNS-01 OVH) | `portail-client.tipunchlabs.fr` |

### Justification

```
   ADR-001 (2026-03)                    ADR-006 (2026-08)

   navigateur ──clair──┐                navigateur ──TLS──┐
                       │                                  │
            [ tunnel WireGuard ]              [ tunnel WireGuard ]
                       │                                  │
                    Caddy:80                          Caddy:443
                                                    (CA locale)
```

Le VPN protege le transport **entre deux machines**. Il ne protege pas le segment navigateur → Caddy une fois le paquet arrive sur le LAN, ni contre un poste compromis sur ce meme LAN. Pour un dashboard sans authentification, c'est sans consequence ; pour un cookie de session ou une cle d'API, ca ne l'est pas.

| Critere | HTTPS opt-in (choisi) | HTTP only (ADR-001) | HTTPS partout |
|---------|----------------------|---------------------|---------------|
| Cookies `Secure` / login | Fonctionnent la ou c'est necessaire | **Bloquants** — `portail-client` inutilisable | Fonctionnent |
| Confidentialite sur le LAN | Assuree sur les flux sensibles | Aucune apres le VPN | Assuree partout |
| Import de CA sur les clients | Requis, mais une fois par machine | Aucun | Requis |
| Cout de maintenance | Nul (renouvellement auto) | Nul | Nul |
| Surface de casse | Limitee aux 4 vhosts flagges | N/A | Tous les vhosts, y compris ceux consommes par des scripts |
| Granularite | Par backend, decision explicite | N/A | Aucune |

L'opt-in est prefere au « HTTPS partout » parce que le cout de la bascule n'est pas dans Caddy mais **chez les clients** : chaque runtime qui consomme une URL `.internal` avec son propre magasin de CA doit etre ajuste. Basculer un vhost consomme par un script sans le savoir casse le script. On paie ce cout la ou il achete quelque chose.

### Consequences

- Le Caddyfile n'a **plus** de `auto_https off` global. Les vhosts HTTP sont exprimes par une adresse explicite `domain:80`, ce qui suffit a desactiver l'HTTPS automatique pour eux seuls.
- ADR-003 (`tls_insecure_skip_verify` pour Proxmox) reste valide et **independant** : il concerne le lien Caddy → upstream, pas le lien client → Caddy.
- **La distribution de la CA root n'est pas automatisee.** Aucun role Ansible ne l'installe sur les postes clients ; c'est une procedure manuelle (`runbook-https-internal.md`, etape 3). C'est le principal point de friction de cette decision.
- **Une reinstallation de la PKI de Caddy invalide tous les clients.** Si `/var/lib/caddy/.local/share/caddy/pki` est efface (rebuild du LXC, reset de volume), Caddy genere une **nouvelle** CA root et chaque client tombe en `ERR_CERT_AUTHORITY_INVALID` jusqu'a reimport. C'est deja arrive une fois : le poste de travail porte deux roots (`Caddy Local Authority - 2025 ECC Root` et `- 2026 ECC Root`).
- **Les runtimes qui embarquent leur propre bundle de CA ignorent le magasin systeme.** Node en est l'exemple vivant : la cible `mcp-prod` du Makefile de `kandidat` doit passer `NODE_OPTIONS=--use-system-ca` pour joindre `https://kandidat.internal`. Meme classe de probleme pour Python (`certifi`), Firefox (magasin propre, import separe) et tout conteneur qui appelle un `.internal` en HTTPS.
- Ajouter un backend au HTTPS interne reste une modification d'une ligne dans `group_vars` suivie de `ansible-playbook ansible/deploy.yml --tags caddy`.

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
