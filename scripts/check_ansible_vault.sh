#!/bin/bash

# Exit if no files are provided
if [ $# -eq 0 ]; then
  echo "No files to check."
  exit 0
fi

# Loop through each file provided as an argument by pre-commit
for file in "$@"; do
  # Check if the file starts with "$ANSIBLE_VAULT;"
  # shellcheck disable=SC2016
  if ! head -n 1 "$file" | grep -q '^$ANSIBLE_VAULT;'; then
    echo "Error: The file $file is not encrypted with ansible-vault."
    exit 1
  fi
done
