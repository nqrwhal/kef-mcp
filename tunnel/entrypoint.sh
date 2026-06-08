#!/bin/sh
# Materialize Poke credentials from POKE_API_KEY so `poke tunnel` runs headless.
# The `poke` CLI reads its account token only from ~/.config/poke/credentials.json
# (it does NOT read POKE_API_KEY for the tunnel command), so we write the file.
set -e

if [ -z "$POKE_API_KEY" ]; then
  echo "ERROR: POKE_API_KEY is not set. Get one at https://poke.com/kitchen/api-keys"
  exit 1
fi

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/poke"
mkdir -p "$CONFIG_DIR"
printf '{"token":"%s"}\n' "$POKE_API_KEY" > "$CONFIG_DIR/credentials.json"
chmod 600 "$CONFIG_DIR/credentials.json"

TUNNEL_NAME="${POKE_TUNNEL_NAME:-KEF + Spotify}"
# Point at the MCP server container on the shared Docker network.
TARGET_URL="${POKE_TUNNEL_TARGET:-http://kef-mcp:8000/mcp}"

echo "Starting Poke tunnel '$TUNNEL_NAME' -> $TARGET_URL"
exec poke tunnel "$TARGET_URL" --name "$TUNNEL_NAME"
