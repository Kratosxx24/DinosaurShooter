"""Cycles showcase of the rex (generators/rex.py at DETAIL=hero) roaring in a misty forest.

Run in a BACKGROUND Blender only (from the repo root):
    blender -b --factory-startup --python blender/renders/rex_showcase.py -- screenshots/rex_hero.png
        [--preview] [--res 1920x1080] [--shot hero|head|low] [--save rex_hero.blend]

The game GLB is untouched by this: the render swaps the Principled placeholders for a skin shader
(pebbled scales, dorsal scutes, wrinkles, SSS, wet mouth), slit-pupil glowing eyes and ivory teeth.
"""
import bpy
import math
import os
import random
import sys
import numpy as np
from mathutils import Vector, Euler

HERE = os.path.dirname(os.path.abspath(__file__))
BL = os.path.dirname(HERE)
ROOT = os.path.dirname(BL)
sys.path.insert(0, os.path.join(BL, "world"))
from _common import start, finish, camera, light, mat, bsdf, assign, HDRI_DIR  # noqa: E402
import _flora as fl  # noqa: E402

a = start()
argv = sys.argv[sys.argv.index("--") + 1:]
SHOT = argv[argv.index("--shot") + 1] if "--shot" in argv else "hero"
TEX = os.path.join(ROOT, "assets", "tex")
rng = random.Random(3)
scene = bpy.context.scene

# ---------------------------------------------------------------- the rex, hero detail
gen = os.path.join(BL, "generators", "rex.py")
g = {"__name__": "__main__", "__file__": gen, "DETAIL": "hero", "HERO_H": "0.03" if a.preview else "0.018"}
exec(compile(open(gen, encoding="utf-8").read(), gen, "exec"), g)
arm = bpy.data.objects["Rex_Rig"]
body = bpy.data.objects["Rex_Body"]
me = body.data
co = np.empty(len(me.vertices) * 3, np.float32)
me.vertices.foreach_get("co", co)
rest = me.attributes.new("rest", "FLOAT_VECTOR", "POINT")      # texture space that doesn't swim with the pose
rest.data.foreach_set("vector", co)
sub = body.modifiers.new("Sub", "SUBSURF")                     # after the armature: smooth the posed surface
sub.levels, sub.render_levels = 0, 1

# the roar: chest up, neck coiled back, head turned to camera, jaw wide, tail sweeping
arm.animation_data.action = None
POSE = {"Pelvis": (0.04, 0.0, 0), "Chest": (-0.06, 0.06, 0), "Neck1": (-0.1, 0.16, 0), "Neck2": (-0.02, 0.16, 0),
        "Head": (0.06, 0.12, 0.14), "Jaw": (0.78, 0, 0),
        "Arm.L": (-0.55, 0.2, 0), "Fore.L": (0.55, 0, 0), "Arm.R": (-0.4, -0.2, 0), "Fore.R": (0.7, 0, 0),
        "Thigh.L": (-0.1, 0, 0), "Shin.L": (0.12, 0, 0), "Meta.L": (-0.02, 0, 0),
        "Thigh.R": (0.08, 0, 0), "Shin.R": (-0.02, 0, 0), "Meta.R": (-0.06, 0, 0),
        "Tail1": (0.04, 0.08, 0), "Tail2": (0.03, 0.12, 0), "Tail3": (0.02, 0.16, 0), "Tail4": (-0.02, 0.2, 0)}
for pb in arm.pose.bones:
    p, y, r = POSE.get(pb.name, (0, 0, 0))
    pb.rotation_mode = "XYZ"
    pb.rotation_euler = Euler((y, r, p), "XYZ")
    pb.location = (0, 0, 0)
arm.rotation_euler = (0, 0, math.radians(-2))                  # three-quarter to the camera
bpy.context.view_layer.update()

# drop the posed rex so its lowest foot touches z = 0
dg = bpy.context.evaluated_depsgraph_get()
ev = body.evaluated_get(dg)
zs = [(body.matrix_world @ v.co).z for v in ev.to_mesh().vertices]
ev.to_mesh_clear()
arm.location.z -= min(zs) - 0.01


