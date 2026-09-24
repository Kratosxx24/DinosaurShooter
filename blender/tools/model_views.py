"""Close-up stills of a generator's model (rest pose, or a clip frame), rendered in a background Blender.
For judging form: silhouette, joints, head shape. Complements anim_preview.py's small contact sheets.

    blender -b --factory-startup --python tools/model_views.py -- <generator.py> <out_prefix>
        [--set KEY=VALUE] [--pose Run:0.25] [--color vertex|single] [--engine eevee] [--size 900x600] [--detail]

Writes <out_prefix>_views.png: a 2x2 grid of side, three-quarter front, three-quarter rear and a head close-up.
"""
import bpy
import os
import sys
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
gen, prefix = os.path.abspath(argv[0]), os.path.abspath(argv[1])
opt = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d
W, H = (int(x) for x in opt("--size", "900x600").split("x"))

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
g = {"__name__": "__main__", "__file__": gen}
for i, a in enumerate(argv):
    if a == "--set":
        k, v = argv[i + 1].split("=", 1)
        g[k] = v
exec(compile(open(gen, encoding="utf-8").read(), gen, "exec"), g)
col = bpy.data.collections[g["COLLECTION"]]
arm = next((o for o in col.all_objects if o.type == "ARMATURE"), None)
meshes = [o for o in col.all_objects if o.type == "MESH"]
scene = bpy.context.scene

pose = opt("--pose")
if arm and pose:
    name, t = pose.split(":")
    act = bpy.data.actions[g["PREFIX"] + name]
    arm.animation_data.action = act
    a, b = act.frame_range
    f = a + (b - a) * float(t)
    scene.frame_set(int(f), subframe=f - int(f))
elif arm and arm.animation_data:
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.rotation_euler = (0, 0, 0)
        pb.location = (0, 0, 0)
bpy.context.view_layer.update()

scene.render.engine = "BLENDER_WORKBENCH"
sh = scene.display.shading
sh.light = "STUDIO"
sh.color_type = "VERTEX" if opt("--color", "single") == "vertex" else "SINGLE"
sh.single_color = (0.62, 0.6, 0.57)
sh.show_cavity, sh.show_shadows = True, True
sh.cavity_type = "BOTH"
sh.show_specular_highlight = True
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.world = scene.world or bpy.data.worlds.new("W")
if opt("--engine") == "eevee":                 # materials + a sun, for judging colour
    scene.render.engine = "BLENDER_EEVEE"
    scene.view_settings.view_transform = "AgX"
    scene.world.use_nodes = True
    bg = next(n for n in scene.world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value, bg.inputs["Strength"].default_value = (0.5, 0.55, 0.6, 1), 0.6
    sun = bpy.data.objects.new("_sun", bpy.data.lights.new("_sun", "SUN"))
    sun.data.energy = 3.5
    sun.rotation_euler = (0.9, 0.2, 0.6)
    scene.collection.objects.link(sun)

floor = bpy.data.meshes.new("_floor")
floor.from_pydata([(-20, -20, 0), (20, -20, 0), (20, 20, 0), (-20, 20, 0)], [], [(0, 1, 2, 3)])
fo = bpy.data.objects.new("_floor", floor)
scene.collection.objects.link(fo)

# bounds of the evaluated meshes
dg = bpy.context.evaluated_depsgraph_get()
pts = []
for o in meshes:
    ev = o.evaluated_get(dg)
    pts += [ev.matrix_world @ v.co for v in ev.to_mesh().vertices]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
c = (lo + hi) / 2
size = (hi - lo).length
head = g["K"]["skull"][0] if "K" in g and "skull" in g["K"] else hi

cam_d = bpy.data.cameras.new("_cam")
cam = bpy.data.objects.new("_cam", cam_d)
scene.collection.objects.link(cam)
scene.camera = cam


def shot(loc, target, lens, path):
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cam_d.lens = lens
    cam_d.clip_end = 200
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    px = np.array(img.pixels[:], dtype=np.float32).reshape(img.size[1], img.size[0], 4)
    bpy.data.images.remove(img)
    os.remove(path)
    return px


d = size * 1.25
tmp = prefix + "_tmp.png"
# the creature faces -Y; its left side is +X
side = shot(c + Vector((d * 1.6, 0, 0.1 * size)), c, 60, tmp)
front = shot(c + Vector((d * 0.8, -d * 1.1, 0.35 * size)), c, 50, tmp)
rear = shot(c + Vector((-d * 0.9, d * 1.0, 0.45 * size)), c, 50, tmp)
hv = Vector(head)
close = shot(hv + Vector((size * 0.28, -size * 0.3, size * 0.08)), hv + Vector((0, -size * 0.05, -size * 0.02)), 50, tmp)
if "--detail" in argv:                       # macro shots: the eye, the face, the foot, the shin
    K = g["K"]
    eye = g["ROT"] @ Vector(g["EYES"][0][0]) if "EYES" in g else hv
    foot = K["ballL"][0]
    shin = K["ankleL"][0].lerp(K["kneeL"][0], 0.4)
    s_ = g["S"]
    rear = shot(eye + Vector((0.3, -0.16, 0.05)) * s_, eye, 60, tmp)
    close = shot(hv + Vector((0.55, -0.6, 0.2)) * s_, hv + Vector((0, -0.12, -0.03)) * s_, 50, tmp)
    side = shot(foot + Vector((0.55, -0.5, 0.3)) * s_, foot + Vector((0, -0.1, 0.03)) * s_, 50, tmp)
    front = shot(shin + Vector((0.75, -0.35, 0.1)) * s_, shin, 50, tmp)
sheet = np.concatenate([np.concatenate([rear, close], axis=1), np.concatenate([side, front], axis=1)], axis=0)
out = bpy.data.images.new("_sheet", sheet.shape[1], sheet.shape[0], alpha=True)
out.pixels.foreach_set(sheet.ravel())
out.filepath_raw, out.file_format = prefix + "_views.png", "PNG"
out.save()
print("views", out.filepath_raw)
