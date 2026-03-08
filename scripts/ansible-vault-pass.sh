#!/bin/bash
if [ -n "$ANSIBLE_VAULT_PASSWORD" ]; then
  echo "$ANSIBLE_VAULT_PASSWORD"
else
  pass show ansible/vault
fi
