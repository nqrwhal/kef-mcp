"""
Google Cast client for the KEF speaker (Chromecast built-in).

The KEF LSX II / LS50 W II / LS60 ship with genuine Chromecast built-in: the
CASTV2 control channel is on TCP 8009 (TLS). We cast HTTP(S) audio URLs to the
Default Media Receiver (app id CC1AD845), which the speaker then pulls and plays
itself -- fire-and-forget, like Spotify Connect. Casting also auto-wakes the
speaker and switches its physical source to wifi.

Why connect by known IP instead of mDNS discovery: the production server runs in
a bridged Docker container, and multicast (mDNS) does not cross the bridge --
but a direct TLS connection to the speaker's IP does (it's the same reachability
the KEF HTTP API already relies on). So we skip discovery entirely and dial the
host directly via get_chromecast_from_host.

pychromecast is synchronous, so every call here runs inside asyncio.to_thread to
keep FastMCP's event loop unblocked. We connect fresh per call rather than
caching a connection, to avoid holding a stale socket across this long-lived
server; connect+wait is ~1-2s, fine for a chat/voice-driven tool.
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

import pychromecast

# Cast control port (CASTV2 over TLS). Constant across all Cast devices.
_CAST_PORT = 8009

# Extension -> MIME, for the DIDL-ish content_type the receiver wants. Anything
# unknown defaults to audio/mpeg, which the receiver treats permissively.
_EXT_MIME = {
    ".mp3": "audio/mpeg",
    ".aac": "audio/aac",
    ".m4a": "audio/aac",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
}

# States that mean "media is actually going" vs. failed-to-start.
_GOOD_STATES = {"PLAYING", "BUFFERING"}


class CastError(RuntimeError):
    pass


def guess_content_type(url: str) -> str:
    """Best-effort MIME from the URL's path extension; default audio/mpeg.
    HLS playlists need the Apple MPEG-URL type or the receiver won't play."""
    path = urlsplit(url).path.lower()
    if path.endswith(".m3u8"):
        return "application/vnd.apple.mpegurl"
    for ext, mime in _EXT_MIME.items():
        if path.endswith(ext):
            return mime
    return "audio/mpeg"


def looks_live(url: str) -> bool:
    """Heuristic: icecast/shoutcast radio streams and HLS playlists are
    continuous, so cast them as LIVE (no seek/duration). A concrete audio file
    extension is buffered."""
    path = urlsplit(url).path.lower()
    if path.endswith(".m3u8"):
        return True
    if any(path.endswith(ext) for ext in _EXT_MIME):
        return False  # a concrete file -> buffered
    # Pathless/extension-less stream endpoint -> assume a live radio stream.
    return True


class CastClient:
    def __init__(self, host: str, *, timeout: float = 15.0):
        if not host:
            raise CastError("Cast host/IP is not set (KEF_HOST).")
        self.host = host
        self._timeout = timeout

    # ---- connection ------------------------------------------------------

    def _connect_sync(self):
        """Dial the speaker directly by IP (no mDNS) and wait until ready."""
        try:
            cc = pychromecast.get_chromecast_from_host(
                (self.host, _CAST_PORT, None, None, None)
            )
            cc.wait(timeout=self._timeout)
            return cc
        except Exception as e:  # pychromecast raises a grab-bag of errors
            raise CastError(
                f"Could not connect to Cast device at {self.host}:{_CAST_PORT}: "
                f"{type(e).__name__}: {e}"
            ) from e

    def _sync_media_session(self, cc, *, want_session: bool = True) -> str:
        """Re-attach to whatever is already playing on a freshly-opened
        connection. Each tool call dials a new connection, so the media
        controller starts blank; it only learns the running session after the
        receiver answers an update_status() request (an async push). Poll until
        a media session shows up (or we time out), then return the player state.
        Without this, a pause/resume issued immediately fails with 'no session
        active' / RequestFailed."""
        mc = cc.media_controller
        deadline = time.time() + self._timeout
        while time.time() < deadline:
            mc.update_status()
            time.sleep(0.6)
            st = mc.status
            if st and (st.media_session_id or not want_session):
                return st.player_state or "UNKNOWN"
        return (mc.status.player_state if mc.status else None) or "UNKNOWN"

    # ---- playback --------------------------------------------------------

    def _play_url_sync(self, url, title, content_type, is_live):
        cc = self._connect_sync()
        try:
            mc = cc.media_controller
            mc.play_media(
                url,
                content_type,
                title=title,
                stream_type="LIVE" if is_live else "BUFFERED",
            )
            mc.block_until_active(timeout=self._timeout)
            # Poll a few times for the receiver to actually start the stream.
            state = "UNKNOWN"
            for _ in range(8):
                mc.update_status()
                state = mc.status.player_state or "UNKNOWN"
                if state in _GOOD_STATES:
                    break
                time.sleep(1)
            if state not in _GOOD_STATES:
                raise CastError(
                    f"Cast did not start playing (state={state}). The URL may be "
                    f"unreachable or an unsupported format: {url}"
                )
            return state
        finally:
            cc.disconnect()

    async def play_url(
        self,
        url: str,
        *,
        title: str | None = None,
        content_type: str | None = None,
        is_live: bool | None = None,
    ) -> str:
        ct = content_type or guess_content_type(url)
        live = looks_live(url) if is_live is None else is_live
        return await asyncio.to_thread(
            self._play_url_sync, url, title, ct, live
        )

    # ---- transport / control --------------------------------------------

    def _control_sync(self, action: str):
        cc = self._connect_sync()
        try:
            mc = cc.media_controller
            if action == "stop":
                # Quitting the receiver app stops playback and clears the
                # session; no need to attach to it first.
                cc.quit_app()
                return
            # pause/resume need the running media session attached first.
            self._sync_media_session(cc)
            if action == "pause":
                mc.pause()
            elif action == "resume":
                mc.play()
            else:
                raise CastError(f"unknown control action {action!r}")
        finally:
            cc.disconnect()

    async def stop(self):
        await asyncio.to_thread(self._control_sync, "stop")

    async def pause(self):
        await asyncio.to_thread(self._control_sync, "pause")

    async def resume(self):
        await asyncio.to_thread(self._control_sync, "resume")

    def _set_volume_sync(self, level: int):
        cc = self._connect_sync()
        try:
            cc.set_volume(max(0, min(100, int(level))) / 100.0)
        finally:
            cc.disconnect()

    async def set_volume(self, level: int):
        """Set the Cast *receiver* session volume (0-100). Note this is the
        Cast app volume, distinct from the KEF hardware volume."""
        await asyncio.to_thread(self._set_volume_sync, level)

    # ---- status ----------------------------------------------------------

    def _status_sync(self) -> dict:
        cc = self._connect_sync()
        try:
            mc = cc.media_controller
            # Attach to a running session if there is one (don't block the full
            # timeout when nothing is playing -- want_session=False returns as
            # soon as we have any status).
            self._sync_media_session(cc, want_session=False)
            st = mc.status
            cst = cc.status
            return {
                "player_state": (st.player_state or "UNKNOWN") if st else "UNKNOWN",
                "title": (st.title if st else None),
                "content_id": (st.content_id if st else None),
                "current_time": (st.current_time if st else None),
                "volume": round((cst.volume_level or 0) * 100) if cst else None,
                "app": (cst.display_name if cst else None),
            }
        finally:
            cc.disconnect()

    async def status(self) -> dict:
        return await asyncio.to_thread(self._status_sync)
