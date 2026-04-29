# 🛠️ Reconfigurer une VM Proxmox via l'agent QEMU (sans console)

> **Objectif** : exécuter des commandes shell et réécrire des fichiers à l'intérieur d'une VM **sans avoir besoin de la console noVNC ni de SSH**, en passant par le canal QEMU Guest Agent (QGA).
>
> **Quand l'utiliser** : VM injoignable réseau (changement IP, mauvais netplan, firewall qui se referme sur lui-même), pas de mot de passe utilisateur set, ou simplement pour automatiser une opération de masse depuis l'hôte Proxmox.
>
> **Prérequis** :
> - `qemu-guest-agent` installé et démarré dans la VM
> - Option "QEMU Guest Agent" cochée sur la VM côté Proxmox
> - Accès SSH (ou local) à l'hôte Proxmox avec sudo
>
> **Durée de lecture** : ~10 minutes
>
> **Auteur** : Xavier Gueret
> **Version** : 1.0

## 📖 Mental Model

```
┌─────────────────────────────────────────────────────────────┐
│                     HÔTE PROXMOX (pve)                      │
│                                                             │
│   ┌──────────────┐  qm guest exec  ┌──────────────────┐    │
│   │  qm CLI      │ ───────────────▶│  socket QGA      │    │
│   │  (root)      │                 │  /var/run/qga/X  │    │
│   └──────────────┘                 └────────┬─────────┘    │
│                                             │              │
│   ─────────────────────────────────────── virtio ─────────│
│                                             │              │
│   ┌─────────────────────────────────────────▼──────────┐   │
│   │              VM (Ubuntu, etc.)                     │   │
│   │  ┌──────────────────────────┐                      │   │
│   │  │ qemu-guest-agent (root)  │  exécute en root     │   │
│   │  └──────────────┬───────────┘                      │   │
│   │                 │                                  │   │
│   │  $ /bin/sh -c "ip a"  ← n'importe quelle commande  │   │
│   └────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

> **Analogie** : QGA, c'est comme si Proxmox avait planté un cordon ombilical privilégié dans la VM, indépendant de la pile réseau. Quand le réseau est cassé (ou volontairement coupé pour reconfiguration), le cordon reste vivant.

> ⚠️ **Sécurité** : QGA exécute les commandes **en root** dans la VM, sans authentification. Quiconque a accès à `qm` sur l'hôte Proxmox peut faire n'importe quoi dans toutes les VMs. Le contrôle d'accès se fait au niveau Proxmox, pas au niveau VM.

------

## 🎯 Cas d'usage typiques

| Situation | Pourquoi QGA est la bonne réponse |
|---|---|
| Changement de plage IP (gateway/subnet) | Le réseau VM est cassé, pas de SSH, console pénible |
| `ufw` qui s'est refermé sur la session SSH | Sortir d'une impasse sans avoir à booter en single-user |
| Bascule en masse de N VMs identiques | Scriptable depuis le pve, pas N consoles à ouvrir |
| Pas de mot de passe utilisateur dans la VM | Login console impossible — QGA contourne |
| Récupération de logs / état système | `journalctl`, `systemctl status` sans réseau |

------

## 🏗️ Chapitre 1 : Vérifier la disponibilité de l'agent

### 1.1 🩺 Ping de l'agent

```bash
# Sur l'hôte Proxmox
sudo qm agent <VMID> ping
```

- **Pas d'output, exit code 0** → agent OK, VM réceptive
- **Erreur "QEMU guest agent is not running"** → agent absent ou option non cochée

### 1.2 🔧 Si l'agent est absent

Côté Proxmox (UI ou CLI) :
```bash
sudo qm set <VMID> --agent enabled=1
```

Puis dans la VM (si tu peux y accéder, console ou SSH) :
```bash
sudo apt install -y qemu-guest-agent
sudo systemctl enable --now qemu-guest-agent
```

> 💡 **Bonne pratique** : intégrer `qemu-guest-agent` dans le template cloud-init, comme ça toutes les VMs créées l'ont déjà.

------

## 🏗️ Chapitre 2 : Exécuter une commande simple

### 2.1 ⚡ Syntaxe de base

```bash
sudo qm guest exec <VMID> -- <commande> [args...]
```

Le binaire et les arguments sont passés **séparément** (pas via shell).

### 2.2 Exemples lecture

```bash
# Lire l'IP de la VM
sudo qm guest exec 9090 -- /bin/ip -4 addr show eth0

# Lire un fichier
sudo qm guest exec 9090 -- /bin/cat /etc/netplan/50-cloud-init.yaml

