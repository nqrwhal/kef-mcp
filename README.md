# kef-mcp

An **MCP server** for controlling **KEF wireless speakers** (LSX II / LS50 Wireless II
/ LS60) and playing **Spotify** on them. Exposes tools any MCP client can call to
power the speaker on/off, switch inputs, set volume, control transport, and start
Spotify playback — with one combined tool that does the whole "wake → switch to
wifi → play" flow.

Built to be driven by [Poke](https://poke.com) (see [`poke/`](./poke)), but it's a
standard MCP server (streamable HTTP) usable by any MCP client.

```
MCP client ──► kef-mcp ──┬─ HTTP ─► KEF speaker (LAN)
                         └─ HTTPS ► Spotify Web API
```

## Tools

| Tool | What it does |
|------|--------------|
| `play_on_kef(query, volume?)` | **Main one.** Wake KEF → source=wifi → find on Spotify → play on KEF. |
| `kef_power_on` / `kef_standby` | Power on / off. |
| `kef_set_source(source)` | wifi, bluetooth, tv, optic, coaxial, analog. |
| `kef_set_volume(level)` / `kef_get_volume` | Hardware volume 0-100. |
| `kef_play_pause` / `kef_next` / `kef_previous` | Transport control. |
| `kef_status` | Power, source, volume, now playing. |
| `spotify_pause` / `spotify_skip` | Spotify-side control. |
| `spotify_set_volume(level)` | Volume on the active Spotify device. |
| `spotify_now_playing` | Track / artist / device. |

## Prerequisites

- **Spotify Premium** (the Web API blocks playback control on Free accounts).
- A KEF LSX II / LS50 Wireless II / LS60 on your LAN, ideally with a **DHCP
  reservation** so its IP is stable.
- Docker (to run the server), or just Python 3.12+ to run it directly.

## Setup

### 1. Configure

```bash
cp .env.example .env
```

Fill in `.env`:

- `KEF_HOST` — the speaker's LAN IP (from the KEF Connect app or your router).
- `KEF_DEVICE_NAME` — substring of its Spotify Connect name (e.g. `KEF`).
- `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` — from a
  [Spotify app](https://developer.spotify.com/dashboard) (Redirect URI:
  `http://127.0.0.1:8888/callback`).
- `MCP_AUTH_TOKEN` — a random string clients must send as a Bearer token.
  Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

### 2. Get a Spotify refresh token (once)

```bash
pip install requests
export SPOTIFY_CLIENT_ID=...      # PowerShell: $env:SPOTIFY_CLIENT_ID="..."
export SPOTIFY_CLIENT_SECRET=...
python auth_spotify.py
```

Log in, approve, and copy the printed `SPOTIFY_REFRESH_TOKEN=...` line into `.env`.

### 3. Run

**Docker (recommended):**

```bash
docker compose up -d --build
docker compose logs -f kef-mcp
```

> `docker-compose.yml` also runs a `cloudflared` sidecar for remote access — only
> needed for cloud clients like Poke. If you don't set `CLOUDFLARE_TUNNEL_TOKEN`,
> ignore that container.

**Or directly:**

```bash
pip install -r requirements.txt
python server.py     # serves streamable HTTP at http://0.0.0.0:8000/mcp
```

### 4. Connect a client

Point your MCP client at `http://<host>:8000/mcp` (or the public tunnel URL) with
`Authorization: Bearer <MCP_AUTH_TOKEN>`.

For **Poke** specifically — Cloudflare Tunnel setup, connecting, and the recipe —
see [`poke/README.md`](./poke/README.md).

## Sanity checks

KEF reachable from the container:

```bash
docker compose exec kef-mcp python -c \
  "import asyncio, os; from kef_client import KefClient; \
   print(asyncio.run(KefClient(os.environ['KEF_HOST']).get_status()))"
```

Should print the speaker status (e.g. `standby` / `powerOn`).

## Notes & troubleshooting

- **"KEF Spotify Connect device not found"** — the KEF only advertises as a Connect
  target once it's awake and has played Spotify since boot. `play_on_kef` wakes it
  first; on a cold boot, cast to it once from the Spotify app, then retry.
- **Spotify 404 / "No active device"** — same cause; ensure `KEF_DEVICE_NAME`
  matches the name Spotify shows.
- **Container can't reach the KEF** — verify `KEF_HOST` and that the speaker has a
  DHCP reservation.
- **KEF API** — writes are `POST /api/setData` (JSON body), reads are
  `GET /api/getData`. Verified against LSX II / LS50 W II / LS60 firmware. Very old
  firmware used GET-only; update firmware if writes fail.

## Project layout

```
kef-mcp/
├── server.py             # MCP server: defines the tools
├── kef_client.py         # KEF local HTTP API client
├── spotify_client.py     # Spotify Web API client
├── auth_spotify.py       # one-time Spotify OAuth helper
├── Dockerfile
├── docker-compose.yml    # server + optional cloudflared tunnel
├── .env.example
└── poke/                 # Poke-specific: tunnel guide + recipe
    ├── README.md
    └── RECIPE.md
```

## Security

- `.env` holds your Spotify secret/refresh token and auth token — gitignored, never
  commit it.
- Anyone with `MCP_AUTH_TOKEN` + the URL can control your speakers and Spotify. Keep
  it secret; consider a Cloudflare Access policy for remote exposure.

## Credits

KEF local-API payload formats verified against
[pykefcontrol](https://github.com/N0ciple/pykefcontrol) (MIT).