def S(n_, name):
    """Enabled input by name (Mix nodes carry float/vector/colour sockets that share names)."""
    return next(x for x in n_.inputs if x.name == name and x.enabled)


def SO(n_):
    return next(x for x in n_.outputs if x.name == "Result" and x.enabled)


def node(nt, kind, loc=(0, 0), **inputs):
    n = nt.nodes.new(kind)
    n.location = loc
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


# ---------------------------------------------------------------- skin
def skin_material():
    """Domed scales that change by region (fine on the face and feet, pebbles on the body, big scutes down the
    back and spine, wide plates on the belly), each scale with its own height and tint; a wet, ridged mouth."""
    m = bpy.data.materials["Rex_Skin"]
    nt = m.node_tree
    for n_ in list(nt.nodes):
        nt.nodes.remove(n_)
    L = nt.links

    def link_or_set(sock, v):
        if isinstance(v, (int, float, tuple)):
            sock.default_value = v
        else:
            L.new(v, sock)

    def math_(op, a_, b_=0.0, c_=None, loc=(0, 0)):
        n_ = node(nt, "ShaderNodeMath", loc)
        n_.operation = op
        link_or_set(n_.inputs[0], a_)
        link_or_set(n_.inputs[1], b_)
        if c_ is not None:
            link_or_set(n_.inputs[2], c_)
        return n_.outputs[0]

    def mix(fac, a_, b_, kind="FLOAT", blend="MIX", loc=(0, 0)):
        n_ = node(nt, "ShaderNodeMix", loc)
        n_.data_type = kind
        n_.blend_type = blend
        for name, v in (("Factor", fac), ("A", a_), ("B", b_)):
            link_or_set(S(n_, name), v)
        return SO(n_)

    def maprange(v, fmin, fmax, tmin=0.0, tmax=1.0, smooth=False, loc=(0, 0)):
        n_ = node(nt, "ShaderNodeMapRange", loc, **{"From Min": fmin, "From Max": fmax, "To Min": tmin, "To Max": tmax})
        if smooth:
            n_.interpolation_type = "SMOOTHSTEP"
        L.new(v, n_.inputs["Value"])
        return n_.outputs[0]

    def channels(attr_name, loc):
        at = node(nt, "ShaderNodeAttribute", loc)
        at.attribute_name = attr_name
        sp = node(nt, "ShaderNodeSeparateColor", (loc[0] + 200, loc[1]))
        L.new(at.outputs["Color"], sp.inputs[0])
        return sp.outputs

    rst_n = node(nt, "ShaderNodeAttribute", (-2600, 0))
    rst_n.attribute_name = "rest"
    rst = rst_n.outputs["Vector"]
    col_n = node(nt, "ShaderNodeAttribute", (-800, 1000))
    col_n.attribute_name = "Col"
    col = col_n.outputs["Color"]
    dorsal, mouth, belly = channels("Rex_Detail", (-2600, 700))[:3]
    face, feet, spine = channels("Rex_Region", (-2600, 500))[:3]
    tongue, palate = channels("Rex_Mouth", (-2600, 300))[:2]

    # warp the lookup a little so no layer reads as a perfect Voronoi
    wn = node(nt, "ShaderNodeTexNoise", (-2400, -100), Scale=3.0, Detail=2.0)
    L.new(rst, wn.inputs["Vector"])
    wc = node(nt, "ShaderNodeVectorMath", (-2200, -100))
    wc.operation = "MULTIPLY_ADD"
    L.new(wn.outputs["Color"], wc.inputs[0])
    wc.inputs[1].default_value = (0.012, 0.012, 0.012)
    L.new(rst, wc.inputs[2])
    warped = wc.outputs[0]

    def scales(scale, y, stretch=None, dome=0.3, rnd=0.85):
        """Domed scale layer: smoothstep(distance to cell edge) x a per-cell height. Returns (height, cell random)."""
        v = warped
        if stretch:
            mp_ = node(nt, "ShaderNodeMapping", (-2000, y))
            mp_.inputs["Scale"].default_value = stretch
            L.new(v, mp_.inputs["Vector"])
            v = mp_.outputs[0]
        e = node(nt, "ShaderNodeTexVoronoi", (-1800, y), Scale=scale, Randomness=rnd)
        e.feature = "DISTANCE_TO_EDGE"
        L.new(v, e.inputs["Vector"])
        c_ = node(nt, "ShaderNodeTexVoronoi", (-1800, y - 200), Scale=scale, Randomness=rnd)
        L.new(v, c_.inputs["Vector"])
        cs = node(nt, "ShaderNodeSeparateColor", (-1600, y - 200))
        L.new(c_.outputs["Color"], cs.inputs[0])
        cell = cs.outputs[0]
        domed = maprange(e.outputs["Distance"], 0.0, dome, smooth=True, loc=(-1600, y))
        return math_("MULTIPLY", domed, math_("MULTIPLY_ADD", cell, 0.6, 0.55, loc=(-1400, y - 200)), loc=(-1200, y)), cell

    fine, _ = scales(62.0, -400, dome=0.28)
    med, cell = scales(30.0, -800, dome=0.3)
    scute, _ = scales(11.0, -1200, dome=0.22)
    spn, _ = scales(5.5, -1600, stretch=(1.6, 0.9, 1.0), dome=0.2, rnd=0.5)
    plate, _ = scales(16.0, -2000, stretch=(0.35, 1.7, 1.0), dome=0.18, rnd=0.35)     # belly: wide transverse plates

    h = mix(math_("MULTIPLY", dorsal, dorsal, loc=(-1000, -1000)), med, scute, loc=(-800, -900))
    h = mix(belly, h, plate, loc=(-600, -900))
    h = mix(math_("MAXIMUM", face, feet, loc=(-1000, -500)), h, fine, loc=(-400, -900))
    h = mix(spine, h, math_("MULTIPLY", spn, 1.4, loc=(-1000, -1600)), loc=(-200, -900))
    # wrinkles across the neck and limb creases, and a grit you only see up close
    wm = node(nt, "ShaderNodeMapping", (-2000, -2400))
    wm.inputs["Scale"].default_value = (1.2, 7.0, 1.6)
    L.new(rst, wm.inputs["Vector"])
    wr = node(nt, "ShaderNodeTexNoise", (-1800, -2400), Scale=1.4, Detail=6.0, Roughness=0.6)
    L.new(wm.outputs[0], wr.inputs["Vector"])
    grit = node(nt, "ShaderNodeTexNoise", (-1800, -2700), Scale=420.0, Detail=1.0)
    L.new(rst, grit.inputs["Vector"])
    h = math_("MULTIPLY_ADD", maprange(wr.outputs["Fac"], 0.45, 0.62, loc=(-1600, -2400)), -0.35, h, loc=(0, -900))
    body_h = math_("MULTIPLY_ADD", grit.outputs["Fac"], 0.08, h, loc=(200, -900))

    # mouth: transverse ridges on the palate, papillae on the tongue, smooth wet lining elsewhere
    rug = node(nt, "ShaderNodeTexWave", (-1800, -3000), Scale=6.0, Distortion=2.0, Detail=2.0)
    rug.wave_type = "BANDS"
    rug.bands_direction = "Y"
    L.new(rst, rug.inputs["Vector"])
    pap = node(nt, "ShaderNodeTexVoronoi", (-1800, -3300), Scale=260.0)
    L.new(rst, pap.inputs["Vector"])
    papr = maprange(pap.outputs["Distance"], 0.0, 0.5, 1.0, 0.0, loc=(-1600, -3300))
    mouth_h = math_("MULTIPLY", rug.outputs["Fac"], palate, loc=(-1400, -3000))
    mouth_h = math_("MULTIPLY_ADD", papr, tongue, mouth_h, loc=(-1200, -3200))
    height = mix(mouth, body_h, math_("MULTIPLY", mouth_h, 0.4, loc=(-1000, -3200)), loc=(400, -900))
    bump = node(nt, "ShaderNodeBump", (700, -600), Strength=0.6, Distance=0.009)
    L.new(height, bump.inputs["Height"])

    # colour: vertex colour x slow mottle x per-scale tint x crevice shade; the mouth keeps its vertex colour
    mot = node(nt, "ShaderNodeTexNoise", (-1400, 1200), Scale=2.2, Detail=4.0)
    L.new(rst, mot.inputs["Vector"])
    c1 = mix(1.0, col, maprange(mot.outputs["Fac"], 0.3, 0.7, 0.72, 1.3, loc=(-1200, 1200)), "RGBA", "MULTIPLY", (-900, 1000))
    c2 = mix(1.0, c1, maprange(cell, 0.0, 1.0, 0.8, 1.2, loc=(-1200, 900)), "RGBA", "MULTIPLY", (-700, 1000))
    c3 = mix(1.0, c2, maprange(body_h, 0.0, 0.8, 0.42, 1.12, loc=(-1200, 600)), "RGBA", "MULTIPLY", (-500, 1000))
    base = mix(mouth, c3, col, "RGBA", "MIX", (-300, 1000))

    b = node(nt, "ShaderNodeBsdfPrincipled", (1000, 0))
    L.new(base, b.inputs["Base Color"])
    L.new(bump.outputs[0], b.inputs["Normal"])
    L.new(mix(mouth, maprange(body_h, 0.0, 1.0, 0.74, 0.5, loc=(500, 200)), 0.1, loc=(750, 200)), b.inputs["Roughness"])
    L.new(mix(mouth, 0.12, 0.35, loc=(750, 400)), b.inputs["Subsurface Weight"])
    L.new(mix(mouth, 0.04, 0.6, loc=(750, 600)), b.inputs["Coat Weight"])
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.4, 0.22)
    b.inputs["Subsurface Scale"].default_value = 0.03
    b.inputs["Specular IOR Level"].default_value = 0.3
    b.inputs["Coat Roughness"].default_value = 0.08
    out = node(nt, "ShaderNodeOutputMaterial", (1300, 0))
    L.new(b.outputs[0], out.inputs["Surface"])


