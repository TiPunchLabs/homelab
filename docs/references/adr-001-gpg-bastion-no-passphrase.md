# 📋 ADR-001 : GPG Key sans passphrase pour le bastion

> **Status** : Accepted
> **Date** : 2026-03-06
> **Decideurs** : Xavier Gueret

------

## 🎯 Contexte

Le bastion-60 centralise l'execution des playbooks Ansible et des commandes Terraform pour l'ensemble du homelab. Il utilise `pass` (password-store) pour stocker le mot de passe Ansible Vault, ce qui permet de dechiffrer les secrets de maniere transparente lors des deploiements.

`pass` repose sur GPG pour le chiffrement/dechiffrement. En mode interactif (SSH humain), une cle GPG avec passphrase fonctionne normalement. En mode non-interactif (CI pipeline, commande SSH one-shot), le prompt de passphrase bloque l'execution.

------

## 🧠 Mental Model

```
AVEC passphrase :
  CI runner → ssh bastion → pass show → gpg --decrypt → PROMPT PASSPHRASE → BLOQUE

SANS passphrase :
  CI runner → ssh bastion → pass show → gpg --decrypt → secret retourne → ansible-playbook OK
```

------

## 🔀 Alternatives evaluees

### Option A : Cle GPG dediee SANS passphrase (retenue)

La cle GPG du bastion n'a pas de passphrase. Elle est dediee a cet usage et ne quitte jamais le bastion.

| Critere | Evaluation |
|---------|------------|
| Simplicite | Excellente - aucune config supplementaire |
| Compatibilite CI | Totale - fonctionne en mode non-interactif |
| Surface d'attaque | Limitee - cle dediee, usage unique |
| Maintenance | Nulle - pas de token/session a renouveler |

### Option B : Passphrase + gpg-preset-passphrase

Garder une passphrase mais la pre-charger dans le gpg-agent au demarrage du bastion via `gpg-connect-agent PRESET_PASSPHRASE`.

| Critere | Evaluation |
|---------|------------|
| Simplicite | Moyenne - config gpg-agent + systemd service |
| Compatibilite CI | Bonne - mais depend du gpg-agent running |
| Surface d'attaque | Reduite - passphrase en memoire seulement |
| Maintenance | Moyenne - gpg-agent peut crash, timeouts a gerer |

**Rejet** : complexite disproportionnee pour un homelab. Le gpg-agent peut expirer ou crasher, ajoutant un point de defaillance.

### Option C : Passphrase injectee via variable d'environnement

Passer la passphrase GPG via `GPG_PASSPHRASE` env var et utiliser `--pinentry-mode loopback --passphrase-fd`.

| Critere | Evaluation |
|---------|------------|
| Simplicite | Moyenne - config pinentry + env var |
| Compatibilite CI | Bonne - via SSH SendEnv |
| Surface d'attaque | Variable - passphrase transitee en env var |
| Maintenance | Faible |

**Rejet** : la passphrase transite en variable d'environnement (visible dans `/proc/*/environ`), ce qui annule l'avantage securitaire.

### Option D : Vault externe (HashiCorp Vault, AWS Secrets Manager)

Remplacer `pass` par un gestionnaire de secrets centralise.

| Critere | Evaluation |
|---------|------------|
| Simplicite | Faible - infrastructure supplementaire |
| Compatibilite CI | Excellente |
| Surface d'attaque | Minimale |
| Maintenance | Elevee - un service de plus a operer |

**Rejet** : over-engineering pour un homelab personnel. Introduit une dependance reseau et un SPOF supplementaire.

------

## ✅ Decision

**Option A retenue** : cle GPG dediee sans passphrase, avec les mesures compensatoires suivantes.

------

## 🔐 Mesures compensatoires

La cle GPG sans passphrase est acceptable dans ce contexte grace aux protections suivantes :

### Isolation de la cle
- **Cle dediee** : `162B177E2392A1B19F2F9E891ECA38AD56C66998` (Bastion Homelab)
- **Usage unique** : chiffrer/dechiffrer le password-store du bastion
- **Pas de reutilisation** : cette cle n'est utilisee pour rien d'autre (pas de signature, pas d'email)
- **Separee de la cle personnelle** : la cle Xavier Gueret (avec passphrase) reste pour l'usage personnel

### Protection du transport
- La cle privee est stockee **dans un vault Ansible chiffre** (`vault/config.yml`)
- Le vault est chiffre par un mot de passe gere via `pass` sur le workstation
- La cle privee n'est **jamais en clair** dans le repo Git

### Protection du bastion
- **SSH hardened** : authentification par cle uniquement, root login desactive
- **UFW actif** : seul le port 22 est ouvert
- **Acces restreint** : seul l'utilisateur `ansible` peut se connecter
- **Reseau local** : le bastion n'est pas expose sur Internet

### Principe du moindre privilege
- La cle GPG ne peut dechiffrer que le password-store local
- Le password-store ne contient qu'un seul secret (`ansible/vault`)
- Meme si la cle GPG est compromise, l'attaquant n'obtient que le mot de passe Ansible Vault
- Pour exploiter ce mot de passe, il faut aussi avoir acces au repo et aux fichiers vault chiffres

------

## 🔄 Conditions de revision

Cette decision devrait etre re-evaluee si :

- Le bastion est expose sur Internet (VPN, port forwarding)
- Plusieurs utilisateurs accedent au bastion
- Le password-store contient des secrets a haute criticite (production, donnees clients)
- Un vault externe est deploye dans le homelab pour d'autres usages

------

## 📚 References

- [pass - the standard unix password manager](https://www.passwordstore.org/)
- [GnuPG - gpg-preset-passphrase](https://www.gnupg.org/documentation/manuals/gnupg/gpg_002dpreset_002dpassphrase.html)
- [Incident SSH cloud-init 2026-02-26](../../homelab-docs/incidents/2026-02-26-ssh-cloud-init-regression.md)

> **Document created on** : 2026-03-06
> **Author** : Xavier Gueret
> **Version** : 1.0
