# DinosaurShooter

First-person dinosaur wave shooter in the browser (working title "Mist Hunt"). Three.js 0.170 via
CDN import map, no build step. Everything lives in `index.html` for now.

## Run
`python tools/serve.py 8020`, then open http://localhost:8020 (launch config "game"). Click to start.
`window.game` is a test harness: `begin()`, `sim(sec, keys)`, `spawn(kind, dist, angDeg)`,
`aimAt(dino)`, `shoot(n)`, `teleport(x, z, yawDeg)`, `snap(name)` (saves `screenshots/<name>.png`).

## Assets come from blender-lab
`assets/` is **generated** in `~/blender-lab` and copied here. Don't hand-edit GLBs; change the
generator there, re-export, and copy the new file over. Bump the version (`_v1` -> `_v2`, the `V`
constant in index.html) when a file's contents change shape.

| file | source in blender-lab |
|---|---|
| `raptor_v1.glb`, `rex_v1.glb` | `generators/dino.py` (KIND=raptor / rex), via `tools/anim_preview.py --export` |
| `rifle_v1.glb` | `generators/rifle.py` |
| `world_v1.glb`, `plants_v1.glb`, `instances_v1.json` | `tools/export_forest_game.py` (builds `renders/forest_house.py --game`) |
| `tex/*.jpg` | Poly Haven textures used by the forest scene |