def eye_material():
    m = bpy.data.materials["Rex_Eye"]
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    L = nt.links
    out = node(nt, "ShaderNodeOutputMaterial", (1200, 0))
    b = node(nt, "ShaderNodeBsdfPrincipled", (900, 0), Roughness=0.05)
    b.inputs["Coat Weight"].default_value = 1.0
    b.inputs["Coat Roughness"].default_value = 0.02
    L.new(b.outputs[0], out.inputs["Surface"])
    at = node(nt, "ShaderNodeAttribute", (-900, 0))
    at.attribute_name = "Rex_EyeUV"
    sp = node(nt, "ShaderNodeSeparateXYZ", (-700, 0))
    L.new(at.outputs["Vector"], sp.inputs[0])
    # radius from the forward axis
    xy = node(nt, "ShaderNodeCombineXYZ", (-500, 100))
    L.new(sp.outputs["X"], xy.inputs["X"])
    L.new(sp.outputs["Y"], xy.inputs["Y"])
    rad = node(nt, "ShaderNodeVectorMath", (-300, 100))
    rad.operation = "LENGTH"
    L.new(xy.outputs[0], rad.inputs[0])
    # slit pupil: |x| / sqrt(1 - y^2) < 0.13
    ax = node(nt, "ShaderNodeMath", (-500, -150))
    ax.operation = "ABSOLUTE"
    L.new(sp.outputs["X"], ax.inputs[0])
    slit = node(nt, "ShaderNodeMath", (-300, -150))
    slit.operation = "LESS_THAN"
    slit.inputs[1].default_value = 0.12
    L.new(ax.outputs[0], slit.inputs[0])
    # iris ramp by radius: pupil-side gold -> amber -> dark limbus -> black
    ramp = node(nt, "ShaderNodeValToRGB", (-100, 150))
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.0, (1.0, 0.75, 0.18, 1)
    cr.elements[1].position, cr.elements[1].color = 0.62, (0.85, 0.28, 0.02, 1)
    e = cr.elements.new(0.74)
    e.color = (0.12, 0.02, 0.0, 1)
    e = cr.elements.new(0.82)
    e.color = (0.0, 0.0, 0.0, 1)
    L.new(rad.outputs["Value"], ramp.inputs["Fac"])
    # streaks
    st = node(nt, "ShaderNodeTexNoise", (-300, 400), Scale=14.0, Detail=2.0)
    L.new(at.outputs["Vector"], st.inputs["Vector"])
    mul = node(nt, "ShaderNodeMix", (150, 250))
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    S(mul, "Factor").default_value = 0.6
    L.new(ramp.outputs["Color"], S(mul, "A"))
    L.new(st.outputs["Color"], S(mul, "B"))
    pup = node(nt, "ShaderNodeMix", (400, 150))
    pup.data_type = "RGBA"
    L.new(slit.outputs[0], S(pup, "Factor"))
    L.new(SO(mul), S(pup, "A"))
    S(pup, "B").default_value = (0.0, 0.0, 0.0, 1)
    # only the front hemisphere shows iris
    front = node(nt, "ShaderNodeMath", (-300, -350))
    front.operation = "GREATER_THAN"
    front.inputs[1].default_value = 0.0
    L.new(sp.outputs["Z"], front.inputs[0])
    fm = node(nt, "ShaderNodeMix", (650, 150))
    fm.data_type = "RGBA"
    L.new(front.outputs[0], S(fm, "Factor"))
    S(fm, "A").default_value = (0.0, 0.0, 0.0, 1)
    L.new(SO(pup), S(fm, "B"))
    L.new(SO(fm), b.inputs["Base Color"])
    L.new(SO(fm), b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = 3.5


def keratin_material():
    m = bpy.data.materials["Rex_Keratin"]
    nt = m.node_tree
    b = bsdf(m)
    L = nt.links
    rst = node(nt, "ShaderNodeAttribute", (-900, 0))
    rst.attribute_name = "rest"
    sp = node(nt, "ShaderNodeSeparateXYZ", (-700, 0))
    L.new(rst.outputs["Vector"], sp.inputs[0])
    # teeth live forward of rest y = -2.9 (the head), claws everywhere else
    is_tooth = node(nt, "ShaderNodeMath", (-500, 0))
    is_tooth.operation = "LESS_THAN"
    is_tooth.inputs[1].default_value = -2.9
    L.new(sp.outputs["Y"], is_tooth.inputs[0])
    dirt = node(nt, "ShaderNodeTexNoise", (-700, 300), Scale=60.0, Detail=3.0)
    L.new(rst.outputs["Vector"], dirt.inputs["Vector"])
    tooth = node(nt, "ShaderNodeMix", (-300, 300))
    tooth.data_type = "RGBA"
    L.new(dirt.outputs["Fac"], S(tooth, "Factor"))
    S(tooth, "A").default_value = (0.62, 0.55, 0.4, 1)
    S(tooth, "B").default_value = (0.4, 0.3, 0.18, 1)
    c = node(nt, "ShaderNodeMix", (0, 200))
    c.data_type = "RGBA"
    L.new(is_tooth.outputs[0], S(c, "Factor"))
    S(c, "A").default_value = (0.05, 0.04, 0.032, 1)
    L.new(SO(tooth), S(c, "B"))
    L.new(SO(c), b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.32
    b.inputs["Subsurface Weight"].default_value = 0.2
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.8, 0.5)
    b.inputs["Subsurface Scale"].default_value = 0.01


skin_material()
eye_material()
keratin_material()

# ---------------------------------------------------------------- forest floor
R = 70
gm = bpy.data.meshes.new("Ground")
n = 90 if a.preview else 160
xs = np.linspace(-R, R, n)
X, Yg = np.meshgrid(xs, xs)
Z = np.zeros_like(X)
from mathutils import noise  # noqa: E402
for i in range(n):
    for j in range(n):
        p = Vector((X[i, j], Yg[i, j], 0))
        d = math.hypot(X[i, j], Yg[i, j] + 2)
        Z[i, j] = noise.noise(p * 0.06) * 1.6 * min(1.0, max(0.0, (d - 9) / 18)) + noise.noise(p * 0.3) * 0.12
verts = np.stack([X, Yg, Z], -1).reshape(-1, 3)
faces = [(i * n + j, i * n + j + 1, (i + 1) * n + j + 1, (i + 1) * n + j) for i in range(n - 1) for j in range(n - 1)]
gm.from_pydata(verts.tolist(), [], faces)
for p in gm.polygons:
    p.use_smooth = True
ground = bpy.data.objects.new("Ground", gm)
scene.collection.objects.link(ground)
gmat = bpy.data.materials.new("M_Ground")
nt = gmat.node_tree
gb = bsdf(gmat)
tc = node(nt, "ShaderNodeTexCoord", (-1200, 0))
mp = node(nt, "ShaderNodeMapping", (-1000, 0))
mp.inputs["Scale"].default_value = (0.4, 0.4, 0.4)
nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])


