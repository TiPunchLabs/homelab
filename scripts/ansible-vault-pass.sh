#!/bin/bash
if [ -n "$ANSIBLE_VAULT_PASSWORD" ]; then
  printf '%s\n' "$ANSIBLE_VAULT_PASSWORD"
else
  pass show ansible/vault
fi