# Lister les services
sudo qm guest exec 9090 -- /bin/systemctl is-active docker
```

### 2.3 📤 Format de sortie

QGA renvoie un JSON :

```json
{
   "exitcode" : 0,
   "exited" : 1,
   "out-data" : "    inet 192.168.10.90/24 brd 192.168.10.255 scope global eth0\n"
}
```

- `exited: 1` = la commande s'est terminée (pas un timeout)
- `exitcode: 0` = succès
- `out-data` = stdout
- `err-data` = stderr (si présent)

### 2.4 ⏱️ Timeouts

```bash
# Augmenter le timeout pour les commandes longues
sudo qm guest exec 9090 --timeout 60 -- /usr/sbin/netplan apply
```

Default : 30 secondes.

------

## 🏗️ Chapitre 3 : Pipes, redirections, scripts

### 3.1 🔀 Le piège des arguments

Comme QGA passe les args séparément, **les `>`, `|`, `&&` ne sont pas interprétés** :

```bash
# ❌ MAUVAIS — '>' est passé comme literal à echo
sudo qm guest exec 9090 -- /bin/echo "hello" > /tmp/test.txt

# ✅ BON — wrapper dans sh -c
sudo qm guest exec 9090 -- /bin/sh -c 'echo "hello" > /tmp/test.txt'
```

### 3.2 💡 Pattern : commande composée

```bash
sudo qm guest exec 9090 -- /bin/sh -c '
  cd /etc/netplan
  ls -la
  cat 50-cloud-init.yaml
'
```

------

## 🏗️ Chapitre 4 : Écrire un fichier dans la VM

QGA n'a pas de commande `file-write` directe (sur les versions récentes elle peut exister mais reste capricieuse). La méthode robuste : **base64 + decode dans la VM**.

### 4.1 🎯 Pattern complet

```bash
# 1. Préparer le contenu côté hôte
cat <<'EOF' > /tmp/payload.txt
ligne 1
ligne 2 avec "guillemets" et 'apostrophes'
ligne 3 avec $variables qui ne doivent pas être interprétées
EOF

# 2. Encoder en base64 (sans wrap)
PAYLOAD_B64=$(base64 -w0 < /tmp/payload.txt)

# 3. Décoder dans la VM
sudo qm guest exec 9090 -- /bin/sh -c "echo $PAYLOAD_B64 | base64 -d > /etc/some/file.conf"
```

### 4.2 🛡️ Pourquoi base64

- Évite tous les problèmes d'échappement (guillemets, backticks, dollars, retours ligne, UTF-8…)
- Marche même avec du contenu binaire
- Lisible et reproductible

### 4.3 📝 Vérifier ce qu'on a écrit

```bash
sudo qm guest exec 9090 -- /bin/cat /etc/some/file.conf
```

------

## 🏗️ Chapitre 5 : Cas concret — bascule réseau in-place

Scénario : la VM `dockhost-90` est en `192.168.1.90`, le subnet est mort, il faut la passer en `192.168.10.90` sans console.

### 5.1 📥 Lire la conf actuelle (pour préserver la structure)

```bash
sudo qm guest exec 9090 -- /bin/cat /etc/netplan/50-cloud-init.yaml
```

Note la `macaddress`, le nom d'interface, les `nameservers`, etc.

### 5.2 ✏️ Préparer la nouvelle conf

```bash
cat <<'EOF' > /tmp/dockhost-netplan.yaml
network:
  version: 2
  ethernets:
    eth0:
      match:
        macaddress: "bc:24:11:3d:fa:d2"
      addresses:
      - "192.168.10.90/24"
      nameservers:
        addresses:
        - 1.1.1.1
        - 8.8.8.8
        search:
        - local
      set-name: "eth0"
      routes:
      - to: "default"
        via: "192.168.10.1"
EOF

NETPLAN_B64=$(base64 -w0 < /tmp/dockhost-netplan.yaml)
```

### 5.3 🚫 Désactiver l'override cloud-init

Cloud-init réécrit `/etc/netplan/` au boot suivant si on ne le désactive pas — la nouvelle config se ferait écraser :

```bash
sudo qm guest exec 9090 -- /bin/sh -c \
  'echo "network: {config: disabled}" > /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg'
```

### 5.4 📤 Pousser le netplan

```bash
sudo qm guest exec 9090 -- /bin/sh -c \
  "echo $NETPLAN_B64 | base64 -d > /etc/netplan/50-cloud-init.yaml && chmod 600 /etc/netplan/50-cloud-init.yaml"
