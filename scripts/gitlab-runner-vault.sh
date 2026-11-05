#!/usr/bin/env bash
# Write dockhost/ansible/group_vars/dockhost/vault/gitlab_runner.yml, encrypted.
#
# The runner token comes from the gitlab-terraform state (terraform output),
# the runner-quota fine-grained PAT is read from a silent prompt. Neither is
# displayed nor written unencrypted outside a private temporary file.
# Run it from an owner terminal (the vault password comes from pass).
set -euo pipefail
set +x

root=$(cd "$(dirname "$0")/.." && pwd)
dest=$root/dockhost/ansible/group_vars/dockhost/vault/gitlab_runner.yml
vault_pass=$root/scripts/ansible-vault-pass.sh

if [[ -e $dest ]]; then
  echo "gitlab-runner-vault: $dest already exists; edit it with ansible-vault edit" >&2
  exit 1
fi

runner_token=$(cd "$root/gitlab-terraform" && terraform output -raw homelab_runner_token)
[[ $runner_token == glrt-* ]] || {
  echo "gitlab-runner-vault: terraform output homelab_runner_token is not a glrt- token" >&2
  exit 1
}

read -rsp "runner-quota fine-grained PAT: " quota_token
echo
[[ ${#quota_token} -gt 20 ]] || {
  echo "gitlab-runner-vault: token too short" >&2
  exit 1
}

umask 077
tmp=$(mktemp)
trap 'shred -u "$tmp"' EXIT
printf -- '---\nvault_gitlab_runner_token: "%s"\nvault_runner_quota_token: "%s"\n' \
  "$runner_token" "$quota_token" >"$tmp"
unset runner_token quota_token

ansible-vault encrypt --vault-password-file "$vault_pass" --output "$dest" "$tmp"
head -1 "$dest"
echo "gitlab-runner-vault: wrote $dest"
