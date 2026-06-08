"""
One-time Spotify authorization helper.

Run this ONCE (on any machine with a browser) to get a refresh token, then put
that token into your .env as SPOTIFY_REFRESH_TOKEN. The server uses the refresh
token to mint access tokens forever after, no browser needed.

Usage:
    pip install requests
    set SPOTIFY_CLIENT_ID=...        (Windows: set / PowerShell: $env:SPOTIFY_CLIENT_ID=...)
    set SPOTIFY_CLIENT_SECRET=...
    python auth_spotify.py

Your Spotify app's Redirect URI must include EXACTLY:
    http://127.0.0.1:8888/callback
"""

import base64
import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "user-modify-playback-state user-read-playback-state"

if not (CLIENT_ID and CLIENT_SECRET):
    sys.exit("Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET env vars first.")

_auth_code = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(q)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if "code" in params:
            _auth_code["code"] = params["code"][0]
            self.wfile.write(b"<h2>Authorized. You can close this tab.</h2>")
        else:
            self.wfile.write(b"<h2>No code received.</h2>")

    def log_message(self, *a):
        pass  # quiet


def main():
    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
        }
    )
    print("Opening browser to authorize Spotify...")
    print("If it doesn't open, visit:\n", auth_url, "\n")
    webbrowser.open(auth_url)

    server = HTTPServer(("127.0.0.1", 8888), Handler)
    while "code" not in _auth_code:
        server.handle_request()

    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": _auth_code["code"],
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Authorization": f"Basic {basic}"},
        timeout=15,
    )
    r.raise_for_status()
    refresh = r.json()["refresh_token"]
    print("\n" + "=" * 60)
    print("SUCCESS. Add this line to your .env:\n")
    print(f"SPOTIFY_REFRESH_TOKEN={refresh}")
    print("=" * 60)


if __name__ == "__main__":
    main()
