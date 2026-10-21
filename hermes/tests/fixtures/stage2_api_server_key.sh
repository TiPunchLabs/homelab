#!/bin/sh
# VERBATIM copy of the API_SERVER_KEY block of docker/stage2-hook.sh,
# image nousresearch/hermes-agent:v2026.8.18 (stage2-hook.sh sha256 1fc8921844e288e4…), lines 445-460.
# Only refuse_symlinked_path is stubbed (same contract: 0 = refuse).
# Used by test_m2_cafe_ia.py (T13); refresh it on every image upgrade.
set -eu
HERMES_HOME="${HERMES_HOME:-/opt/data}"
refuse_symlinked_path() { [ -L "$2" ]; }
if [ -f "$HERMES_HOME/.env" ] && ! grep -q '^API_SERVER_KEY=..*' "$HERMES_HOME/.env" 2>/dev/null; then
  if refuse_symlinked_path "append" "$HERMES_HOME/.env"; then
    :
  else
    _gen_key=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
    if [ -n "$_gen_key" ]; then
      # Drop an empty assignment line if the seed left one behind, then
      # append the generated key.
      sed -i '/^API_SERVER_KEY=$/d' "$HERMES_HOME/.env" 2>/dev/null || true
      printf 'API_SERVER_KEY=%s\n' "$_gen_key" >>"$HERMES_HOME/.env"
      echo "[stage2] Generated API_SERVER_KEY for the loopback gateway api_server"
    fi
    unset _gen_key
  fi
fi
