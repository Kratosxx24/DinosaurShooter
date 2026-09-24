# DinosaurShooter

First-person dinosaur wave shooter in the browser (working title "Mist Hunt"). Three.js 0.170 via
CDN import map, no build step. Everything lives in `index.html` for now.

## Run
`python tools/serve.py 8020`, then open http://localhost:8020 (launch config "game"). Click to start.
`window.game` is a test harness: `begin()`, `sim(sec, keys)`, `spawn(kind, dist, angDeg)`,
`aimAt(dino)`, `shoot(n)`, `teleport(x, z, yawDeg)`, `snap(name)` (saves `screenshots/<name>.png`).

## Assets are generated in `blender/`
`assets/` is **built** from the Python generators in `blender/` (Blender 5.2, run headless). Don't
hand-edit GLBs: change the generator, rebuild, check the preview in `screenshots/`, then test in game.

    python blender/build.py                  # everything, ~35 s
    python blender/build.py raptor rifle     # just these
    python blender/build.py rifle --ver v2   # new file name; then bump V (or RIFLE_V) in index.html

Bump the version (`_v1` -> `_v2` and `V` in index.html) when you ship a changed file: browsers and
Cloudflare cache by URL. `BLENDER` env var overrides the blender.exe path.

| file | source |
|---|---|
| `raptor_v1.glb`, `rex_v1.glb` | `blender/generators/dino.py` (KIND=raptor / rex): skin-modifier body, 22-bone FK rig, clips Idle/Run/Attack/Roar/Death, `knots` extras for hitboxes |
| `rifle_v2.glb` | `blender/generators/rifle.py`: scoped carbine, nodes Rifle_Body/Mag/Bolt + empties Rifle_Muzzle/Rifle_Sight (scope eye point); loaded via `RIFLE_V` |
| `world_v1.glb`, `plants_v1.glb`, `instances_v1.json` | `blender/tools/export_world.py` (builds `blender/world/forest_house.py --game`; plants from `world/_flora.py`) |
| `tex/*.jpg` | Poly Haven CC0: forest_leaves_02, bark_brown_02, mossy_rock, concrete_wall_003, wood_floor_deck |

Generator conventions: parameters as constants at the top, seeded randomness, each builds into its own
collection, forward = Blender -Y (Three.js +Z) for creatures, barrel along +Y for the rifle (camera -Z).
Never touch the user's live Blender session from here; `build.py` always spawns a background Blender.
To look at a model in the user's open Blender (Blender MCP), exec the generator there: it only purges and
rebuilds its own collection, e.g. `exec(compile(open(gen).read(), gen, "exec"), {"__name__": "__main__", "__file__": gen})`.
`blender/` is excluded from the deployed site by `.assetsignore`.
