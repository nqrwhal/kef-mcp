# Poke recipe

Paste this into Poke as a recipe (its automations feature) after connecting the
MCP server. It tells Poke how to use the KEF + Spotify tools.

```
When I ask you to play music, control the speakers, or change volume,
use my KEF + Spotify tools.

- To start music, call play_on_kef with my request as the query
  (e.g. an artist, playlist, album, or song). It powers on the KEF,
  switches it to wifi, and starts Spotify on it. Pass volume only if
  I specify one.
- For "louder/quieter" or a specific level, use kef_set_volume (0-100).
- For pause/resume use kef_play_pause; for skip use kef_next / kef_previous.
- "Turn off the speakers" -> kef_standby.
- If I ask what's playing, use kef_status.

If play_on_kef says the KEF Spotify Connect device wasn't found, tell me to
open Spotify and play to the KEF once so it registers, then retry.
```

## Things you can then say to Poke

- "Play Bonobo on the KEF"
- "Put on my Discover Weekly on the speakers"
- "Turn the KEF volume to 40"
- "Pause the music" / "Skip this track"
- "Turn the speakers off"
- "What's playing?"