def img(name, noncolor=False, loc=(-700, 0)):
    t = node(nt, "ShaderNodeTexImage", loc)
    t.image = bpy.data.images.load(os.path.join(TEX, name))
    if noncolor:
        t.image.colorspace_settings.name = "Non-Color"
    nt.links.new(mp.outputs[0], t.inputs["Vector"])
    return t


dif, nor, rou = img("ground_diff.jpg"), img("ground_nor.jpg", True, (-700, -300)), img("ground_rough.jpg", True, (-700, -600))
dark = node(nt, "ShaderNodeMix", (-300, 100))
dark.data_type = "RGBA"
dark.blend_type = "MULTIPLY"
S(dark, "Factor").default_value = 1.0
nt.links.new(dif.outputs["Color"], S(dark, "A"))
S(dark, "B").default_value = (0.3, 0.26, 0.2, 1)
nt.links.new(SO(dark), gb.inputs["Base Color"])
nt.links.new(rou.outputs["Color"], gb.inputs["Roughness"])
nm = node(nt, "ShaderNodeNormalMap", (-300, -300))
nt.links.new(nor.outputs["Color"], nm.inputs["Color"])
nt.links.new(nm.outputs[0], gb.inputs["Normal"])
assign(ground, gmat)

# ---------------------------------------------------------------- vegetation, rocks: instanced by hand, clear of the shot
bark = fl.mossy_material("M_Bark", base=(0.07, 0.06, 0.05), moss=(0.04, 0.08, 0.015), moss_from=0.45, scale=3)
leaf_big = fl.leaf_mesh("LeafBig", length=0.62, width=0.26, fold=0.3)
leaf_small = fl.leaf_mesh("LeafSmall", length=0.4, width=0.16, fold=0.2)
LPT = 24 if a.preview else 44
canopy = fl.leaf_material("M_Canopy", greens=((0.03, 0.09, 0.015), (0.07, 0.16, 0.02), (0.12, 0.2, 0.03)))
under = fl.leaf_material("M_Under", greens=((0.02, 0.07, 0.01), (0.05, 0.14, 0.02), (0.09, 0.18, 0.02)), translucency=0.45)
trees = [fl.broadleaf_tree(f"Tree{i}", seed=40 + i, height=rng.uniform(18, 28), bark=bark, leaf=canopy,
                          leaf_obj=(leaf_big, leaf_small)[i % 2], leaves_per_twig=LPT) for i in range(4)]
