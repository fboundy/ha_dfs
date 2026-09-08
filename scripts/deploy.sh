#!/usr/bin/env bash
# Vendor the neso_dfs library into the integration and copy it to a Home Assistant host.
#
#   ./scripts/deploy.sh [user@host] [config_dir]
set -euo pipefail

HOST="${1:-root@192.168.4.23}"
CONFIG_DIR="${2:-/config}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPONENT_DIR="$REPO_ROOT/custom_components/neso_dfs"

python "$REPO_ROOT/scripts/sync_vendor.py"

echo "Deploying to $HOST:$CONFIG_DIR/custom_components/neso_dfs"
ssh "$HOST" "mkdir -p '$CONFIG_DIR/custom_components/neso_dfs'"
scp -q -r "$COMPONENT_DIR/." "$HOST:$CONFIG_DIR/custom_components/neso_dfs/"
ssh "$HOST" "find '$CONFIG_DIR/custom_components/neso_dfs' -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true"

echo "Done. Restart Home Assistant to load the integration:"
echo "  ssh $HOST 'ha core restart'"
