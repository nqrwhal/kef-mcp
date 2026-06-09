"""
Poke <-> KEF + Spotify MCP server.

Exposes a set of tools over streamable-HTTP MCP so Poke (cloud) can control a
KEF LSX II on your LAN and drive Spotify playback through it.

Reached by Poke via a Cloudflare Tunnel -> this container. A bearer token
(MCP_AUTH_TOKEN) gates access so only your Poke can call it.
"""

from __future__ import annotations

import os
import re

from fastmcp import FastMCP

from cast_client import CastClient, CastError
from kef_client import KefClient, KefError
from spotify_client import SpotifyClient, SpotifyError
from youtube_resolver import resolve_stream_url

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


def _cast() -> CastClient:
    # Cast reuses the KEF's LAN IP -- the speaker's Chromecast control channel
    # lives on the same host. No separate env var needed.
    if not KEF_HOST:
        raise CastError("KEF_HOST is not set; Cast tools are disabled.")
    return CastClient(KEF_HOST)


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


# ====================== Google Cast tools ======================
# These play NON-Spotify audio: internet radio, direct stream URLs, and
# YouTube/SoundCloud (resolved to a stream URL). The speaker has Chromecast
# built-in; casting auto-wakes it and switches it to wifi, like Spotify Connect.


async def _cast_then_volume(
    url: str,
    title: str | None,
    volume: int | None,
    *,
    content_type: str | None = None,
    is_live: bool | None = None,
) -> None:
    """Set KEF hardware volume (if asked) then cast the URL. Volume goes to the
    KEF hardware -- the same loudness control as play_on_kef -- not the Cast
    receiver session volume, so it behaves consistently across all play tools."""
    if volume is not None and kef is not None:
        await kef.set_volume(volume)
    await _cast().play_url(
        url, title=title, content_type=content_type, is_live=is_live
    )


@mcp.tool
async def cast_url(url: str, volume: int | None = None) -> str:
    """Play a direct audio stream URL on the KEF via Google Cast.

    Use this for internet radio, podcast audio, or any direct .mp3/.aac/.flac/
    stream URL. NOT for Spotify (use play_on_kef) or YouTube (use
    play_from_youtube). `volume` optionally sets the KEF hardware volume (0-100).
    """
    await _cast_then_volume(url, None, volume)
    return f"Casting {url} to the KEF."


@mcp.tool
async def play_radio(query_or_url: str, volume: int | None = None) -> str:
    """Play internet radio / a direct stream URL on the KEF via Google Cast.

    Pass a direct stream URL (e.g. an Icecast/Shoutcast .mp3 endpoint).
    `volume` optionally sets the KEF hardware volume (0-100).
    """
    await _cast_then_volume(query_or_url, None, volume)
    return f"Playing radio: {query_or_url}"


@mcp.tool
async def play_from_youtube(query: str, volume: int | None = None) -> str:
    """Play audio from YouTube (or SoundCloud / other sites) on the KEF via Cast.

    `query` can be a search phrase ("daft punk discovery") or a direct
    YouTube/SoundCloud URL. The audio stream is resolved and cast to the KEF.
    Use this when the user wants something from YouTube specifically; for music
    by name, prefer play_on_kef (Spotify). `volume` optionally sets the KEF
    hardware volume (0-100).

    Note: 24/7 YouTube *livestreams* (e.g. "lofi hip hop radio") only offer HLS,
    which this speaker's Cast receiver can't play -- use a normal video/track,
    or use play_radio with a direct radio stream URL for continuous audio.
    """
    r = await resolve_stream_url(query)
    if r["is_hls"]:
        # The KEF's Cast Default Media Receiver does not play HLS (verified
        # against Apple's reference HLS stream too), so livestreams won't work.
        raise CastError(
            f"'{r['title']}' is a livestream (HLS), which this KEF's Cast "
            f"receiver can't play. Try a normal video/track, or play_radio with "
            f"a direct stream URL for continuous audio."
        )
    await _cast_then_volume(r["url"], r["title"], volume, is_live=r["is_live"])
    return f"Playing '{r['title']}' on the KEF (from YouTube)."


@mcp.tool
async def cast_stop() -> str:
    """Stop Cast playback on the KEF and close the Cast receiver."""
    await _cast().stop()
    return "Stopped casting."


@mcp.tool
async def cast_pause() -> str:
    """Pause the current Cast playback on the KEF."""
    await _cast().pause()
    return "Paused Cast playback."


@mcp.tool
async def cast_resume() -> str:
    """Resume paused Cast playback on the KEF."""
    await _cast().resume()
    return "Resumed Cast playback."


@mcp.tool
async def cast_status() -> dict:
    """What's currently playing on the KEF via Google Cast."""
    return await _cast().status()


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


# Poke addresses tool calls at a connection-scoped path (/<connectionId>/mcp),
# while tool sync and the URL you configure use plain /mcp. FastMCP only mounts
# /mcp, so the connection-scoped calls 404. This middleware rewrites any
# "/<segment>/mcp..." request to "/mcp..." so both forms resolve to the server.
_PREFIXED_MCP = re.compile(r"^/[^/]+(/mcp.*)$")


class _StripConnIdMiddleware:
    """Rewrite /<connectionId>/mcp -> /mcp so Poke's connection-scoped tool
    calls reach the FastMCP app. Non-/mcp paths are left untouched (still 404)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not scope.get("path", "").startswith("/mcp"):
            m = _PREFIXED_MCP.match(scope.get("path", ""))
            if m:
                scope = dict(scope)
                scope["path"] = m.group(1)
                if scope.get("raw_path"):
                    scope["raw_path"] = m.group(1).encode()
        await self.app(scope, receive, send)


async def _no_oauth(request):
    """Handle OAuth discovery probes.

    Per the MCP spec (RFC 9728), a client fetches /.well-known/oauth-protected-
    resource only after getting a 401, to discover the auth server. This server
    has no auth (the Poke tunnel is the trust boundary), so the spec-correct
    answer is "no such metadata" -> 404. Poke reads that as "no auth required"
    and proceeds. We register it explicitly so it's an intentional 404 rather
    than noisy unmatched-route log spam.
    """
    from starlette.responses import JSONResponse

    return JSONResponse({"error": "no_auth", "detail": "server requires no auth"}, status_code=404)


def build_app():
    """Build the ASGI app: FastMCP at /mcp, tolerant of a connection-id prefix.

    stateless_http=True avoids 409 Conflict errors caused by session collisions
    when the Poke tunnel reconnects or opens overlapping sessions.
    """
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    mcp_app = mcp.http_app(path="/mcp", stateless_http=True)
    # Explicit, intentional 404s for the OAuth discovery probes Poke sends at
    # connection setup, so they don't read as mysterious errors in the logs.
    # Listed before the catch-all Mount so they match first.
    oauth_paths = [
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-authorization-server/mcp",
    ]
    routes = [Route(p, _no_oauth, methods=["GET"]) for p in oauth_paths]
    routes.append(Mount("/", app=mcp_app))
    # lifespan MUST be forwarded or the streamable-HTTP session manager isn't
    # initialized ("Task group is not initialized").
    parent = Starlette(routes=routes, lifespan=mcp_app.lifespan)
    return _StripConnIdMiddleware(parent)


app = build_app()


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8000"))
    # Streamable-HTTP transport at /mcp (also accepts /<connectionId>/mcp).
    uvicorn.run(app, host=host, port=port)