saplings = [fl.broadleaf_tree(f"Sapling{i}", seed=50 + i, height=rng.uniform(4, 7), bark=bark, leaf=under, leaf_obj=leaf_big,
                             leaves_per_twig=LPT, buttress=False, crown=0.8) for i in range(3)]
ferns = [fl.fern(f"Fern{i}", seed=60 + i, size=rng.uniform(0.9, 1.5), leaf=under) for i in range(3)]
rocks = [fl.rock(f"Rock{i}", seed=70 + i, size=rng.uniform(0.6, 1.3),
                 mat=fl.mossy_material(f"M_Rock{i}", base=(0.13, 0.13, 0.12), moss_from=0.55)) for i in range(3)]
CAM = {"hero": ((7.8, -12.6, 1.5), (0.4, -2.8, 3.1), 32),
       "head": ((3.6, -8.2, 3.9), (0.9, -4.6, 4.3), 55),
       "low": ((5.0, -9.5, 0.45), (0.4, -2.5, 3.2), 22)}[SHOT]
cam_xy = Vector(CAM[0][:2])


def ground_z(x, y):
    p = Vector((x, y, 0))
    d = math.hypot(x, y + 2)
    return noise.noise(p * 0.06) * 1.6 * min(1.0, max(0.0, (d - 9) / 18)) + noise.noise(p * 0.3) * 0.12


