# Headless Poke tunnel: exposes the local MCP server to your Poke agent.
# Runs the official `poke` CLI in a container so it survives reboots
# (restart: unless-stopped) instead of being a foreground process.
FROM node:20-slim

RUN npm install -g poke@latest

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
