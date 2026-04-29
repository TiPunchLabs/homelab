# 🔐 Guide : Configurer un client WireGuard Linux via wg-easy

> **Prerequis** :
> - Acces a l'interface web wg-easy (`http://192.168.10.50:51821`)
> - Connexion au reseau local ou VPN existant pour acceder a wg-easy
> - Distribution Linux (Ubuntu, Debian, Fedora, Arch)

> **Duree estimee** : 5 minutes

------

## 📖 Introduction

Ce guide explique comment configurer un client WireGuard sur Linux a partir du fichier de configuration genere par wg-easy (interface web hebergee sur vpngate-50).

### Mental Model

```
┌──────────┐                          ┌────────────┐
│  Laptop  │  ── tunnel WireGuard ──► │ vpngate-50 │ ──► LAN 192.168.10.0/24
│ (client) │     UDP :51820           │ (serveur)  │
└──────────┘                          └────────────┘
     │                                      │
     │  DNS → 192.168.10.71 (Pi-hole)        │
     │  IP  → 10.0.0.x (tunnel)             │
     └──────────────────────────────────────-┘
```

------

## 🏗️ Chapter 1 : Installer WireGuard

### 1.1 Ubuntu / Debian

```bash
sudo apt update && sudo apt install wireguard resolvconf -y
```

### 1.2 Fedora

```bash
sudo dnf install wireguard-tools -y
```

### 1.3 Arch Linux

```bash
sudo pacman -S wireguard-tools
```

> 💡 **Note** : `resolvconf` est necessaire sur Ubuntu/Debian pour que WireGuard puisse configurer le DNS automatiquement. Sur Fedora/Arch, `systemd-resolved` s'en charge.

------

## 🏗️ Chapter 2 : Telecharger la configuration depuis wg-easy

### 2.1 Acceder a l'interface web

Ouvrir dans un navigateur :

```
http://192.168.10.50:51821
```

Se connecter avec le mot de passe administrateur.

### 2.2 Creer un client

1. Cliquer sur **"+ New"**
2. Donner un nom au client (ex: `laptop-linux`)
3. Le client apparait dans la liste

### 2.3 Telecharger le fichier de configuration

1. Cliquer sur l'icone **Download** (fleche vers le bas) a cote du client cree
2. Sauvegarder le fichier `.conf` (ex: `laptop-linux.conf`)

Le fichier telecharge ressemble a ceci :

```ini
[Interface]
PrivateKey = <cle_privee_generee>
Address = 10.0.0.X/32
DNS = 192.168.10.71

[Peer]
PublicKey = <cle_publique_serveur>
PresharedKey = <cle_partagee>
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = <ip_publique>:51820
```

> 💡 **Note** : Le champ `DNS` pointe vers `192.168.10.71` (Pi-hole dns-71), qui resout les domaines `.internal` et filtre les publicites.

------

## 🏗️ Chapter 3 : Installer la configuration

### 3.1 Copier le fichier

```bash
sudo cp ~/Downloads/laptop-linux.conf /etc/wireguard/wg0.conf
sudo chmod 600 /etc/wireguard/wg0.conf
```

> ⚠️ **Warning** : Le fichier contient la cle privee du client. Les permissions `600` (lecture seule root) sont indispensables.

### 3.2 Verifier la configuration

```bash
sudo cat /etc/wireguard/wg0.conf
```

Verifier que les champs `Endpoint`, `Address` et `DNS` sont corrects.

------

## 🏗️ Chapter 4 : Connexion et gestion

### 4.1 Connexion manuelle

```bash
# Activer le tunnel
sudo wg-quick up wg0

# Verifier le statut
sudo wg show

# Desactiver le tunnel
sudo wg-quick down wg0
```

### 4.2 Connexion automatique au demarrage

```bash
# Activer le service systemd
sudo systemctl enable wg-quick@wg0

# Demarrer immediatement
sudo systemctl start wg-quick@wg0

# Verifier le statut
sudo systemctl status wg-quick@wg0
```

### 4.3 Verifier la connectivite

```bash
# Ping vers le serveur VPN
ping -c 3 192.168.10.50

# Verifier la resolution DNS .internal
dig proxmox.internal @192.168.10.71

# Tester l'acces a un service
curl -s http://kandidat.internal
```

------

## 🔧 Troubleshooting

| Probleme | Cause probable | Solution |
|----------|---------------|----------|
| `RTNETLINK answers: Operation not permitted` | Module kernel manquant | `sudo modprobe wireguard` |
| DNS ne resout pas `.internal` | Tunnel non actif ou resolvconf manquant | Verifier `wg show` et installer `resolvconf` |
| `Handshake did not complete` | Endpoint injoignable ou cles incorrectes | Verifier l'IP publique et le port 51820/UDP |
| Pas d'acces au LAN (192.168.10.x) | `AllowedIPs` mal configure | Verifier que `0.0.0.0/0` est present dans la config |
| DNS lent ou timeout | Pi-hole dns-71 inaccessible | `ping 192.168.10.71` — verifier que le LXC tourne |

------

## ✅ Checklist

- [ ] WireGuard installe (`wg --version`)
- [ ] Fichier `.conf` telecharge depuis wg-easy
- [ ] Configuration copiee dans `/etc/wireguard/wg0.conf` (permissions 600)
- [ ] Tunnel actif (`sudo wg show` montre un handshake recent)
- [ ] DNS `.internal` fonctionne (`dig proxmox.internal`)
- [ ] Service systemd active si connexion automatique souhaitee

------

## 📚 Resources

- [WireGuard — Documentation officielle](https://www.wireguard.com/)
- [wg-easy — GitHub](https://github.com/wg-easy/wg-easy)
- [Pi-hole — Documentation](https://docs.pi-hole.net/)

------

> **Document created on** : 2026-03-30
> **Author** : xgueret
> **Version** : 1.0