def in_view(x, y, margin=0.35):
    """Inside the camera's view wedge and nearer than the rex: keep it clear."""
    v = Vector((x, y)) - cam_xy
    t = Vector(CAM[1][:2]) - cam_xy
    ang = v.angle(t) if v.length > 1e-3 else 0
    return ang < margin and v.length < t.length + 3


def place(colls, n_, rmin, rmax, scale, seed, clear=True, sink=0.0):
    r = random.Random(seed)
    k = 0
    tries = 0
    while k < n_ and tries < n_ * 50:
        tries += 1
        ang = r.uniform(0, 2 * math.pi)
        d = r.uniform(rmin, rmax)
        x, y = d * math.cos(ang), -2 + d * math.sin(ang)
        if clear and in_view(x, y):
            continue
        if math.hypot(x, y + 2) < 5.5:
            continue
        o = bpy.data.objects.new(f"inst{seed}_{k}", None)
        o.instance_type = "COLLECTION"
        o.instance_collection = r.choice(colls)
        o.location = (x, y, ground_z(x, y) - sink)
        o.rotation_euler = (r.uniform(-0.05, 0.05), r.uniform(-0.05, 0.05), r.uniform(0, 6.28))
        s = r.uniform(*scale)
        o.scale = (s, s, s)
        scene.collection.objects.link(o)
        k += 1


