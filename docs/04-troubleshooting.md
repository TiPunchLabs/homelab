# Troubleshooting

## SSH

### Connection refused

```bash
# Check that the VM is running
ssh pve "qm status 9090"  # dockhost
ssh pve "qm status 9040"  # kubecluster control plane

# Test network connectivity
ping 192.168.10.90

# Test SSH with verbose output
ssh -vvv dockhost-90
```

### Permission denied (publickey)

```bash
# Check that the key is loaded in the agent
ssh-add -l

# Add the key manually
ssh-add ~/.ssh/id_vm_proxmox_rsa

# Check SSH config
cat ~/.ssh/config | grep -A 4 "dockhost-90"
```

### Host key changed (MITM warning)

After re-provisioning a VM, the host key changes:

```bash
# Remove the old host key
ssh-keygen -R 192.168.10.90    # dockhost
ssh-keygen -R 192.168.10.40    # kubecluster CP
```

---

## Terraform

### Provider not found error

```bash
cd <project>/terraform
terraform init -upgrade
```

### State lock

```bash
# Check active locks
terraform force-unlock <LOCK_ID>
```

### SSH file not found in CI

The file `~/.ssh/id_proxmox_vms.pub` does not exist on the CI runner. The code uses `fileexists()` to handle this case:

```hcl
vm_ssh_keys = fileexists(pathexpand("~/.ssh/id_proxmox_vms.pub")) ? [
  trimspace(file(pathexpand("~/.ssh/id_proxmox_vms.pub")))
] : []
```

---

## Ansible

### Vault password not found

```bash
# Check that pass is configured
pass show ansible/vault

# Check the script
bash scripts/ansible-vault-pass.sh
```

### Unencrypted vault file

The pre-commit hook `check-ansible-vault` blocks commits if a vault file is in plain text:

```bash
# Re-encrypt the file
ansible-vault encrypt <vault_file>

# Verify
head -1 <vault_file>
# Should display: $ANSIBLE_VAULT;1.1;AES256
```

### community.docker module not found

```bash
# Install required collections
ansible-galaxy collection install -r requirements.yml
```

---

## Docker (on dockhost-90)

### Container won't start

```bash
ssh dockhost-90

# View container logs
docker logs gitlab_runner

# Check compose files
docker compose -f /opt/gitlab-runner/docker-compose.yml config
```

### GitLab Runner won't register

```bash
# Check logs
docker logs gitlab_runner

# Common causes:
# 1. Expired or invalid token -> regenerate and update the vault
# 2. Insufficient scope -> the token must have admin:org
# 3. Runner already registered with the same name -> delete in GitLab Settings
```

---

## Kubernetes (kubecluster)

### Nodes in NotReady state

```bash
ssh kubecluster-40
kubectl get nodes
kubectl describe node <node-name>

# Check kubelet
systemctl status kubelet
journalctl -u kubelet -f
```

### Pods in CrashLoopBackOff

```bash
kubectl get pods -A
kubectl describe pod <pod-name> -n <namespace>
kubectl logs <pod-name> -n <namespace>
```

### Expired join token

```bash
# On the control plane (kubecluster-40)
kubeadm token create --print-join-command
```

---

## CI/CD

### Ansible-lint fails in CI

```bash
# Reproduce locally
uv run ansible-lint proxmox/ansible/ dockhost/ansible/ kubecluster/ansible/
```

### Trivy scan fails

```bash
# Run a local scan
docker run --rm aquasec/trivy:0.69.3 image <image:tag>
```

### Gitleaks blocks a commit or a pipeline

The `gitleaks` pre-commit hook and CI job print the rule, file, line and commit; the value itself is redacted.

- A real secret: remove it from the change (move it to Ansible Vault or `pass`) and rotate it if it was ever pushed.
- A false positive: rewrite the line so it no longer looks like a secret, or add `# gitleaks:allow` at the end of that line.
- A finding in already-pushed history: add its fingerprint (printed by Gitleaks) to `.gitleaksignore` with a comment. Never rewrite history for this.

One-off audit of the whole history (no value printed, report kept outside the repo):

```bash
gitleaks git --redact --no-banner --report-format json --report-path /tmp/gitleaks-history.json .
```

### Pre-commit hooks fail

```bash
# Run all hooks
pre-commit run --all-files

# Fix formatting automatically
# trailing-whitespace and end-of-file-fixer auto-correct
# Re-stage corrected files
git add <corrected_files>
```
