#!/bin/sh
# Materialize Poke credentials so `poke tunnel` runs headless.
#
# `poke tunnel` does NOT read POKE_API_KEY from the environment. It reads its
# account token only from ~/.config/poke/credentials.json (the file that
# `poke login` writes). That token is a *device-login session token* obtained
# via the browser device-code flow -- not the same thing as a kitchen API key.
#
# Since we can't open a browser inside the container, you log in once on a
# machine that has one (`npx poke@latest login`) and copy the resulting token
# from ~/.config/poke/credentials.json into .env as POKE_TUNNEL_TOKEN. This
# script writes that token into the credentials file the CLI expects.
#
# POKE_API_KEY is kept only as a fallback for backwards compatibility; the
# tunnel endpoint may reject a long-lived kitchen key, so POKE_TUNNEL_TOKEN
# (your login session token) is the supported path.
set -e

TOKEN="${POKE_TUNNEL_TOKEN:-$POKE_API_KEY}"

if [ -z "$TOKEN" ]; then
  echo "ERROR: No Poke token set."
  echo "Run 'npx poke@latest login' on a machine with a browser, then copy the"
  echo "'token' value from ~/.config/poke/credentials.json into .env as"
  echo "POKE_TUNNEL_TOKEN."
  exit 1
fi

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/poke"
mkdir -p "$CONFIG_DIR"
printf '{"token":"%s"}\n' "$TOKEN" > "$CONFIG_DIR/credentials.json"
chmod 600 "$CONFIG_DIR/credentials.json"

TUNNEL_NAME="${POKE_TUNNEL_NAME:-KEF + Spotify}"
# Point at the MCP server container on the shared Docker network.
TARGET_URL="${POKE_TUNNEL_TARGET:-http://kef-mcp:8000/mcp}"

echo "Starting Poke tunnel '$TUNNEL_NAME' -> $TARGET_URL"
exec poke tunnel "$TARGET_URL" --name "$TUNNEL_NAME"
