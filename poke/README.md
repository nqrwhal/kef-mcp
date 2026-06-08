# Connecting the KEF MCP server to Poke

This folder covers the **Poke-specific** wiring: exposing the MCP server to Poke's
cloud and adding the recipe. For building/running the server itself, see the
[root README](../README.md).

```
Poke (cloud) ──HTTPS──► Cloudflare Tunnel ──► kef-mcp (Docker, your always-on host)
                                                  ├─ HTTP ─► KEF LSX II (your LAN)
                                                  └─ HTTPS ► Spotify Web API
```

Poke is a cloud assistant, so it can't reach a speaker on your LAN directly. The
MCP server runs on an always-on machine at home and is exposed to Poke through a
free Cloudflare Tunnel — no port forwarding, no static IP.

## 1. Get the server running

Follow the [root README](../README.md) first: set up `.env` (KEF IP, Spotify app +
refresh token, `MCP_AUTH_TOKEN`), then `docker compose up -d --build`.

## 2. Cloudflare Tunnel

1. <https://one.dash.cloudflare.com> → **Networks → Tunnels → Create a tunnel** →
   **Cloudflared**. Name it (e.g. `kef-mcp`).
2. Copy the **tunnel token** (the long string after `--token`) into `.env` as
   `CLOUDFLARE_TUNNEL_TOKEN`. The `cloudflared` container in `docker-compose.yml`
   uses it.
3. Under **Public Hostnames**, add:
   - **Hostname**: pick one (e.g. `kef.yourdomain.com`).
   - **Service**: `http://kef-mcp:8000`  (container name + port on the shared network)
4. Save. Your public MCP URL is: `https://<that-hostname>/mcp`

Verify: visit `https://<hostname>/mcp` in a browser — you should get an MCP/HTTP
response, not a Cloudflare error. Check `docker compose logs cloudflared` if not.

## 3. Add the MCP server to Poke

1. In Poke, add a custom **MCP server**.
2. **URL:** `https://<your-hostname>/mcp`
3. **Auth:** Bearer token → your `MCP_AUTH_TOKEN`.
   (If Poke asks for a raw header instead: `Authorization: Bearer <MCP_AUTH_TOKEN>`.)
4. Poke should discover the tools: `play_on_kef`, `kef_*`, `spotify_*`.

## 4. Add the recipe

Paste the text from [`RECIPE.md`](./RECIPE.md) into Poke as a recipe. Then just
talk to it: *"Play Bonobo on the KEF."*

## Notes

- Poke connects custom tools as MCP servers over streamable HTTP — that's exactly
  what this server speaks (`/mcp` endpoint).
- The KEF only advertises as a Spotify Connect target once it's awake and has
  played Spotify since boot. `play_on_kef` wakes it first; on a cold boot you may
  need to cast to it from the Spotify app once. The tool returns a clear message if
  the device isn't found.
- For stronger protection, put a Cloudflare Access policy in front of the hostname.
