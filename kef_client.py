"""
Thin client for the KEF LSX II / LS50 Wireless II / LS60 local HTTP+JSON API.

The speaker exposes an undocumented control API on http://<ip>:80/api/.
Reads use GET /api/getData; writes use POST /api/setData with a JSON body
(GET-with-query is only used by older firmware on other models).

Verified against the pykefcontrol project (MIT) for the LSX II payload formats.
"""

from __future__ import annotations

import httpx

# Valid physical sources accepted by the speaker.
# Note: it's "optic" (not "optical"). "wifi" is what Spotify Connect plays through.
KEF_SOURCES = {"wifi", "bluetooth", "tv", "optic", "coaxial", "analog"}


class KefError(RuntimeError):
    pass


class KefClient:
    def __init__(self, host: str, *, timeout: float = 5.0):
        if not host:
            raise KefError("KEF host/IP is not set (KEF_HOST).")
        self.base = f"http://{host}/api"
        self._timeout = timeout

    # ---- low-level -------------------------------------------------------

    async def _get_data(self, path: str, roles: str = "value"):
        params = {"path": path, "roles": roles}
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.get(f"{self.base}/getData", params=params)
            r.raise_for_status()
            data = r.json()
        # Reads come back as a single-element list.
        if isinstance(data, list) and data:
            return data[0]
        return data

    async def _set_data(self, path: str, value: dict, roles: str = "value"):
        body = {"path": path, "roles": roles, "value": value}
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(f"{self.base}/setData", json=body)
            r.raise_for_status()
            return r.json() if r.content else {}

    # ---- power / source --------------------------------------------------

    async def _set_physical_source(self, kef_source: str):
        return await self._set_data(
            "settings:/kef/play/physicalSource",
            {"type": "kefPhysicalSource", "kefPhysicalSource": kef_source},
        )

    async def power_on(self):
        # "powerOn" wakes the speaker; it returns to its last source.
        return await self._set_physical_source("powerOn")

    async def standby(self):
        return await self._set_physical_source("standby")

    async def set_source(self, source: str):
        source = source.lower().strip()
        if source not in KEF_SOURCES:
            raise KefError(
                f"Invalid source {source!r}. Valid: {', '.join(sorted(KEF_SOURCES))}"
            )
        # Setting a source also powers the speaker on if it was in standby.
        return await self._set_physical_source(source)

    async def get_source(self) -> str:
        d = await self._get_data("settings:/kef/play/physicalSource")
        return d.get("kefPhysicalSource", "unknown")

    async def get_status(self) -> str:
        d = await self._get_data("settings:/kef/host/speakerStatus")
        return d.get("kefSpeakerStatus", "unknown")

    # ---- volume ----------------------------------------------------------

    async def get_volume(self) -> int:
        d = await self._get_data("player:volume")
        return int(d.get("i32_", 0))

    async def set_volume(self, level: int):
        level = max(0, min(100, int(level)))
        return await self._set_data(
            "player:volume", {"type": "i32_", "i32_": level}
        )

    # ---- transport -------------------------------------------------------

    async def _control(self, control: str):
        return await self._set_data(
            "player:player/control", {"control": control}, roles="activate"
        )

    async def play_pause(self):
        return await self._control("pause")  # toggles play/pause

    async def next_track(self):
        return await self._control("next")

    async def previous_track(self):
        return await self._control("previous")

    # ---- now playing -----------------------------------------------------

    async def now_playing(self) -> dict:
        try:
            d = await self._get_data("player:player/data")
        except Exception:
            return {}
        if isinstance(d, dict):
            track = d.get("trackRoles", {}) or {}
            return {
                "state": d.get("state", "unknown"),
                "title": track.get("title"),
                "artist": (track.get("mediaData", {}) or {})
                .get("metaData", {})
                .get("artist"),
            }
        return {}
