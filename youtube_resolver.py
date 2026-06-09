"""
Resolve a YouTube/SoundCloud (or any yt-dlp-supported) page or search query into
a direct, castable audio stream URL.

The Cast Default Media Receiver plays an HTTP(S) audio URL but knows nothing
about YouTube. yt-dlp extracts the underlying progressive audio stream URL from
a page (or, for a bare query, searches YouTube and takes the first hit). We then
hand that URL to CastClient.play_url, same as a radio stream.

yt-dlp is synchronous and does network I/O, so extraction runs in
asyncio.to_thread. Note: extraction is inherently fragile -- when a site changes
its internals, the fix is to bump the yt-dlp version and rebuild the image.
"""

from __future__ import annotations

import asyncio

import yt_dlp


class ResolveError(RuntimeError):
    pass

# Prefer a PROGRESSIVE (plain http, non-HLS) audio stream: the Cast Default
# Media Receiver plays those cleanly as a normal audio URL. Fall back to any
# bestaudio (which for 24/7 livestreams is HLS) and let the caller cast it as
# HLS/LIVE. noplaylist so a query/URL yields one item; default_search=ytsearch1
# turns a bare query into a YouTube search and takes the top hit, while a real
# URL is extracted directly.
_YDL_OPTS = {
    "format": "bestaudio[protocol^=http][protocol!*=m3u8]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "skip_download": True,
}


def _resolve_sync(query_or_url: str) -> dict:
    try:
        with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
            info = ydl.extract_info(query_or_url, download=False)
    except Exception as e:
        raise ResolveError(
            f"Could not resolve a playable stream for {query_or_url!r}: "
            f"{type(e).__name__}: {e}"
        ) from e

    # A search or playlist comes back as {entries: [...]}; take the first entry.
    if info.get("entries"):
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise ResolveError(f"No results found for {query_or_url!r}.")
        info = entries[0]

    url = info.get("url")
    if not url:
        raise ResolveError(
            f"yt-dlp returned no direct stream URL for {query_or_url!r}."
        )
    proto = info.get("protocol") or ""
    is_hls = "m3u8" in proto or url.lower().split("?")[0].endswith(".m3u8")
    return {
        "url": url,
        "title": info.get("title") or query_or_url,
        # HLS (livestreams) must be cast as an HLS LIVE stream, not audio/mpeg.
        "is_hls": is_hls,
        "is_live": bool(info.get("is_live")) or is_hls,
    }


async def resolve_stream_url(query_or_url: str) -> dict:
    """Resolve a query or page URL to a castable stream.

    Returns a dict: {url, title, is_hls, is_live}. The caller uses is_hls to
    pick the right Cast content-type/stream-type.
    """
    return await asyncio.to_thread(_resolve_sync, query_or_url)
