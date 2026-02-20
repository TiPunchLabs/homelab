#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -xe

# Function to run commands and handle errors
run_command() {
  local command="$1"
  echo "Running command: $command"
  if eval "$command"; then
    echo "Command succeeded: $command"
  else
    echo "Error: Command failed: $command" >&2
    exit 1
  fi
}

# JSON file containing token setup information
SETUP_TOKEN_FILE="/tmp/token_setup.json"

# Check if the TERRAFORM_PASSWORD environment variable is set
if [ -z "$GEN_PASS" ]; then
  echo "Error: GEN_PASSWORD environment variable is not set."
  exit 1
fi

# Get the number of entries in the JSON file
nb_token=$(jq '.token_setup | length' $SETUP_TOKEN_FILE)

# Loop through each token_setup entry
for i in $(seq 0 $((nb_token - 1))); do
  # Extract values for each index i
  TOKEN_NAME=$(jq -r ".token_setup[$i].name" $SETUP_TOKEN_FILE)
  ROLE=$(jq -r ".token_setup[$i].role" $SETUP_TOKEN_FILE)
  UGID=$(jq -r ".token_setup[$i].ugid" $SETUP_TOKEN_FILE)
  TOKEN_COMMENT=$(jq -r ".token_setup[$i].comment" $SETUP_TOKEN_FILE)
  TOKEN_EXPIRE=$(jq -r ".token_setup[$i].expire" $SETUP_TOKEN_FILE)
  TOKEN_PRIVSEP=$(jq -r ".token_setup[$i].privsep" $SETUP_TOKEN_FILE)
  PRIVILEGES=$(jq -r ".token_setup[$i].privileges[]" $SETUP_TOKEN_FILE)

  # Join the array into a single string separated by spaces
  PRIVILEGES_STR=$(
    IFS=" "
    echo "${PRIVILEGES[*]}"
  )

  # Check if the role already exists
  if pveum role list -o json | jq -e --arg role "$ROLE" '.[] | select (.roleid == $role)' >/dev/null; then
    echo "Role $ROLE already exists, skipping creation."
  else
    # Add the role with specified privileges
    echo "Adding role $ROLE..."
    run_command "pveum role add $ROLE -privs \"$PRIVILEGES_STR\""
  fi

  # # Check if the user already exists
  if pveum user list -o json | jq -e --arg user "$UGID" '.[] | select(.userid == $user)' >/dev/null; then
    echo "User $UGID already exists, skipping creation."
  else
    # Add user terraform-prov@pve with the specified password
    echo "Adding user $UGID..."
    run_command "pveum user add $UGID --password \"$GEN_PASS\""
  fi

  # # Check if the user already has the role assigned
  if pveum acl list -o json | jq -e --arg role "$ROLE" --arg ugid "$UGID" '.[] | select (.roleid == $role and .ugid == $ugid)' >/dev/null; then
    echo "User $UGID already has the $ROLE role assigned, skipping association."
  else
    # Assign TerraformProv role to the user
    echo "Assigning $ROLE role to user $UGID..."
    run_command "pveum aclmod / -user $UGID -role $ROLE"
  fi

  # echo "Role $ROLE assigned to user $UGID successfully."

  # Check if the token already exists
  if pveum user token list "$UGID" -o json | jq -e --arg token "$TOKEN_NAME" '.[] | select(.tokenid == $token)' >/dev/null; then
    echo "Token '$TOKEN_NAME' already exists for user '$UGID'. No action taken."
  else
    echo "Creating token '$TOKEN_NAME' for user '$UGID'."
    # Create the token
    run_command "pveum user token add $UGID $TOKEN_NAME -expire $TOKEN_EXPIRE -privsep $TOKEN_PRIVSEP -comment \"$TOKEN_COMMENT\" -o json > /root/.${TOKEN_NAME}_token"
  fi

done