place(trees, 26 if a.preview else 44, 12, 60, (0.8, 1.2), 1, sink=0.3)
place(saplings, 20 if a.preview else 36, 12, 40, (0.8, 1.3), 4, sink=0.1)
place(ferns, 60 if a.preview else 150, 5, 30, (0.8, 1.8), 2, clear=False)
place(rocks, 18, 6, 35, (0.6, 1.8), 3, clear=False, sink=0.25)
# foreground ferns framing the lower corners
for i, (x, y, s) in enumerate([(6.2, -12.8, 1.6), (3.9, -11.0, 1.2), (11.0, -11.5, 2.0), (-1.5, -9.5, 1.4)]):
    o = bpy.data.objects.new(f"fg_fern{i}", None)
    o.instance_type = "COLLECTION"
    o.instance_collection = ferns[i % 3]
    o.location = (x, y, ground_z(x, y))
    o.rotation_euler = (0, 0, i * 1.9)
    o.scale = (s, s, s)
    scene.collection.objects.link(o)

# ---------------------------------------------------------------- light: backlit misty morning
w = bpy.data.worlds.new("World")
scene.world = w
wn = w.node_tree
bg = next(n_ for n_ in wn.nodes if n_.type == "BACKGROUND")
env = node(wn, "ShaderNodeTexEnvironment", (-400, 0))
env.image = bpy.data.images.load(os.path.join(HDRI_DIR, "forest.exr"))
wmp = node(wn, "ShaderNodeMapping", (-600, 0))
wmp.inputs["Rotation"].default_value[2] = 1.2
wtc = node(wn, "ShaderNodeTexCoord", (-800, 0))
wn.links.new(wtc.outputs["Generated"], wmp.inputs["Vector"])
wn.links.new(wmp.outputs[0], env.inputs["Vector"])
tint = node(wn, "ShaderNodeMix", (-200, 0))
tint.data_type = "RGBA"
tint.blend_type = "MULTIPLY"
S(tint, "Factor").default_value = 1.0
S(tint, "B").default_value = (0.55, 0.68, 0.8, 1)
wn.links.new(env.outputs["Color"], S(tint, "A"))
wn.links.new(SO(tint), bg.inputs["Color"])
bg.inputs["Strength"].default_value = 0.35
# mist: a homogeneous world volume, thick enough for shafts through the canopy
vol = node(wn, "ShaderNodeVolumePrincipled", (0, -250))
vol.inputs["Density"].default_value = 0.0 if "--novol" in argv else 0.008
vol.inputs["Color"].default_value = (0.75, 0.82, 0.88, 1)
vol.inputs["Anisotropy"].default_value = 0.55
wout = next(n_ for n_ in wn.nodes if n_.type == "OUTPUT_WORLD")
wn.links.new(vol.outputs[0], wout.inputs["Volume"])

