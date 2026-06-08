"""
Spotify Web API client (Premium required for playback control).

Uses the Authorization Code flow. A refresh token is obtained once via
auth_spotify.py and stored in SPOTIFY_REFRESH_TOKEN; this client exchanges it
for short-lived access tokens automatically.

Scopes needed: user-modify-playback-state user-read-playback-state
"""

from __future__ import annotations

import base64
import re
import time
from difflib import SequenceMatcher

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
        # Spotify's playback-control endpoints (pause/next/play/volume/transfer)
        # return 200 with a non-empty, NON-JSON body (an opaque string, no JSON
        # content-type). Parsing that with .json() raises JSONDecodeError, so
        # only decode when it actually looks like JSON; otherwise treat as empty.
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:  # JSONDecodeError subclasses ValueError
            return {}

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
        """Resolve a free-text request to the best-matching Spotify URI.

        Spotify's search returns *something* in every category for almost any
        words (e.g. a loosely-related playlist), so simply taking the first
        result from a fixed category order plays the wrong thing — "New Levels
        New Devils by Polyphia" used to match a random "New To Play" playlist.

        Instead we score every candidate across all types by how well its name
        (and artist) matches the query, and return the highest-scoring URI.
        """
        d = await self._req(
            "GET", "/search", params={"q": query, "type": types, "limit": 5}
        )

        candidates = self._gather_candidates(d)
        if not candidates:
            raise SpotifyError(f"No Spotify results for {query!r}.")

        best = max(candidates, key=lambda c: self._score(query, c))
        return best["uri"]

    @staticmethod
    def _gather_candidates(d: dict) -> list[dict]:
        """Flatten the search response into scoreable candidates.

        Filters out null items (Spotify returns `null` entries in the items
        arrays, which previously crashed `items[0]["uri"]`).
        """
        out: list[dict] = []
        for it in (d.get("tracks") or {}).get("items") or []:
            if it:
                out.append({"kind": "track", "name": it.get("name", ""),
                            "artist": ", ".join(a["name"] for a in it.get("artists", [])),
                            "uri": it["uri"]})
        for it in (d.get("albums") or {}).get("items") or []:
            if it:
                out.append({"kind": "album", "name": it.get("name", ""),
                            "artist": ", ".join(a["name"] for a in it.get("artists", [])),
                            "uri": it["uri"]})
        for it in (d.get("artists") or {}).get("items") or []:
            if it:
                out.append({"kind": "artist", "name": it.get("name", ""),
                            "artist": "", "uri": it["uri"]})
        for it in (d.get("playlists") or {}).get("items") or []:
            if it:
                out.append({"kind": "playlist", "name": it.get("name", ""),
                            "artist": (it.get("owner") or {}).get("display_name", ""),
                            "uri": it["uri"]})
        return out

    # Words in a query that signal the user wants a playlist / album.
    _PLAYLIST_HINT = re.compile(
        r"\b(playlist|mix|radio|vibes?|beats|chill|focus|study|workout|essentials)\b",
        re.I,
    )
    _ALBUM_HINT = re.compile(r"\b(album|ep|lp)\b", re.I)
    _WORD = re.compile(r"[a-z0-9]+")

    @classmethod
    def _norm(cls, s: str) -> str:
        return " ".join(cls._WORD.findall((s or "").lower()))

    @classmethod
    def _score(cls, query: str, c: dict) -> float:
        """Higher = better match. Combines name similarity, token overlap,
        an optional 'by <artist>' match, light type priors, and intent hints."""
        # Split a trailing "... by <artist>" so the artist boosts the artist
        # match instead of polluting the name comparison.
        m = re.search(r"\b(.*?)\s+by\s+(.+)$", query.strip(), re.I)
        qname, qartist = (m.group(1).strip(), m.group(2).strip()) if m else (query.strip(), None)

        qn, nm = cls._norm(qname), cls._norm(c["name"])
        base = SequenceMatcher(None, qn, nm).ratio()
        qtok, ntok = set(qn.split()), set(nm.split())
        overlap = len(qtok & ntok) / max(1, len(qtok))
        s = 0.6 * base + 0.4 * overlap
        if qn == nm:
            s += 0.5
        if qartist and c["artist"]:
            s += 0.5 * SequenceMatcher(None, cls._norm(qartist), cls._norm(c["artist"])).ratio()

        s += {"track": 0.15, "album": 0.15, "artist": 0.12, "playlist": -0.25}[c["kind"]]
        if c["kind"] == "playlist" and cls._PLAYLIST_HINT.search(query):
            s += 0.45
        if c["kind"] == "album" and cls._ALBUM_HINT.search(query):
            s += 0.3
        return s

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
