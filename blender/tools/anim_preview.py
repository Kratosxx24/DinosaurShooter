"""Contact sheets of a rigged generator's clips, rendered in a separate background Blender (never the
live session), plus an optional GLB export with skin + every action.

    blender -b --factory-startup --python tools/anim_preview.py -- <generator.py> <out_prefix>
        [--cols 8] [--views side,front34] [--only Walk] [--export <out.glb>] [--no-draco] [--set KEY=VALUE]

Writes <out_prefix>_<view>.png: one row per action, --cols evenly spaced frames per row. Workbench, so it
is fast and shows form rather than materials. Clips named *Walk* travel forward at the armature's
`walk_speed` property: planted paws must then stand still against the 0.5 m floor ruler (no foot slide).
"""
import bpy
import json
import math
import os
import struct
import sys
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
gen, prefix = os.path.abspath(argv[0]), os.path.abspath(argv[1])
opt = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d
cols = int(opt("--cols", 8))
views = opt("--views", "side,front34").split(",")
only = opt("--only")
export = opt("--export")
draco = "--no-draco" not in argv

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
g = {"__name__": "__main__", "__file__": gen}
for i, a in enumerate(argv):          # --set KEY=VALUE injects generator parameters (KIND=rex, ...)
    if a == "--set":
        k, v = argv[i + 1].split("=", 1)
        g[k] = v
exec(compile(open(gen, encoding="utf-8").read(), gen, "exec"), g)
col = bpy.data.collections[g["COLLECTION"]]
arm = next(o for o in col.all_objects if o.type == "ARMATURE")
meshes = [o for o in col.all_objects if o.type == "MESH"]
actions = [a for a in bpy.data.actions if a.name.startswith(g["PREFIX"])]
actions.sort(key=lambda a: ("Idle" not in a.name, "Walk" not in a.name, "Run" not in a.name, a.name))
if only:
    actions = [a for a in actions if only in a.name]
speed = float(arm.get("walk_speed", 0))

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
sh = scene.display.shading
sh.light, sh.color_type, sh.single_color = "STUDIO", "OBJECT", (0.7, 0.7, 0.72)
sh.show_cavity, sh.show_shadows = True, True
scene.render.resolution_x, scene.render.resolution_y = 520, 330
scene.render.film_transparent = False
for o in meshes:
    o.color = (0.62, 0.6, 0.58, 1)

# floor + ruler posts every 0.5 m along the travel axis (the cat faces -Y)
studio = bpy.data.collections.new("_Studio")
scene.collection.children.link(studio)


def box(name, loc, size, color):
    me = bpy.data.meshes.new(name)
    x, y, z = (s / 2 for s in size)
    me.from_pydata([(sx * x, sy * y, sz * z) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)], [],
                   [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
    ob = bpy.data.objects.new(name, me)
    ob.location, ob.color = loc, color
    studio.objects.link(ob)


box("_floor", (0, 0, -0.01), (30, 30, 0.02), (0.32, 0.33, 0.35, 1))
for i in range(-24, 13):
    box(f"_tick{i}", (1.4, i * 0.5, 0.02), (0.08, 0.04 if i % 2 else 0.08, 0.04), (0.9, 0.5, 0.2, 1))

cam_d = bpy.data.cameras.new("_cam")
cam = bpy.data.objects.new("_cam", cam_d)
studio.objects.link(cam)
scene.camera = cam


def aim(loc, target):
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()


def frame_of(act, c):
    a, b = act.frame_range
    return a + (b - a) * c / cols


def shoot(path):
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    px = np.array(img.pixels[:], dtype=np.float32).reshape(img.size[1], img.size[0], 4)
    bpy.data.images.remove(img)
    return px


for view in views:
    rows = []
    for act in actions:
        arm.animation_data.action = act
        travel = float(arm.get("run_speed", 0)) if "Run" in act.name else speed if "Walk" in act.name else 0.0
        dur = (act.frame_range[1] - act.frame_range[0]) / scene.render.fps
        cells = []
        for c in range(cols):
            f = frame_of(act, c)
            scene.frame_set(int(f), subframe=f - int(f))
            arm.location.y = -travel * dur * c / cols + (travel * dur / 2 if travel else 0)
            if view == "side":        # orthographic from the cat's left: gait, ground contact, slide
                cam_d.type, cam_d.ortho_scale = "ORTHO", 8.4
                aim((14, 1.1, 1.6), (0, 1.1, 1.4))
            else:                     # three-quarter front, perspective
                cam_d.type, cam_d.lens = "PERSP", 42
                aim((6.2, -7.8, 3.2), (0, 0.4, 1.1))
            cells.append(shoot(f"{prefix}_cell.png"))
        rows.append(np.concatenate(cells, axis=1))
    sheet = np.concatenate(rows[::-1], axis=0)   # image rows run bottom-up: first action on top
    h, w = sheet.shape[:2]
    out = bpy.data.images.new("_sheet", w, h, alpha=True)
    out.pixels.foreach_set(sheet.ravel())
    out.filepath_raw, out.file_format = f"{prefix}_{view}.png", "PNG"
    out.save()
    print("sheet", out.filepath_raw, [a.name for a in actions])
if os.path.exists(f"{prefix}_cell.png"):
    os.remove(f"{prefix}_cell.png")

if export:
    arm.location = (0, 0, 0)
    arm.animation_data.action = actions[0]
    scene.frame_set(0)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in [arm] + meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(
        filepath=export, export_format="GLB", use_selection=True, export_yup=True, export_apply=True,
        export_draco_mesh_compression_enable=draco, export_cameras=False, export_lights=False,
        export_skins=True, export_animations=True, export_animation_mode="ACTIONS", export_extras=True,
        export_vertex_color="ACTIVE",
    )
    with open(export, "rb") as f:
        data = f.read()
    n = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + n])
    acc = doc["accessors"]
    print(f"EXPORTED {os.path.getsize(export)} bytes -> {export}")
    print(f"  skins: {[len(s['joints']) for s in doc.get('skins', [])]} joints; "
          f"meshes: {len(doc['meshes'])}; draco: {'KHR_draco_mesh_compression' in doc.get('extensionsUsed', [])}")
    for a in doc.get("animations", []):
        dur = max(acc[s["input"]]["max"][0] for s in a["samplers"])
        print(f"  anim {a['name']}: {dur:.2f}s, {len(a['channels'])} channels")