sun = light("SUN", (0, 0, 30), 3.2, color=(1.0, 0.82, 0.6), size=math.radians(2.0), name="Sun")
sun.rotation_euler = Euler((math.radians(62), 0, math.radians(200)))     # low, from behind the rex: rim + shafts
light("AREA", (12, -10, 7), 500, color=(0.72, 0.82, 1.0), size=9, target=(0.5, -3, 3.5), name="Fill")
light("AREA", (4.5, -9.5, 5.5), 420, color=(1.0, 0.86, 0.72), size=2.5, target=(0.8, -4.5, 4.2), name="FaceKey")
light("SPOT", (-10, 8, 16), 16000, color=(1.0, 0.72, 0.48), size=0.3, target=(0.5, -3, 3.4), name="Rim", spot_deg=16)
# the eyes cast a little glow of their own
for s in (1, -1):
    pl = light("POINT", (0, 0, 0), 6, color=(1.0, 0.45, 0.1), size=0.05, name=f"EyeGlow{s}")
    c = g["EYE_C"][0 if s == 1 else 1]
    wc = arm.matrix_world @ arm.pose.bones["Head"].matrix @ arm.pose.bones["Head"].bone.matrix_local.inverted() @ \
        (g["ROT"] @ c + Vector((0, -0.06, 0)))
    pl.location = wc

if SHOT == "head":                     # frame the posed head: in front of the snout, off to its left
    hb = arm.pose.bones["Head"]
    h0, h1 = arm.matrix_world @ hb.head, arm.matrix_world @ hb.tail
    fwd = (h1 - h0).normalized()
    fwd.z = 0
    fwd.normalize()
    right = fwd.cross(Vector((0, 0, 1)))
    tgt = h0.lerp(h1, 0.45) + Vector((0, 0, -0.25))
    CAM = (tuple(tgt + fwd * 3.6 - right * 2.4 + Vector((0, 0, -0.35))), tuple(tgt), 45)
cam = camera(CAM[0], CAM[1], lens=CAM[2], fstop=2.8 if SHOT == "head" else 5.6)
head_w = arm.matrix_world @ arm.pose.bones["Head"].tail
cam.data.dof.focus_distance = (Vector(CAM[0]) - head_w).length
scene.render.resolution_x, scene.render.resolution_y = a.res
scene.cycles.volume_step_rate = 4.0 if a.preview else 2.0
scene.cycles.volume_max_steps = 256
finish(a, samples=384, look="AgX - Medium High Contrast", exposure=-0.2, bounces=8)
