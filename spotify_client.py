"""
Spotify Web API client (Premium required for playback control).

Uses the Authorization Code flow. A refresh token is obtained once via
auth_spotify.py and stored in SPOTIFY_REFRESH_TOKEN; this client exchanges it
for short-lived access tokens automatically.

Scopes needed: user-modify-playback-state user-read-playback-state
"""

from __future__ import annotations

import base64
import time

import httpx

TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"


class SpotifyError(RuntimeError):
    pass


class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        if not (client_id and client_secret and refresh_token):
            raise SpotifyError(
                "Spotify not configured. Set SPOTIFY_CLIENT_ID, "
                "SPOTIFY_CLIENT_SECRET, SPOTIFY_REFRESH_TOKEN "
                "(run auth_spotify.py once to get the refresh token)."
            )
        self._id = client_id
        self._secret = client_secret
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    async def _token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 30:
            return self._access_token
        basic = base64.b64encode(
            f"{self._id}:{self._secret}".encode()
        ).decode()
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                headers={"Authorization": f"Basic {basic}"},
            )
            r.raise_for_status()
            d = r.json()
        self._access_token = d["access_token"]
        self._expires_at = time.time() + d.get("expires_in", 3600)
        return self._access_token

    async def _req(self, method: str, path: str, **kw):
        token = await self._token()
        headers = {"Authorization": f"Bearer {token}"}
        headers.update(kw.pop("headers", {}))
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.request(method, f"{API}{path}", headers=headers, **kw)
        if r.status_code == 404:
            raise SpotifyError(
                "No active Spotify device found. Open Spotify on the KEF "
                "(or transfer to it) first."
            )
        r.raise_for_status()
        return r.json() if r.content else {}

    # ---- devices ---------------------------------------------------------

    async def devices(self) -> list[dict]:
        d = await self._req("GET", "/me/player/devices")
        return d.get("devices", [])

    async def find_device(self, name_contains: str) -> dict | None:
        name_contains = name_contains.lower()
        for dev in await self.devices():
            if name_contains in dev.get("name", "").lower():
                return dev
        return None

    async def transfer(self, device_id: str, play: bool = True):
        return await self._req(
            "PUT",
            "/me/player",
            json={"device_ids": [device_id], "play": play},
        )

    # ---- search + playback ----------------------------------------------

    async def search_uri(self, query: str, types: str = "track,playlist,artist,album") -> str:
        d = await self._req(
            "GET", "/search", params={"q": query, "type": types, "limit": 1}
        )
        # Prefer a context (playlist/album/artist) over a single track when present.
        for key in ("playlists", "albums", "artists", "tracks"):
            items = (d.get(key) or {}).get("items") or []
            if items:
                return items[0]["uri"]
        raise SpotifyError(f"No Spotify results for {query!r}.")

    async def play(self, uri: str, device_id: str | None = None):
        params = {"device_id": device_id} if device_id else {}
        # Track URIs go in `uris`; playlist/album/artist URIs go in `context_uri`.
        if uri.startswith("spotify:track:"):
            body = {"uris": [uri]}
        else:
            body = {"context_uri": uri}
        return await self._req(
            "PUT", "/me/player/play", params=params, json=body
        )

    async def pause(self):
        return await self._req("PUT", "/me/player/pause")

    async def next(self):
        return await self._req("POST", "/me/player/next")

    async def previous(self):
        return await self._req("POST", "/me/player/previous")

    async def set_volume(self, percent: int):
        percent = max(0, min(100, int(percent)))
        return await self._req(
            "PUT", "/me/player/volume", params={"volume_percent": percent}
        )

    async def now_playing(self) -> dict:
        d = await self._req("GET", "/me/player")
        if not d:
            return {"playing": False}
        item = d.get("item") or {}
        return {
            "playing": d.get("is_playing", False),
            "track": item.get("name"),
            "artist": ", ".join(a["name"] for a in item.get("artists", [])),
            "device": (d.get("device") or {}).get("name"),
        }
