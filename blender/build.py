"""Rebuild game assets from their Blender generators, straight into assets/. Each target runs in its own
background Blender (never a live session), so it's safe to run while Blender is open.

    python blender/build.py                     # everything
    python blender/build.py raptor rifle        # just these
    python blender/build.py rifle --ver v2      # write rifle_v2.glb (then bump V in index.html)

targets: raptor (generators/dino.py), rex (generators/rex.py), rifle (generators/rifle.py), world (world/forest_house.py ->
world_vN.glb + plants_vN.glb + instances_vN.json). Preview sheets land in screenshots/ (git-ignored).
Set BLENDER to point at blender.exe if it isn't in the default install location.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets")
SHOTS = os.path.join(ROOT, "screenshots")
BLENDER = os.environ.get("BLENDER", r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")

args = sys.argv[1:]
ver = args[args.index("--ver") + 1] if "--ver" in args else "v1"
targets = [a for a in args if not a.startswith("--") and a != ver] or ["raptor", "rex", "rifle", "world"]


def tool(name):
    return os.path.join(HERE, "tools", name)


def gen(name):
    return os.path.join(HERE, "generators", name)


JOBS = {
    "raptor": [tool("anim_preview.py"), "--", gen("dino.py"), os.path.join(SHOTS, "raptor"), "--set", "KIND=raptor",
               "--cols", "6", "--no-draco", "--export", os.path.join(ASSETS, f"raptor_{ver}.glb")],
    "rex": [tool("anim_preview.py"), "--", gen("rex.py"), os.path.join(SHOTS, "rex"),
            "--cols", "6", "--no-draco", "--export", os.path.join(ASSETS, f"rex_{ver}.glb")],
    "rifle": [tool("headless.py"), "--", gen("rifle.py"), os.path.join(SHOTS, "rifle"), "--views", "side,front34",
              "--no-draco", "--export", os.path.join(ASSETS, f"rifle_{ver}.glb")],
    "world": [tool("export_world.py"), "--", "--ver", ver],
}

os.makedirs(SHOTS, exist_ok=True)
failed = []
for t in targets:
    if t not in JOBS:
        sys.exit(f"unknown target {t!r}; choose from {', '.join(JOBS)}")
    t0 = time.time()
    script, *rest = JOBS[t]
    p = subprocess.run([BLENDER, "-b", "--factory-startup", "--python", script, *rest], capture_output=True, text=True)
    log = p.stdout + p.stderr
    ok = p.returncode == 0 and "Traceback" not in log
    notes = [ln.strip() for ln in log.splitlines() if ln.startswith(("DINO", "RIFLE", "wrote", "total instanced"))]
    print(f"{'ok ' if ok else 'FAIL'} {t:7s} {time.time() - t0:5.1f}s  {' | '.join(notes)}")
    if not ok:
        failed.append(t)
        print("\n".join(ln for ln in log.splitlines() if "Error" in ln or "Traceback" in ln or ln.startswith("  File"))[-3000:])
for f in sorted(os.listdir(ASSETS)):
    if f.endswith((".glb", ".json")):
        print(f"  assets/{f:24s} {os.path.getsize(os.path.join(ASSETS, f)) // 1024:6d} KB")
sys.exit(1 if failed else 0)
