"""Shared setup for the render gallery. Each scene script does:

    import sys, os; sys.path.insert(0, os.path.dirname(__file__)); from _common import *
    args = start()                  # wipes the (factory) scene, parses argv
    ... build ...
    finish(args, samples=512)      # Cycles on the GPU, denoised, writes the PNG

Run in a BACKGROUND Blender only:
    blender -b --factory-startup --python renders/<scene>.py -- <out.png> [--preview] [--res 1920x1080]
"""
import bpy
import math
import os
import sys
from mathutils import Vector

HDRI_DIR = os.path.join(bpy.utils.system_resource("DATAFILES"), "studiolights", "world")


class Args:
    pass


def start():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    a = Args()
    a.out = os.path.abspath(argv[0]) if argv and not argv[0].startswith("--") else None
    a.preview = "--preview" in argv
    a.res = (1920, 1080)
    if "--res" in argv:
        w, h = argv[argv.index("--res") + 1].split("x")
        a.res = (int(w), int(h))
    a.save = argv[argv.index("--save") + 1] if "--save" in argv else None
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras,
                 bpy.data.curves, bpy.data.worlds):
        for d in list(coll):
            coll.remove(d)
    return a


def use_gpu(scene):
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = backend
            prefs.get_devices()
            devs = [d for d in prefs.devices if d.type == backend]
            if devs:
                for d in prefs.devices:
                    d.use = d.type == backend
                scene.cycles.device = "GPU"
                print("render device:", backend, [d.name for d in devs])
                return backend
        except TypeError:
            continue
    print("render device: CPU")
    return None


def mat(name, color=(0.8, 0.8, 0.8), rough=0.5, metal=0.0, **inputs):
    """Principled material; extra inputs by socket name, e.g. mat(..., **{"Transmission Weight": 1})."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*color[:3], 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    for k, v in inputs.items():
        b.inputs[k].default_value = v
    return m


def bsdf(m):
    return next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def emission_mat(name, color, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (*color[:3], 1)
    e.inputs["Strength"].default_value = strength
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(e.outputs[0], o.inputs["Surface"])
    return m


def assign(ob, m):
    ob.data.materials.clear()
    ob.data.materials.append(m)
    return ob


def world_hdri(name="sunset.exr", strength=1.0, rot_z=0.0, camera_color=None, camera_strength=1.0):
    """HDRI world from Blender's bundled studio lights. camera_color: flat backdrop seen by camera only."""
    w = bpy.data.worlds.new("World")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value[2] = rot_z
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(os.path.join(HDRI_DIR, name))
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    if camera_color is None:
        nt.links.new(bg.outputs[0], out.inputs["Surface"])
    else:
        lp = nt.nodes.new("ShaderNodeLightPath")
        flat = nt.nodes.new("ShaderNodeBackground")
        flat.inputs["Color"].default_value = (*camera_color[:3], 1)
        flat.inputs["Strength"].default_value = camera_strength
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
        nt.links.new(bg.outputs[0], mix.inputs[1])
        nt.links.new(flat.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return w


def world_color(color, strength=1.0):
    w = bpy.data.worlds.new("World")
    bpy.context.scene.world = w
    w.use_nodes = True
    bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = (*color[:3], 1)
    bg.inputs["Strength"].default_value = strength
    return w


def camera(loc, target, lens=50, fstop=None, focus=None, name="Cam"):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.clip_start = 0.01
    cd.clip_end = 20000
    cam = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = loc
    d = Vector(target) - Vector(loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    if fstop:
        cd.dof.use_dof = True
        cd.dof.aperture_fstop = fstop
        cd.dof.focus_distance = focus if focus else d.length
    bpy.context.scene.camera = cam
    return cam


def light(kind, loc, energy, color=(1, 1, 1), size=1.0, target=None, name=None, spot_deg=None):
    ld = bpy.data.lights.new(name or kind, kind)
    ld.energy = energy
    ld.color = color[:3]
    if kind == "AREA":
        ld.size = size
    elif kind in ("POINT", "SPOT"):
        ld.shadow_soft_size = size
    elif kind == "SUN":
        ld.angle = size
    if kind == "SPOT" and spot_deg:
        ld.spot_size = math.radians(spot_deg)
        ld.spot_blend = 0.4
    ob = bpy.data.objects.new(name or kind, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    if target is not None:
        d = Vector(target) - Vector(loc)
        ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return ob


def link(ob):
    bpy.context.scene.collection.objects.link(ob)
    return ob


def finish(a, samples=512, look="AgX - Medium High Contrast", exposure=0.0, bounces=None,
           caustics=False, film_transparent=False, extra=None):
    scene = bpy.context.scene
    use_gpu(scene)
    c = scene.cycles
    c.samples = max(32, samples // 8) if a.preview else samples
    c.use_denoising = True
    c.use_adaptive_sampling = True
    c.adaptive_threshold = 0.01
    c.caustics_reflective = caustics
    c.caustics_refractive = caustics
    if bounces:
        c.max_bounces = bounces
        c.glossy_bounces = min(bounces, 12)
        c.transmission_bounces = bounces
        c.transparent_max_bounces = max(bounces, 16)
    r = scene.render
    r.resolution_x, r.resolution_y = a.res
    r.resolution_percentage = 40 if a.preview else 100
    r.film_transparent = film_transparent
    vs = scene.view_settings
    try:
        vs.view_transform = "AgX"
        vs.look = look
    except TypeError:
        pass
    vs.exposure = exposure
    r.image_settings.file_format = "PNG"
    if extra:
        extra(scene)
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.save))
    if a.out:
        r.filepath = a.out
        bpy.ops.render.render(write_still=True)
        print("WROTE", a.out)
