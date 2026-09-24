# DinosaurShooter

First-person dinosaur wave shooter in the browser (working title "Mist Hunt"). Three.js 0.170 via
CDN import map, no build step. Everything lives in `index.html` for now.

## Run
`python tools/serve.py 8020`, then open http://localhost:8020 (launch config "game"). Click to start.
`window.game` is a test harness: `begin()`, `sim(sec, keys)`, `spawn(kind, dist, angDeg)`,
`aimAt(dino)`, `shoot(n)`, `teleport(x, z, yawDeg)`, `snap(name)` (saves `screenshots/<name>.png`).

## Deploy
`npx wrangler deploy` publishes the repo root as static assets on Cloudflare Workers
(https://dinosaur-shooter.codexcanon.workers.dev). `wrangler.jsonc` is the config, `.assetsignore` keeps
tooling and sources out, and `_headers` caches `assets/*.glb|json` as immutable (so bump versions). Commit first.

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
| `raptor_v2.glb` | `blender/generators/dino.py` (KIND=raptor): metaball body + alpha-card feathers (`Raptor_Feathers`), baked scale normal/detail maps, painted-iris eyes; 22-bone FK rig, clips Idle/Run/Attack/Roar/Death, `knots` extras for hitboxes; loaded via `RAPTOR_V`. index.html keeps its Skin/Eye/Feather textures (alphaTest, DoubleSide). Close-ups: `blender/tools/model_views.py --engine eevee --detail` |
| `rex_v2.glb` | `blender/generators/rex.py`: SDF-sculpted body (`sdf.py`: splined sweeps + ellipsoid muscles -> surface nets), decimated to 12k tris; same rig/clip/knot contract. `DETAIL=hero` builds the dense mesh for `blender/renders/rex_showcase.py` (Cycles: `--shot hero|head`, `--preview`) |
| `rifle_v2.glb` | `blender/generators/rifle.py`: scoped carbine, nodes Rifle_Body/Mag/Bolt + empties Rifle_Muzzle/Rifle_Sight (scope eye point); loaded via `RIFLE_V` |
| `world_v2.glb`, `plants_v2.glb`, `instances_v2.json` | `blender/tools/export_world.py` (builds `blender/world/forest_house.py --game`; plants from `world/_flora.py`); loaded via `WORLD_V`. The `Water` sheet covers the channel only: UVMap = metres along/across the flow, 2nd UV set x = depth to the bed, read by the water shader in index.html |
| `tex/*.jpg` | Poly Haven CC0: forest_leaves_02, bark_brown_02, mossy_rock, concrete_wall_003, wood_floor_deck |

## Sound
Recorded samples in `assets/sfx/`, built by `tools/sfx_build.py` (cuts of CC0 Freesound previews, one `RECIPE` line each), listed per slot (`rex.roar`, `rifle.shot`, ...) in `assets/sfx/sfx_v2.json`
(loaded via `SFX_V`; slot defaults in `SLOTS` in index.html). Slots can layer several files with pitch ranges.
An empty slot falls back to the synthesized sound. `game.hear(slot, dist)` auditions one, `game.sfx()` lists what
loaded. Format, slot table, sources and the credits table: `assets/sfx/README.md`. Never overwrite a sound file
in place (cached immutable): new name, and bump the manifest version if it changed after shipping.

Generator conventions: parameters as constants at the top, seeded randomness, each builds into its own
collection, forward = Blender -Y (Three.js +Z) for creatures, barrel along +Y for the rifle (camera -Z).
Never touch the user's live Blender session from here; `build.py` always spawns a background Blender.
To look at a model in the user's open Blender (Blender MCP), exec the generator there: it only purges and
rebuilds its own collection, e.g. `exec(compile(open(gen).read(), gen, "exec"), {"__name__": "__main__", "__file__": gen})`.
`blender/` is excluded from the deployed site by `.assetsignore`.