```

> ⚠️ Le `chmod 600` est demandé par les versions récentes de netplan (warning sur les permissions sinon).

### 5.5 🔄 Appliquer et vérifier

```bash
sudo qm guest exec 9090 --timeout 30 -- /bin/sh -c \
  '/usr/sbin/netplan apply 2>&1; sleep 3; ip -4 addr show eth0 | grep inet; ip route | grep default'
```

Le `sleep 3` laisse le temps à netplan d'établir la nouvelle interface avant d'afficher l'état.

### 5.6 ✅ Test connectivité depuis l'hôte / le laptop

```bash
ping -c 2 192.168.10.90
ssh-keygen -R 192.168.1.90  # nettoyer l'ancien fingerprint
ssh dockhost-90 "hostname && ip -4 addr show eth0 | grep inet"
```

------

## 🏗️ Chapitre 6 : Différences VM vs LXC

QGA n'existe **que pour les VMs**. Pour les LXC, on utilise une autre voie : `pct exec` et `pct set`, qui ne nécessitent pas d'agent (l'hôte Proxmox a un accès direct au namespace du conteneur).

### 6.1 LXC : reconfigurer l'IP réseau

```bash
# Lire la conf
sudo pct config 1070 | grep ^net0

# Modifier
sudo pct set 1070 -net0 \
  "name=eth0,bridge=vmbr0,hwaddr=BC:24:11:0B:8E:BE,ip=192.168.10.70/24,gw=192.168.10.1,type=veth"

# Reboot
sudo pct reboot 1070

# Vérifier
sudo pct exec 1070 -- ip -4 addr show eth0
```

### 6.2 LXC : exécuter une commande

```bash
sudo pct exec 1070 -- systemctl status caddy
```

Pas de wrapper `sh -c` nécessaire pour les pipes : `pct exec` passe par `nsenter`, donc tu as un shell complet par défaut si tu enchaînes avec `sh -c '...'` quand même.

------

## 🔧 Troubleshooting

| Symptôme | Cause probable | Action |
|---|---|---|
| `QEMU guest agent is not running` | Agent absent ou option Proxmox non cochée | `qm set <VMID> --agent enabled=1` puis installer qemu-guest-agent dans la VM |
| `QEMU guest agent timeout` sur une commande longue | Default 30s dépassé | `--timeout 60` (ou plus) |
| `out-data` vide alors que la commande fait quelque chose | stdout n'a peut-être rien produit, vérifier `err-data` | Forcer un `2>&1` dans le `sh -c` |
| Caractères mangés dans le `out-data` | Échappement shell mal fait | Passer en mode base64 (chapitre 4) |
| Au prochain reboot, ma config réseau est revenue à l'ancienne | Cloud-init a réécrit netplan | Désactiver via `99-disable-network-config.cfg` (chapitre 5.3) |

------

## ✅ Checklist d'opération in-place

Avant de toucher quoi que ce soit :
- [ ] Snapshot Proxmox de la VM (rollback sûr) : `sudo qm snapshot <VMID> avant-modif`
- [ ] L'agent répond : `sudo qm agent <VMID> ping`
- [ ] La conf actuelle est lue et notée

Pendant l'opération :
- [ ] Désactivation cloud-init (si modif réseau)
- [ ] Modif via base64 pour éviter les surprises d'échappement
- [ ] Validation interne (depuis la VM via QGA) avant d'attendre le réseau

Après :
- [ ] Test de connectivité depuis l'hôte
- [ ] Test SSH depuis le client final
- [ ] Si tout va bien : `sudo qm delsnapshot <VMID> avant-modif` (le snapshot consomme du disque)

------

## 🎓 Conclusion

QGA transforme l'agent invité en **canal de contrôle out-of-band**, indépendant de la pile réseau. C'est l'outil de choix pour :
- Reconfigurer un réseau cassé
- Automatiser des opérations VM-par-VM sans console
- Récupérer une situation d'erreur sans booter en mode single-user

Pour les LXC, le même esprit s'applique avec `pct exec` / `pct set`, sans avoir besoin d'un agent — le conteneur est par définition transparent depuis l'hôte.

------

## 📚 Ressources

- [Proxmox VE — qm man page](https://pve.proxmox.com/pve-docs/qm.1.html)
- [Proxmox VE — pct man page](https://pve.proxmox.com/pve-docs/pct.1.html)
- [QEMU Guest Agent reference](https://wiki.qemu.org/Features/GuestAgent)
- [Netplan — disable cloud-init network config](https://cloudinit.readthedocs.io/en/latest/reference/network-config.html#disabling-network-configuration)

> **Document créé le** : 2026-04-28
> **Auteur** : Xavier Gueret
> **Version** : 1.0
