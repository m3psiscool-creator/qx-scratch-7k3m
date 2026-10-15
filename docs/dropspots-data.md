# Loading landing data for the Dropspots tab

Epic's leaderboard has no location data, so landing rows have to come from somewhere else: a replay parser,
a data provider's API (for example Osirion's, which needs an account, an API key and paid credits), or your own
export. The site only needs one row per team per game.

## Upload

`POST /api/admin/drops` with the header `x-admin-key: <ADMIN_KEY>` and a JSON body:

```json
{
  "window_id": "S42_ReloadCashCup_DuosZB_Event5Round1_NAC",
  "append": false,
  "coords": "unit",
  "map": {
    "name": "Reload map, season 42",
    "image": "https://example.com/map.png",
    "credit": "Map image: <who it is from>",
    "pois": [{ "name": "Tilted", "x": 0.41, "y": 0.62, "r": 0.03 }]
  },
  "drops": [
    { "game": 1, "team": "<account id>+<account id>", "x": 0.4123, "y": 0.6201, "poi": "Tilted",
      "placement": 7, "points": 23, "rank": 120, "win": false }
  ]
}
```

- `coords`: `"unit"` (x and y between 0 and 1 across the map image, top-left is 0,0) or `"world"` (game units; then also send
  `"bounds": [minX, maxX, minY, maxY]` and, if the image's y axis runs the other way, `"flip_y": true`).
- `team`: account ids joined by `+`. Names are looked up for the best teams; any text works too.
- `rank`: the team's final rank in the event. Leave it out and it is filled from the stored top 1,000 when the event has finished.
- `points`: points for that game. Leave it out and send `"elims"` instead; the event's scoring rules compute the points.
- `placement`: finishing place in that game. `win`: true for the winner.
- At most 20,000 rows per request. Send the first batch without `append`, the rest with `"append": true`
  (`scripts/import_drops.py` does this for you).
- `map` is optional but it is what names the map on the page. `image` must be an `https://` address you may use.

## Script

```
set ADMIN_KEY=<your admin key>
python scripts/import_drops.py landings.json
```

`landings.json` is the body above (one tournament per file). The script chunks the rows and prints what was stored.

## What the page does with it

Heatmaps of everyone and of the teams that qualified (final rank within the top N you choose), a game filter, drawn
areas (rectangle or freehand) with the stats of the teams that landed inside them, and a comparison of the named spots.

## Map pictures
Landings are stored as 0-1 coordinates across a square that is the same for every event (world units -55000..55000; u = world Y, v = -world X, set by `MAP_BOUNDS` in `worker/run.mjs`).
A map picture must be drawn in that same square. `drops.MAPS` lists the maps that have one, by the codename in the playlist id (`SourSpawn` = Nitemare Island), and `/maps/<name>.jpg` serves it.

To add a map (when a new codename shows up in `/api/drops/info`):
1. Download the map's overview image (the Fortnite Wiki has one per Reload map: `File:<Map> - Island - Fortnite Reload.png`, API `fortnite.fandom.com/api.php`).
2. `tools/mapfit/identify_map.py <window>` tells which candidate image the landings fit best (share of landings on land); check with names seen in the replay data (e.g. "Estate" for Nitemare's Estranged Estate).
3. `tools/mapfit/fit_map.py <image prefix>` finds rotation, scale and centre and draws the landings over the picture for a visual check.
4. `tools/mapfit/render_map.py <out dir>` writes the picture warped into the 0-1 frame; set k, L, cx, cy to the fitted values. Add it to `web/maps` and an entry to `drops.MAPS`.
Nitemare Island fit: rotated 90 degrees, scale 1.56, centre (0.50, 0.54); 96% of landings fall on land and the hot spots sit on the towns.
