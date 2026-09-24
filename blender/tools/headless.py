"""Run a generator in a separate background Blender (never the user's live session), render
turntable-style preview shots, and optionally export the collection to GLB.

    blender -b --factory-startup --python tools/headless.py -- <generator.py> <out_prefix> [--export <out.glb>] [--no-draco]
        [--views front34,side] [--set PROP=vending --set VARIANT=cyan]

Shots land at <out_prefix>_<view>.png. The studio (floor, lights, camera) is built in this
throwaway process only, so nothing here touches a saved .blend.
"""
import bpy
import math
import os
import sys
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
gen, prefix = os.path.abspath(argv[0]), os.path.abspath(argv[1])
export = argv[argv.index("--export") + 1] if "--export" in argv else None
draco = "--no-draco" not in argv
views = argv[argv.index("--views") + 1].split(",") if "--views" in argv else ["front34", "rear34", "side", "top"]
bright = "--bright" in argv           # daylight studio: pale floor, strong key/fill/rim, for reading dark forms

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

g = {"__name__": "__main__", "__file__": gen}
for i, a in enumerate(argv):          # --set KEY=VALUE injects generator parameters (PROP, VARIANT, ...)
    if a == "--set":
        k, v = argv[i + 1].split("=", 1)
        g[k] = v
exec(compile(open(gen, encoding="utf-8").read(), gen, "exec"), g)
col = bpy.data.collections[g["COLLECTION"]]
objs = [o for o in col.all_objects if o.type == "MESH"]

# bounds of the asset
lo = Vector((1e9, 1e9, 1e9)); hi = -lo
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
center = (lo + hi) / 2
size = max((hi - lo).length, 0.5)

scene = bpy.context.scene
for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
    try:
        scene.render.engine = eng
        break
    except TypeError:
        pass
scene.render.resolution_x, scene.render.resolution_y = 1100, 700
scene.render.film_transparent = False
try:
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Punchy"
except TypeError:
    pass
try:
    scene.eevee.use_raytracing = True
except AttributeError:
    pass

world = bpy.data.worlds.new("Studio")
scene.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs[0].default_value = (0.55, 0.6, 0.68, 1) if bright else (0.012, 0.02, 0.045, 1)
bg.inputs[1].default_value = 1.0

studio = bpy.data.collections.new("_Studio")
scene.collection.children.link(studio)

floor_me = bpy.data.meshes.new("_floor")
r = size * 6
floor_me.from_pydata([(-r, -r, 0), (r, -r, 0), (r, r, 0), (-r, r, 0)], [], [(0, 1, 2, 3)])
floor = bpy.data.objects.new("_floor", floor_me)
fm = bpy.data.materials.new("_floor")
fm.use_nodes = True
b = next(n for n in fm.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
b.inputs["Base Color"].default_value = (0.45, 0.46, 0.48, 1) if bright else (0.02, 0.022, 0.03, 1)
b.inputs["Roughness"].default_value = 0.6 if bright else 0.25       # matte cyc / wet-street sheen
floor_me.materials.append(fm)
studio.objects.link(floor)


def light(name, kind, energy, loc, color=(1, 1, 1), size_=2.0):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind == "AREA":
        ld.size = size_
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    d = center - Vector(loc)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    studio.objects.link(ob)


s = size
if bright:
    light("_key", "AREA", 1400 * s, center + Vector((s * 0.9, -s * 1.0, s * 1.3)), (1.0, 0.95, 0.88), s * 1.2)
    light("_fill", "AREA", 500 * s, center + Vector((-s * 1.3, -s * 0.6, s * 0.5)), (0.85, 0.92, 1.0), s * 1.5)
    light("_rim", "AREA", 1200 * s, center + Vector((-s * 0.4, s * 1.3, s * 0.9)), (0.8, 0.88, 1.0), s)
    light("_top", "AREA", 400 * s, center + Vector((0, 0, s * 2)), (1.0, 1.0, 1.0), s * 2)
else:
    light("_key", "AREA", 400 * s, center + Vector((s * 0.9, -s * 1.1, s * 1.2)), (1.0, 0.92, 0.85), s)
    light("_rimM", "AREA", 500 * s, center + Vector((-s * 1.2, s * 0.9, s * 0.6)), (1.0, 0.18, 0.6), s)
    light("_rimC", "AREA", 500 * s, center + Vector((s * 1.3, s * 0.8, s * 0.4)), (0.0, 0.8, 1.0), s)
    light("_top", "AREA", 150 * s, center + Vector((0, 0, s * 2)), (0.7, 0.8, 1.0), s * 2)

if "--frame" in argv:                 # --frame x,y,z,size: frame a detail (e.g. a head) instead of the whole asset
    fx, fy, fz, fs = map(float, argv[argv.index("--frame") + 1].split(","))
    center, size = Vector((fx, fy, fz)), fs

cam_d = bpy.data.cameras.new("_cam")
cam_d.lens = 50
cam = bpy.data.objects.new("_cam", cam_d)
studio.objects.link(cam)
scene.camera = cam

VIEWS = {  # direction from center (asset front = -Y in Blender)
    "front34": Vector((0.8, -1.0, 0.38)),
    "rear34": Vector((-0.85, 1.0, 0.42)),
    "side": Vector((1.0, 0.0, 0.12)),
    "top": Vector((0.35, -0.5, 1.4)),
    "front": Vector((0.0, -1.0, 0.15)),
    "low": Vector((0.9, -0.7, 0.08)),
}
for name in views:
    d = VIEWS[name].normalized()
    # fit the bounding sphere in the (narrower) vertical field of view
    vfov = 2 * math.atan(18 * scene.render.resolution_y / scene.render.resolution_x / cam_d.lens)
    cam.location = center + d * (size / 2) / math.tan(vfov / 2) * 1.08
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = f"{prefix}_{name}.png"
    bpy.ops.render.render(write_still=True)
    print("shot", scene.render.filepath)

if export:
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs + [o for o in col.all_objects if o.type == "EMPTY"]:     # empties = named sockets (muzzle, sight)
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(
        filepath=export, export_format="GLB", use_selection=True, export_yup=True,
        export_apply=True, export_draco_mesh_compression_enable=draco,
        export_cameras=False, export_lights=False,
    )
    dg = bpy.context.evaluated_depsgraph_get()
    tris = 0
    for o in objs:
        me = o.evaluated_get(dg).to_mesh()
        me.calc_loop_triangles()
        tris += len(me.loop_triangles)
        o.evaluated_get(dg).to_mesh_clear()
    print(f"EXPORTED {len(objs)} objects, {tris} tris, {os.path.getsize(export)} bytes -> {export}")
