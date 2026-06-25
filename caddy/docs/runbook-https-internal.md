# 🔐 Runbook — Passer les URLs `.internal` en HTTPS

> **Objectif** : basculer un ou plusieurs backends Caddy de HTTP vers HTTPS (CA interne Caddy), de façon idempotente via Ansible.
> **Prérequis** : accès SSH au LXC `caddy-70` (192.168.1.70), repo `homelab/` à jour, VPN WireGuard actif.
> **Durée** : ~5 min config + 1 import de CA root par machine cliente.

------

## 🧠 Mental Model

```
                    AVANT (HTTP)                         APRÈS (HTTPS)
  service.internal:80  ──HTTP──>  Caddy        service.internal  ──HTTPS──>  Caddy
                                    │            (tls internal)     │
                                    └─HTTP/HTTPS─> upstream         └──> upstream (inchangé)
```

Le flag `tls_internal: true` dans `group_vars` est le **seul interrupteur**. Le template
`Caddyfile.j2` fait le reste :

| `tls_internal` | Bloc généré | Écoute |
|---|---|---|
| absent / `false` | `domain:80 { ... }` | **HTTP** (port 80) |
| `true` | `domain { tls internal ... }` | **HTTPS** (CA interne Caddy) |

> 💡 **Note** : `tls internal` ≠ `tls_insecure_skip_verify`.
> - `tls_internal` → Caddy **sert** le site en HTTPS (front, côté client).
> - `tls_insecure_skip_verify` → Caddy **accepte** un upstream HTTPS auto-signé (back, côté upstream). Indépendants.

------

## 🛠️ Étape 1 — Activer le flag par backend

Fichier : `caddy/ansible/group_vars/caddy/all/main.yml`

Ajouter `tls_internal: true` au(x) backend(s) voulu(s). Exemple pour tout basculer :

```yaml
caddy_backends:
  - name: kandidat
    domain: kandidat.internal
    upstream: http://192.168.10.90:8000
    tls_internal: true          # <— ajouter cette ligne
  - name: portainer
    domain: portainer.internal
    upstream: http://192.168.10.90:9000
    tls_internal: true          # <— idem sur chaque backend
  # ... etc
```

> ⚠️ **Warning** : les backends `proxmox` et `portail-client` sont **déjà** en `tls_internal: true`. Ne pas les dupliquer.

------

## 🚀 Étape 2 — Déployer

```bash
cd caddy
ansible-playbook ansible/deploy.yml --tags caddy
```

Caddy recharge à chaud, génère les certificats avec sa CA interne et sert les domaines en HTTPS. Idempotent : relançable sans effet de bord.

------

## 📜 Étape 3 — Faire confiance à la CA interne de Caddy (clients)

Sans ça : avertissement TLS dans le navigateur (cert signé par une CA inconnue). À faire **une fois par machine cliente**.

### 3.1 Récupérer le certificat root depuis le LXC

```bash
# Depuis ton poste (VPN actif)
scp ansible@192.168.1.70:/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt ./caddy-root.crt
```

> 💡 Le chemin exact peut varier selon la version/installation. Vérifier au besoin :
> `ssh ansible@192.168.1.70 'find /var/lib/caddy -name root.crt'`

### 3.2 Importer dans le magasin de confiance

**Linux (Debian/Ubuntu) :**
```bash
sudo cp caddy-root.crt /usr/local/share/ca-certificates/caddy-internal.crt
sudo update-ca-certificates
```

**Firefox** (magasin propre) : `Paramètres → Vie privée & sécurité → Certificats → Voir les certificats → Autorités → Importer` → cocher « confiance pour les sites web ».

**macOS :**
```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain caddy-root.crt
```

**Windows (PowerShell admin) :**
```powershell
Import-Certificate -FilePath .\caddy-root.crt -CertStoreLocation Cert:\LocalMachine\Root
```

------

## 🔧 Troubleshooting

| Symptôme | Cause probable | Action |
|---|---|---|
| `ERR_CERT_AUTHORITY_INVALID` | CA root non importée sur le client | Refaire l'étape 3 |
| Toujours en HTTP après deploy | `tls_internal` non pris en compte | Vérifier l'indentation YAML ; relancer `--tags caddy` |
| `502 Bad Gateway` | upstream injoignable | `tls_internal` n'affecte que le front ; vérifier l'upstream/port |
| Upstream HTTPS auto-signé KO | manque skip-verify côté back | Ajouter `tls_insecure_skip_verify: true` (≠ `tls_internal`) |
| Cert root introuvable sur le LXC | chemin/installation différents | `find /var/lib/caddy -name root.crt` |

------

## ✅ Checklist

- [ ] `tls_internal: true` ajouté aux backends voulus dans `group_vars/caddy/all/main.yml`
- [ ] `ansible-playbook ansible/deploy.yml --tags caddy` exécuté sans erreur
- [ ] CA root récupérée depuis `caddy-70`
- [ ] CA root importée sur chaque machine cliente
- [ ] Accès `https://<service>.internal` sans warning TLS

------

## 🎓 Rappel — pourquoi ce n'est PAS le défaut

Stratégie actuelle : **HTTP par défaut, HTTPS seulement si requis**. Le transport est déjà chiffré par le VPN WireGuard (vpngate-50) sur un LAN privé. `tls_internal` n'est activé que là où l'app l'**exige** fonctionnellement (ex. `portail-client` : cookie de session `Secure` pour le login magic-link). Passer tout en HTTPS est cosmétique/défense-en-profondeur, pas une nécessité réseau.

------

> **Document créé le** : 2026-06-22
> **Auteur** : Xavier Gueret
> **Version** : 1.0
