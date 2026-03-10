# Troubleshooting

## SSH

### Connexion refusee

```bash
# Verifier que la VM est demarree
ssh pve "qm status 9050"  # dockhost
ssh pve "qm status 9040"  # kubecluster control plane

# Tester la connectivite reseau
ping 192.168.1.50

# Tester SSH avec verbose
ssh -vvv dockhost-50
```

### Permission denied (publickey)

```bash
# Verifier que la cle est chargee dans l'agent
ssh-add -l

# Ajouter la cle manuellement
ssh-add ~/.ssh/id_proxmox_vms

# Verifier la config SSH
cat ~/.ssh/config | grep -A 4 "dockhost"
```

### Host key changed (MITM warning)

Apres re-provisionnement d'une VM, le host key change :

```bash
# Supprimer l'ancien host key
ssh-keygen -R 192.168.1.50    # dockhost
ssh-keygen -R 192.168.1.40    # kubecluster CP
```

---

## Terraform

### Erreur provider non trouve

```bash
cd <projet>/terraform
terraform init -upgrade
```

### State lock

```bash
# Verifier les locks actifs
terraform force-unlock <LOCK_ID>
```

### Erreur fichier SSH introuvable en CI

Le fichier `~/.ssh/id_proxmox_vms.pub` n'existe pas sur le runner CI. Le code utilise `fileexists()` pour gerer ce cas :

```hcl
vm_ssh_keys = fileexists(pathexpand("~/.ssh/id_proxmox_vms.pub")) ? [
  trimspace(file(pathexpand("~/.ssh/id_proxmox_vms.pub")))
] : []
```

---

## Ansible

### Vault password introuvable

```bash
# Verifier que pass est configure
pass show ansible/vault

# Verifier le script
bash scripts/ansible-vault-pass.sh
```

### Fichier vault non chiffre

Le pre-commit hook `check-ansible-vault` bloque les commits si un fichier vault est en clair :

```bash
# Re-chiffrer le fichier
ansible-vault encrypt <fichier_vault>

# Verifier
head -1 <fichier_vault>
# Doit afficher: $ANSIBLE_VAULT;1.1;AES256
```

### Module community.docker non trouve

```bash
# Installer les collections requises
ansible-galaxy collection install -r requirements.yml
```

---

## Docker (sur dockhost-50)

### Container ne demarre pas

```bash
ssh dockhost-50

# Voir les logs du container
docker logs github_runner
docker logs portainer_agent

# Verifier les compose files
docker compose -f /opt/github-runner/docker-compose.yml config
docker compose -f /opt/portainer-agent/docker-compose.yml config
```

### GitHub Runner ne s'enregistre pas

```bash
# Verifier les logs
docker logs github_runner

# Causes frequentes :
# 1. PAT expire ou invalide -> regenrer le PAT et mettre a jour le vault
# 2. Scope insuffisant -> le PAT doit avoir admin:org
# 3. Runner deja enregistre avec le meme nom -> supprimer dans GitHub Settings
```

### Portainer Agent inaccessible

```bash
# Verifier que le port est ouvert
ssh dockhost-50 "ss -tlnp | grep 9001"

# Verifier le firewall
ssh dockhost-50 "sudo ufw status"

# Le port 9001 doit etre autorise depuis l'IP du manager Portainer
```

---

## Kubernetes (kubecluster)

### Noeuds en NotReady

```bash
ssh kubecluster-40
kubectl get nodes
kubectl describe node <node-name>

# Verifier kubelet
systemctl status kubelet
journalctl -u kubelet -f
```

### Pods en CrashLoopBackOff

```bash
kubectl get pods -A
kubectl describe pod <pod-name> -n <namespace>
kubectl logs <pod-name> -n <namespace>
```

### Token de jointure expire

```bash
# Sur le control plane (kubecluster-40)
kubeadm token create --print-join-command
```

---

## CI/CD

### Ansible-lint echoue en CI

```bash
# Reproduire en local
uv run ansible-lint proxmox/ansible/ dockhost/ansible/ kubecluster/ansible/
```

### Trivy scan echoue

```bash
# Lancer un scan local
docker run --rm aquasec/trivy:0.69.3 image <image:tag>
```

### Pre-commit hooks echouent

```bash
# Lancer tous les hooks
pre-commit run --all-files

# Corriger automatiquement le formatage
# trailing-whitespace et end-of-file-fixer se corrigent automatiquement
# Re-stager les fichiers corriges
git add <fichiers_corriges>
```
