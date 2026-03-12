# 🔧 Mode Operatoire : Execution distante depuis le Bastion

> **Objectif** : Valider que le bastion-60 peut executer des playbooks Ansible sur les VMs cibles (dockhost-90, kubecluster-*) de maniere autonome et non-interactive.
>
> **Prerequis** :
> - Bastion-60 provisionne et accessible (`ssh bastion-60`)
> - Roles deployes : motd, security_hardening, tooling, ssh_keys
> - GPG/pass fonctionnel (`pass show ansible/vault` retourne le mot de passe)

------

## 🧠 Mental Model

```
                    +-----------------+
                    |   Workstation   |
                    |  (192.168.1.X)  |
                    +--------+--------+
                             | ssh
                             v
                    +-----------------+
                    |   bastion-60    |
                    |  192.168.1.60   |
                    |                 |
                    |  ~/homelab/     |
                    |  uv + ansible   |
                    |  pass + gpg     |
                    |  ssh keys       |
                    +---+----+----+---+
                        |    |    |
                ssh     |    |    |    ssh
              +---------+    |    +---------+
              v              v              v
        +-----------+  +-----------+  +-----------+
        | dockhost  |  | kubecluster| | kubecluster|
        |    -50    |  |    -40     | |  -41/-42   |
        +-----------+  +-----------+  +-----------+
```

------

## 📝 Etape 1 : Verification des prerequis sur le bastion

Se connecter au bastion et verifier que tout est en place.

```bash
# Depuis le workstation
ssh bastion-60
```

### 1.1 Verifier les outils

```bash
# Ansible disponible via uv
cd ~/homelab
uv run ansible --version

# Terraform installe
terraform --version

# GPG key dediee bastion (sans passphrase)
gpg --list-keys "Bastion Homelab"

# pass fonctionnel (doit retourner le mot de passe sans prompt)
pass show ansible/vault
```

### 1.2 Verifier la connectivite SSH vers les cibles

```bash
# Dockhost
ssh -o BatchMode=yes dockhost-90 "hostname && uptime"

# Kubecluster control plane
ssh -o BatchMode=yes kubecluster-40 "hostname && uptime"

# Kubecluster workers
ssh -o BatchMode=yes kubecluster-41 "hostname && uptime"
ssh -o BatchMode=yes kubecluster-42 "hostname && uptime"
```

> **Note** : `-o BatchMode=yes` force le mode non-interactif. Si ca echoue, la cle SSH n'est pas correcte.

------

## 📝 Etape 2 : Test dry-run d'un playbook dockhost

Executer un playbook en mode `--check` (dry-run) pour valider le flux complet sans modifier la cible.

```bash
cd ~/homelab/dockhost
uv run ansible-playbook ansible/deploy.yml --tags motd --check
```

### Resultat attendu

```
PLAY [Configure dockhost-90] **************
TASK [motd : ...] ************************
ok/changed: [dockhost-90]
PLAY RECAP ********************************
dockhost-90 : ok=X  changed=Y  unreachable=0  failed=0
```

### Troubleshooting

| Symptome | Cause probable | Solution |
|----------|---------------|----------|
| `UNREACHABLE` | Cle SSH non deployee | Verifier `~/.ssh/id_vm_proxmox_rsa` et `~/.ssh/config` |
| `vault password` error | `pass show` echoue | Verifier GPG key trust (`gpg --list-keys`) |
| `uv: command not found` | PATH incomplet | Ajouter `export PATH="$HOME/.local/bin:$PATH"` |
| `No module named ansible` | Dependencies pas installees | `cd ~/homelab && uv sync` |

------

## 📝 Etape 3 : Test execution reelle (tag leger)

Une fois le dry-run OK, executer un tag sans risque (ex: `motd`) pour valider l'ecriture.

```bash
cd ~/homelab/dockhost
uv run ansible-playbook ansible/deploy.yml --tags motd
```

Puis verifier sur la cible :

```bash
ssh dockhost-90 "cat /etc/motd"
```

------

## 📝 Etape 4 : Test depuis le workstation via SSH (simulation CI)

Simuler ce que fera le CI : une commande SSH one-shot sur le bastion.

```bash
# Depuis le workstation (PAS le bastion)
ssh bastion-60 "cd ~/homelab/dockhost && ~/.local/bin/uv run ansible-playbook ansible/deploy.yml --tags motd --check"
```

> **Important** : En mode non-login SSH, le `PATH` peut ne pas inclure `~/.local/bin/`. Utiliser le chemin absolu `~/.local/bin/uv`.

------

## 📝 Etape 5 : Test kubecluster (optionnel)

```bash
# Depuis le bastion
cd ~/homelab/kubecluster
uv run ansible-playbook ansible/deploy.yml --tags cfg_nodes --check
```

------

## ✅ Checklist de validation

- [ ] `ssh bastion-60` fonctionne
- [ ] `pass show ansible/vault` retourne le secret sans prompt
- [ ] `ssh dockhost-90 "hostname"` fonctionne depuis le bastion
- [ ] `uv run ansible-playbook --tags motd --check` passe en dry-run
- [ ] `uv run ansible-playbook --tags motd` passe en execution reelle
- [ ] Commande SSH one-shot depuis le workstation fonctionne
- [ ] Le MOTD est effectivement mis a jour sur la cible

------

## 📚 References

- [Bastion VM specs](../CLAUDE.md#sous-projet--bastion)
- [SSH cloud-init incident](../../homelab-docs/incidents/2026-02-26-ssh-cloud-init-regression.md)
- [IP addresses](../../homelab-docs/references/ip-addresses.md)

> **Document created on**: 2026-03-06
> **Author**: Xavier Gueret
> **Version**: 1.0
