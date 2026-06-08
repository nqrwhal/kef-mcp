"""
Poke <-> KEF + Spotify MCP server.

Exposes a set of tools over streamable-HTTP MCP so Poke (cloud) can control a
KEF LSX II on your LAN and drive Spotify playback through it.

Reached by Poke via a Cloudflare Tunnel -> this container. A bearer token
(MCP_AUTH_TOKEN) gates access so only your Poke can call it.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from kef_client import KefClient, KefError
from spotify_client import SpotifyClient, SpotifyError

# ---- config from env ----------------------------------------------------

KEF_HOST = os.environ.get("KEF_HOST", "")
KEF_DEVICE_NAME = os.environ.get("KEF_DEVICE_NAME", "KEF")  # Spotify Connect name
DEFAULT_VOLUME = int(os.environ.get("KEF_DEFAULT_VOLUME", "25"))

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REFRESH_TOKEN = os.environ.get("SPOTIFY_REFRESH_TOKEN", "")

AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")

kef = KefClient(KEF_HOST) if KEF_HOST else None


def _spotify() -> SpotifyClient:
    return SpotifyClient(
        SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN
    )


def _need_kef() -> KefClient:
    if kef is None:
        raise KefError("KEF_HOST is not set; KEF tools are disabled.")
    return kef


# Bearer-token auth so only your Poke can reach the tools.
auth = None
if AUTH_TOKEN:
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    auth = StaticTokenVerifier(tokens={AUTH_TOKEN: {"client_id": "poke"}})

mcp = FastMCP("KEF + Spotify", auth=auth)


# ====================== KEF tools ======================

@mcp.tool
async def kef_power_on() -> str:
    """Wake the KEF speakers from standby."""
    await _need_kef().power_on()
    return "KEF powered on."


@mcp.tool
async def kef_standby() -> str:
    """Put the KEF speakers into standby (off)."""
    await _need_kef().standby()
    return "KEF in standby."


@mcp.tool
async def kef_set_source(source: str) -> str:
    """Switch the KEF input source.

    Valid sources: wifi, bluetooth, tv, optic, coaxial, analog.
    Use 'wifi' for Spotify Connect / streaming.
    """
    await _need_kef().set_source(source)
    return f"KEF source set to {source}."


@mcp.tool
async def kef_set_volume(level: int) -> str:
    """Set the KEF hardware volume (0-100)."""
    await _need_kef().set_volume(level)
    return f"KEF volume set to {level}."


@mcp.tool
async def kef_get_volume() -> int:
    """Get the current KEF hardware volume (0-100)."""
    return await _need_kef().get_volume()


@mcp.tool
async def kef_play_pause() -> str:
    """Toggle play/pause on the KEF."""
    await _need_kef().play_pause()
    return "Toggled play/pause on KEF."


@mcp.tool
async def kef_next() -> str:
    """Skip to the next track on the KEF."""
    await _need_kef().next_track()
    return "Skipped to next track."


@mcp.tool
async def kef_previous() -> str:
    """Go to the previous track on the KEF."""
    await _need_kef().previous_track()
    return "Went to previous track."


@mcp.tool
async def kef_status() -> dict:
    """Report KEF power state, current source, and what's playing."""
    k = _need_kef()
    return {
        "status": await k.get_status(),
        "source": await k.get_source(),
        "volume": await k.get_volume(),
        "now_playing": await k.now_playing(),
    }


# ====================== Spotify tools ======================

@mcp.tool
async def spotify_pause() -> str:
    """Pause Spotify playback."""
    await _spotify().pause()
    return "Spotify paused."


@mcp.tool
async def spotify_skip() -> str:
    """Skip to the next Spotify track."""
    await _spotify().next()
    return "Skipped to next Spotify track."


@mcp.tool
async def spotify_now_playing() -> dict:
    """What's currently playing on Spotify and on which device."""
    return await _spotify().now_playing()


@mcp.tool
async def spotify_set_volume(level: int) -> str:
    """Set Spotify playback volume (0-100) on the active device."""
    await _spotify().set_volume(level)
    return f"Spotify volume set to {level}."


# ====================== The main combined tool ======================

@mcp.tool
async def play_on_kef(query: str, volume: int | None = None) -> str:
    """Play music on the KEF speakers from a natural request.

    Does the whole flow: wakes the KEF, switches it to wifi, finds the
    requested artist/track/playlist/album on Spotify, transfers playback to
    the KEF's Spotify Connect device, and starts it.

    `query` is a free-text request like "Bonobo", "lofi beats playlist",
    or "Bohemian Rhapsody by Queen".
    `volume` optionally sets the KEF volume (0-100) before playing.
    """
    k = _need_kef()
    sp = _spotify()

    # 1. Wake the speaker and put it on wifi (Spotify Connect streams here).
    await k.set_source("wifi")  # also powers on from standby
    if volume is not None:
        await k.set_volume(volume)

    # 2. Resolve the request to a Spotify URI.
    uri = await sp.search_uri(query)

    # 3. Make sure the KEF is the active Spotify device, then play.
    dev = await sp.find_device(KEF_DEVICE_NAME)
    if dev is None:
        # The KEF may not advertise as a Connect device until it's awake and
        # the Spotify Connect endpoint is active. Tell the user clearly.
        names = ", ".join(d["name"] for d in await sp.devices()) or "none"
        raise SpotifyError(
            f"KEF Spotify Connect device matching '{KEF_DEVICE_NAME}' not found. "
            f"Visible devices: {names}. Make sure the KEF is awake and has "
            f"played Spotify at least once so it appears as a Connect target."
        )
    await sp.transfer(dev["id"], play=False)
    await sp.play(uri, device_id=dev["id"])
    return f"Playing '{query}' on the KEF."


if __name__ == "__main__":
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8000"))
    # Streamable-HTTP transport at /mcp — this is the URL you give Poke.
    mcp.run(transport="http", host=host, port=port, path="/mcp")
