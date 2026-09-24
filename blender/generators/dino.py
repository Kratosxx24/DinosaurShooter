"""Rigged, animated theropod for the forest shooter: KIND = "raptor" (fast pack hunter, ~4.4 m long) or
"rex" (a 10 m brute). Budget: <= 6k tris each.

Body = dense metaball ellipsoid chains along anatomical polylines (muscle masses, a wedge skull, brow ridges,
bird feet), polygonised, decimated to BODY_TRIS and AO-baked; the knot tree K gives the bones and the game's
hitboxes. Capsule-distance skin weights (playbook: procedural-creature-rig-to-threejs) with a hard mouth-line
split between Head and Jaw; teeth, claws and eyes are found on the surface by ray casts and weighted 100% to
their bone. Countershaded + striped + AO vertex colours (COLOR_0), glowing eyes (what you see first in the fog).
Clips (FK, keyed per frame, in place): Idle, Run, Attack, Roar, Death. Armature custom props
`run_speed` (m/s at which Run's stride matches the ground) and `kind` reach Three.js as userData.

Build (from the repo root; writes assets/raptor_vN.glb and a contact sheet in screenshots/):
    python blender/build.py raptor        (or rex)
Close-up stills: blender -b --factory-startup --python blender/tools/model_views.py -- blender/generators/dino.py
    screenshots/raptor --set KIND=raptor [--color vertex]
"""
import bpy
import bmesh
import math
import random
from mathutils import Vector, Matrix, Euler
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

KIND = globals().get("KIND", "raptor")
COLLECTION = "Dino_" + KIND
PREFIX = KIND.capitalize() + "_"
SEED = 7 if KIND == "raptor" else 11
FPS = 24
SKIN_SHARP = 5.0
MB_RES = 0.02             # metaball tessellation (raptor metres; scales with S) before decimation
CHAIN = 0.75              # a dense metaball chain's surface radius ~= 0.75 x element radius
STEP = 0.35               # element spacing along a chain, as a fraction of the local radius
BODY_TRIS = 4400          # decimation target for the flesh; teeth/claws/eyes/feathers add ~1.3k
AO_RAYS = 24
DETAIL_FACTOR = 1.0       # decimation weight: the face and feet keep more of their triangles
MOUTH = (0.16, 0.035, 0.03)   # gums / mouth lining: the lip band that stretches open when the jaw drops
rng = random.Random(SEED)

# ---------------------------------------------------------------- proportions per kind
if KIND == "rex":
    S, HEAD, ARM, BULK, NECK, DEEP = 2.35, 1.75, 0.45, 1.3, 0.8, 1.35
    RUN_SPEED, RUN_PERIOD = 7.0, 0.9
    SKIN_TOP, SKIN_BELLY, STRIPE = (0.055, 0.045, 0.03), (0.3, 0.25, 0.18), (0.02, 0.018, 0.014)
    EYE = (1.0, 0.45, 0.08)
else:
    S, HEAD, ARM, BULK, NECK, DEEP = 1.0, 1.0, 1.0, 1.0, 1.0, 1.0
    RUN_SPEED, RUN_PERIOD = 9.0, 0.5
    SKIN_TOP, SKIN_BELLY, STRIPE = (0.07, 0.075, 0.05), (0.42, 0.38, 0.28), (0.012, 0.014, 0.012)
    EYE = (1.0, 0.8, 0.2)
EYE_STRENGTH = 12.0

# ---------------------------------------------------------------- knots: name -> (position, (width, height) radius)
# Authored facing +X, +Y = the animal's left, in raptor metres (x S). Knots are the joints: they become the
# bones and the game's hitbox capsules, and their radii are the flesh size there.
K = {}


def knot(name, x, y, z, rw, rh=None):
    K[name] = (Vector((x, y, z)) * S, (rw * S, (rh if rh is not None else rw) * S))


knot("tail5", -2.5, 0, 1.02, 0.02)
knot("tail4", -1.9, 0, 1.1, 0.055 * BULK, 0.065 * BULK)
knot("tail3", -1.3, 0, 1.15, 0.095 * BULK, 0.115 * BULK)
knot("tail2", -0.72, 0, 1.19, 0.15 * BULK, 0.18 * BULK)
knot("hip", 0, 0, 1.22, 0.2 * BULK, 0.24 * BULK)
knot("chest", 0.55, 0, 1.2 + 0.04 * (BULK - 1), 0.2 * BULK, 0.27 * BULK)
knot("neck0", 0.55 + 0.3 * NECK, 0, 1.36, 0.12 * BULK * max(1, HEAD * 0.75), 0.14 * BULK * max(1, HEAD * 0.75))
knot("neck1", 0.55 + 0.43 * NECK, 0, 1.36 + 0.2 * NECK, 0.075 * HEAD ** 0.8, 0.085 * HEAD ** 0.8 * DEEP)
knot("head0", 0.55 + 0.53 * NECK, 0, 1.36 + 0.36 * NECK, 0.09 * HEAD, 0.105 * HEAD * DEEP)
hx, _, hz = K["head0"][0] / S
H, D = HEAD, HEAD * DEEP                      # head length scale, head height scale
knot("snout", hx + 0.5 * H, 0, hz - 0.065 * D, 0.022 * H, 0.034 * D)
knot("jaw0", hx + 0.04 * H, 0, hz - 0.075 * D, 0.07 * H, 0.05 * D)     # the jaw hinge, low at the back of the skull
knot("jawtip", hx + 0.45 * H, 0, hz - 0.115 * D, 0.025 * H, 0.02 * D)
knot("skull", hx + 0.14 * H, 0, hz - 0.005 * D, 0.085 * H, 0.1 * D)
knot("muzzle", hx + 0.3 * H, 0, hz - 0.035 * D, 0.05 * H, 0.07 * D)
knot("jawmid", hx + 0.22 * H, 0, hz - 0.1 * D, 0.05 * H, 0.03 * D)
knot("belly", 0.28, 0, 1.17 + 0.02 * (BULK - 1), 0.22 * BULK, 0.29 * BULK)
for s, side in ((1, "L"), (-1, "R")):
    knot("hip" + side, 0.02, s * 0.17 * BULK, 1.14, 0.14 * BULK, 0.2 * BULK)
    knot("thigh" + side, 0.14, s * 0.22 * BULK, 0.94, 0.13 * BULK, 0.17 * BULK)
    knot("knee" + side, 0.28, s * 0.24 * BULK, 0.72, 0.075 * BULK, 0.085 * BULK)
    knot("calf" + side, 0.14, s * 0.235 * BULK, 0.54, 0.06 * BULK, 0.065 * BULK)
    knot("ankle" + side, -0.08, s * 0.23 * BULK, 0.32, 0.04 * BULK, 0.045 * BULK)
    knot("ball" + side, 0.12, s * 0.23 * BULK, 0.05, 0.04 * BULK, 0.03 * BULK)
    knot("toe" + side, 0.36, s * 0.23 * BULK, 0.025, 0.022 * BULK, 0.018 * BULK)
    knot("sh" + side, 0.6, s * 0.14 * BULK, 1.1, 0.055 * ARM, 0.07 * ARM)
    knot("elbow" + side, 0.56, s * (0.14 * BULK + 0.08 * ARM), 1.1 - 0.24 * ARM, 0.04 * ARM)
    knot("hand" + side, 0.56 + 0.24 * ARM, s * (0.14 * BULK + 0.07 * ARM), 1.1 - 0.31 * ARM, 0.028 * ARM, 0.02 * ARM)

# bones: (name, head knot, tail knot, parent)
BONES = [("Pelvis", "hip", "chest", None), ("Chest", "chest", "neck0", "Pelvis"),
         ("Neck1", "neck0", "neck1", "Chest"), ("Neck2", "neck1", "head0", "Neck1"),
         ("Head", "head0", "snout", "Neck2"), ("Jaw", "jaw0", "jawtip", "Neck2"),
         ("Tail1", "hip", "tail2", "Pelvis"), ("Tail2", "tail2", "tail3", "Tail1"),
         ("Tail3", "tail3", "tail4", "Tail2"), ("Tail4", "tail4", "tail5", "Tail3")]
for sd in "LR":
    BONES += [(f"Thigh.{sd}", "hip" + sd, "knee" + sd, "Pelvis"), (f"Shin.{sd}", "knee" + sd, "ankle" + sd, f"Thigh.{sd}"),
              (f"Meta.{sd}", "ankle" + sd, "ball" + sd, f"Shin.{sd}"), (f"Toe.{sd}", "ball" + sd, "toe" + sd, f"Meta.{sd}"),
              (f"Arm.{sd}", "sh" + sd, "elbow" + sd, "Chest"), (f"Fore.{sd}", "elbow" + sd, "hand" + sd, f"Arm.{sd}")]


def P(n):
    return K[n][0]


def R(n):
    return K[n][1]


def smooth(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- flesh: polylines of (point, (half width, half height))
# Knots by name, or free points f(x, y, z, w, h) in raptor metres for the masses that aren't joints.
def f(x, y, z, w, h=None):
    return (Vector((x, y, z)) * S, (w * S, (h if h is not None else w) * S))


def k(n, sw=1.0, sh=None):
    return (P(n), (R(n)[0] * sw, R(n)[1] * (sh if sh is not None else sw)))


def between(a, b, t, sw=1.0, sh=None):
    return (P(a).lerp(P(b), t), ((R(a)[0] + (R(b)[0] - R(a)[0]) * t) * sw,
                                 (R(a)[1] + (R(b)[1] - R(a)[1]) * t) * (sh if sh is not None else sw)))


B = BULK
CHAINS = [
    # tail tip -> hips -> ribcage -> shoulders -> neck -> back of the skull: one continuous back line
    [k("tail5"), k("tail4"), k("tail3"), k("tail2"), f(-0.36, 0, 1.21, 0.18 * B, 0.215 * B), k("hip"), k("belly"),
     k("chest"), f(0.72, 0, 1.25, 0.15 * B, 0.2 * B), k("neck0"), between("neck0", "neck1", 0.5), k("neck1"),
     k("head0")],
    # gut and ribcage underneath, so the belly hangs a little below the spine line
    [f(-0.05, 0, 1.1, 0.14 * B, 0.13 * B), f(0.28, 0, 1.02, 0.17 * B, 0.15 * B), f(0.56, 0, 1.06, 0.13 * B, 0.12 * B),
     f(0.72, 0, 1.18, 0.09 * B, 0.08 * B)],
    # skull: occiput -> cranium -> eyes -> muzzle -> snout, a low wedge
    [k("head0"), f(hx + 0.07 * H, 0, hz + 0.0 * D, 0.095 * H, 0.105 * D), k("skull"), k("muzzle"),
     f(hx + 0.41 * H, 0, hz - 0.05 * D, 0.036 * H, 0.054 * D), k("snout")],
    # lower jaw: hinge -> chin
    [k("jaw0"), k("jawmid"), k("jawtip")],
    # throat: fills the V between the jaw and the neck
    [f(hx - 0.02 * H, 0, hz - 0.1 * D, 0.06 * H, 0.05 * D), k("neck1", 0.9)],
]
for s, sd in ((1, "L"), (-1, "R")):
    y = lambda v: s * v
    CHAINS += [
        # brow ridge over the eye, and the jaw muscle bulging behind it
        [f(hx + 0.05 * H, y(0.055 * H), hz + 0.06 * D, 0.03 * H, 0.022 * D),
         f(hx + 0.17 * H, y(0.052 * H), hz + 0.05 * D, 0.028 * H, 0.02 * D),
         f(hx + 0.27 * H, y(0.035 * H), hz + 0.025 * D, 0.02 * H, 0.015 * D)],
        [f(hx + 0.02 * H, y(0.06 * H), hz - 0.03 * D, 0.05 * H, 0.06 * D),
         f(hx + 0.1 * H, y(0.05 * H), hz - 0.06 * D, 0.04 * H, 0.04 * D)],
        # thigh: a heavy drumstick into the hip, the knee forward
        [f(-0.12, y(0.14 * B), 1.2, 0.13 * B, 0.16 * B), k("hip" + sd), k("thigh" + sd),
         between("thigh" + sd, "knee" + sd, 0.5, 0.95), k("knee" + sd)],
        # the caudofemoralis: the tail muscle that pulls the thigh back
        [f(-0.5, y(0.07 * B), 1.18, 0.11 * B, 0.14 * B), f(-0.12, y(0.14 * B), 1.12, 0.12 * B, 0.15 * B),
         f(0.08, y(0.19 * B), 0.98, 0.1 * B, 0.12 * B)],
        # shin with its calf, then the slender bird-like metatarsus
        [k("knee" + sd), f(0.22, y(0.235 * B), 0.64, 0.07 * B, 0.08 * B), k("calf" + sd),
         between("calf" + sd, "ankle" + sd, 0.5), k("ankle" + sd)],
        [k("ankle" + sd), between("ankle" + sd, "ball" + sd, 0.5, 0.8), k("ball" + sd)],
        # digits III and IV on the ground; II (the sickle claw) carried up off it
        [k("ball" + sd, 0.85), f(0.24, y(0.24 * B), 0.035, 0.025 * B, 0.022 * B), k("toe" + sd)],
        [k("ball" + sd, 0.8), f(0.2, y(0.265 * B), 0.03, 0.022 * B, 0.02 * B),
         f(0.29, y(0.285 * B), 0.022, 0.017 * B, 0.015 * B)],
        [f(0.12, y(0.2 * B), 0.08, 0.025 * B, 0.022 * B), f(0.18, y(0.19 * B), 0.1, 0.02 * B, 0.018 * B)],
        # arm: folded like a wing, the hand turned in
        [f(0.62, y(0.1 * B), 1.14, 0.07 * ARM, 0.09 * ARM), k("sh" + sd), between("sh" + sd, "elbow" + sd, 0.5),
         k("elbow" + sd), between("elbow" + sd, "hand" + sd, 0.5), k("hand" + sd)],
    ]


def mouth_z(x):
    """Height of the mouth line (raptor metres) at x: the upper lip curves down a little toward the front."""
    t = min(1.0, max(0.0, (x / S - (hx + 0.04 * H)) / (0.46 * H)))
    return (hz - 0.075 * D + (-0.03 * D) * t) * S


# the lip line: negative elements just inside the skin carve a groove from the jaw corner to the chin
GROOVE = []
for s_ in (1, -1):
    for i in range(14):
        t = i / 13
        x = (hx + 0.06 * H + 0.4 * H * t) * S
        wid = (0.078 + (0.028 - 0.078) * t) * H * S
        GROOVE.append((Vector((x, s_ * wid, mouth_z(x))), (0.011 - 0.004 * t) * H * S))


# ---------------------------------------------------------------- collection
def purge(name):
    c = bpy.data.collections.get(name)
    if not c:
        return
    for o in list(c.all_objects):
        data = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if data is not None and data.users == 0:
            (bpy.data.meshes if isinstance(data, bpy.types.Mesh) else bpy.data.armatures).remove(data)
    for a in [a for a in bpy.data.actions if a.name.startswith(PREFIX)]:
        bpy.data.actions.remove(a)
    bpy.data.collections.remove(c)


purge(COLLECTION)
col = bpy.data.collections.new(COLLECTION)
bpy.context.scene.collection.children.link(col)
scene = bpy.context.scene
scene.render.fps = FPS

# ---------------------------------------------------------------- body: metaballs -> mesh -> decimate
mb = bpy.data.metaballs.new(PREFIX + "Meta")
mb.resolution = mb.render_resolution = MB_RES * S
mb.threshold = 0.6
for chain in CHAINS:
    for (pa, ra), (pb_, rb) in zip(chain, chain[1:]):
        r_min = min(min(ra), min(rb))
        n = max(1, math.ceil((pb_ - pa).length / (STEP * r_min)))
        for i in range(n + (1 if pb_ is chain[-1][0] else 0)):
            t = i / n
            p = pa.lerp(pb_, t)
            w, h = ra[0] + (rb[0] - ra[0]) * t, ra[1] + (rb[1] - ra[1]) * t
            r = max(w, h)
            e = mb.elements.new()
            e.type = "ELLIPSOID"
            e.co = p
            d = (pb_ - pa).normalized()           # stretch along the chain a little so it reads as one limb
            e.radius = r / CHAIN
            e.size_x, e.size_y, e.size_z = 1.0, w / r, h / r
            e.rotation = Vector((1, 0, 0)).rotation_difference(Vector((d.x, d.y, 0)) if abs(d.z) < 0.999 else Vector((1, 0, 0)))
for p, r in GROOVE:
    e = mb.elements.new()
    e.type, e.co, e.radius, e.use_negative = "BALL", p, r / CHAIN, True
    e.stiffness = 2.0
meta = bpy.data.objects.new(PREFIX + "Meta", mb)
col.objects.link(meta)
bpy.context.view_layer.update()
raw = bpy.data.meshes.new_from_object(meta.evaluated_get(bpy.context.evaluated_depsgraph_get()))
bpy.data.objects.remove(meta, do_unlink=True)
bpy.data.metaballs.remove(mb)
tmp = bpy.data.objects.new(PREFIX + "Tmp", raw)
col.objects.link(tmp)
raw_tris = sum(len(p.vertices) - 2 for p in raw.polygons)
# the face and feet are what the player sees up close: weight them so the collapse spends its budget elsewhere
detail = tmp.vertex_groups.new(name="Detail")
for v in raw.vertices:
    p = v.co / S
    face = smooth(hx - 0.05 * H, hx + 0.05 * H, p.x) * smooth(hz - 0.3 * D, hz - 0.2 * D, p.z)
    detail.add([v.index], 0.6 * max(face, 0.6 * (1 - smooth(0.12, 0.2, p.z))), "REPLACE")
dec = tmp.modifiers.new("Decimate", "DECIMATE")
dec.vertex_group, dec.vertex_group_factor, dec.invert_vertex_group = "Detail", DETAIL_FACTOR, True   # inverted: weight 1 = keep
dec.ratio = min(1.0, BODY_TRIS / max(1, raw_tris))
dec.use_symmetry, dec.symmetry_axis = False, "Y"
bpy.context.view_layer.update()
body_me = bpy.data.meshes.new_from_object(tmp.evaluated_get(bpy.context.evaluated_depsgraph_get()))
body_me.name = PREFIX + "Body"
bpy.data.objects.remove(tmp, do_unlink=True)
bpy.data.meshes.remove(raw)
for p in body_me.polygons:
    p.use_smooth = True
flesh_tree = BVHTree.FromPolygons([v.co.copy() for v in body_me.vertices], [tuple(p.vertices) for p in body_me.polygons])


def surface(origin, direction, dist=2.0):
    """First hit on the flesh from origin along direction (world, pre-rotation)."""
    loc, nrm, _, _ = flesh_tree.ray_cast(origin, direction.normalized(), dist * S)
    return loc, nrm


# ---------------------------------------------------------------- rigid extras (teeth, claws, eyes) appended by bmesh
bm = bmesh.new()
bm.from_mesh(body_me)
for fc in bm.faces:
    fc.material_index = 0
bm.verts.ensure_lookup_table()
n_body = len(bm.verts)
extra_bone = {}          # BMVert -> bone name (weight 1)


def cone(base, direction, length, radius, bone, mat=2, segs=5, curl=0.0, curl_axis=None):
    """A tapered horn from base along direction; curl bends the tip toward curl_axis (claws hook down)."""
    d = direction.normalized()
    side = d.orthogonal().normalized()
    up = d.cross(side)
    ring = [bm.verts.new(base + (side * math.cos(a) + up * math.sin(a)) * radius)
            for a in (2 * math.pi * i / segs for i in range(segs))]
    bend = (curl_axis or Vector((0, 0, -1))) * length * curl
    mid = [bm.verts.new(v.co + d * length * 0.5 + bend * 0.3 - (v.co - base) * 0.45) for v in ring]
    tip = bm.verts.new(base + d * length + bend)
    for i in range(segs):
        j = (i + 1) % segs
        bm.faces.new((ring[i], ring[j], mid[j], mid[i])).material_index = mat
        bm.faces.new((mid[i], mid[j], tip)).material_index = mat
    bm.faces.new(list(reversed(ring))).material_index = mat
    for v in ring + mid + [tip]:
        extra_bone[v] = bone


def sphere(center, r, bone, mat, squash=(1, 1, 1)):
    res = bmesh.ops.create_uvsphere(bm, u_segments=10, v_segments=7, radius=r)
    for v in res["verts"]:
        v.co = center + Vector((v.co.x * squash[0], v.co.y * squash[1], v.co.z * squash[2]))
        extra_bone[v] = bone
    for fc in {fc for v in res["verts"] for fc in v.link_faces}:
        fc.material_index = mat


# teeth: rooted just inside the lips, found by casting at the flesh from the side along the mouth line
N_TEETH = 11
for i in range(N_TEETH):
    t = i / (N_TEETH - 1)
    x = (hx + 0.1 * H + 0.36 * H * t) * S
    for s in (1, -1):
        for upper in (True, False):
            if not upper and i % 2:
                continue
            z = mouth_z(x) + (0.006 if upper else -0.006) * S * D
            loc, nrm = surface(Vector((x, 0, z)), Vector((0, s, 0)))
            if loc is None:
                continue
            size = (1.0 - 0.35 * t) * (1.25 if i in (1, 2) else 1.0) * H ** 0.5 * S
            base = loc - nrm * 0.003 * S * H if upper else loc - Vector((0, s * 0.006, 0)) * S * H
            if upper:
                cone(base, Vector((0.12, s * 0.22, -1)), 0.034 * size, 0.008 * size, "Head", curl=0.15,
                     curl_axis=Vector((-1, 0, 0)))
            else:
                cone(base, Vector((0.1, s * 0.1, 1)), 0.026 * size, 0.007 * size, "Jaw", curl=0.15,
                     curl_axis=Vector((-1, 0, 0)))
# eyes: set into the side of the skull under the brow, looking forward-out
EYE_R = 0.027 * H ** 0.6 * S
EYE_X, EYE_Z = (hx + 0.15 * H) * S, (hz + 0.022 * D) * S
for s in (1, -1):
    loc, nrm = surface(Vector((EYE_X, 0, EYE_Z)), Vector((0, s, 0)))
    c = loc - nrm * EYE_R * 0.45
    sphere(c, EYE_R, "Head", 1, squash=(1.0, 0.75, 0.85))
# claws: a hooked claw on each ground toe, the raised sickle on digit II, three on each hand
for sd, s in (("L", 1), ("R", -1)):
    tips = [(P("toe" + sd), Vector((1, 0, -0.35))), (Vector((0.29, s * 0.285 * B, 0.022)) * S, Vector((1, s * 0.25, -0.4)))]
    for p, d in tips:
        cone(p - d.normalized() * 0.012 * S * B, d, 0.06 * S * B, 0.013 * S * B, "Toe." + sd, curl=0.25)
    if KIND == "raptor":
        cone(Vector((0.17, s * 0.19, 0.1)) * S, Vector((0.55, 0, 1.0)), 0.13 * S, 0.02 * S, "Toe." + sd, segs=6,
             curl=0.55, curl_axis=Vector((1, 0, -0.3)).normalized())
    else:
        cone(Vector((0.17, s * 0.19 * B, 0.1)) * S, Vector((1, 0, -0.2)), 0.05 * S, 0.014 * S, "Toe." + sd, curl=0.25)
    hand = P("hand" + sd)
    for dy in (-0.018, 0.0, 0.018):
        cone(hand + Vector((0.0, dy * S * ARM, 0)), Vector((0.55, dy * 12, -1)), 0.065 * S * ARM, 0.009 * S * ARM,
             "Fore." + sd, curl=0.4, curl_axis=Vector((-1, 0, 0)))

# feathers: a crest of dark quills down the neck and back, a fan on each forearm, a tuft at the tail tip.
# Each quill copies the skin weights of the flesh vertex nearest its root, so it rides the surface as it bends.
QUILL = tuple(c * 0.55 for c in STRIPE[:3]) if KIND == "raptor" else None
extra_col = {}
body_kd = KDTree(n_body)
for v in bm.verts[:n_body]:
    body_kd.insert(v.co, v.index)
body_kd.balance()


def quill(root, direction, length, width, colour, bone=None):
    """A flat blade: a diamond base (wide along the feather, thin across it) and a tip."""
    d = direction.normalized()
    across = d.cross(Vector((0, 0, 1))) if abs(d.z) < 0.95 else Vector((0, 1, 0))
    across.normalize()
    along = across.cross(d).normalized()
    ring = [bm.verts.new(root + along * width), bm.verts.new(root + across * width * 0.25),
            bm.verts.new(root - along * width), bm.verts.new(root - across * width * 0.25)]
    tip = bm.verts.new(root + d * length)
    for i in range(4):
        bm.faces.new((ring[i], ring[(i + 1) % 4], tip)).material_index = 0
    bm.faces.new(list(reversed(ring))).material_index = 0
    anchor = bone or body_kd.find(root)[1]
    for v in ring + [tip]:
        extra_bone[v] = anchor
        extra_col[v] = colour


if QUILL:
    back = Vector((-1, 0, 0))
    for i in range(34):                  # neck crest -> back -> tail: longest over the shoulders
        t = i / 33
        x = (hx - 0.02 - (hx + 1.3) * t) * S
        loc, nrm = surface(Vector((x, 0, 3.0 * S)), Vector((0, 0, -1)), 4.0)
        if loc is None:
            continue
        size = math.sin(math.pi * min(1.0, 0.15 + t * 1.1)) ** 0.7 * (1.0 if t < 0.55 else 1.0 - (t - 0.55) * 1.4)
        for s_ in (1, -1):               # a pair either side of the midline so it reads as a ruff, not a fin
            root = loc + Vector((0, s_ * 0.012 * S, -0.012 * S))
            quill(root, nrm * 0.4 + back * 1.0 + Vector((0, s_ * 0.3, 0)), (0.05 + 0.1 * size) * S, 0.012 * S, QUILL)
    for sd, s_ in (("L", 1), ("R", -1)):
        for j in range(6):              # forearm fan: trailing back and down off the ulna
            t = j / 5
            root = P("elbow" + sd).lerp(P("hand" + sd), 0.1 + 0.85 * t) + Vector((0, s_ * 0.01, 0)) * S
            quill(root, Vector((-0.8 + 0.5 * t, s_ * 0.15, -0.6)), (0.1 + 0.05 * t) * S, 0.014 * S, QUILL, "Fore." + sd)
    for j in range(7):                  # tail-tip tuft
        a = (j / 6 - 0.5) * 1.6
        root = P("tail5").lerp(P("tail4"), 0.35 + 0.1 * abs(a))
        quill(root, Vector((-1, math.sin(a) * 0.6, 0.2 + math.cos(a) * 0.15)), 0.16 * S, 0.014 * S, QUILL, "Tail4")

bm.verts.index_update()
extra = {v.index: bone for v, bone in extra_bone.items()}     # read indices while the BMVerts are alive
extra_rgb = {v.index: c for v, c in extra_col.items()}
bm.to_mesh(body_me)
bm.free()


# ---------------------------------------------------------------- vertex colours: countershading + stripes, x baked AO
def bake_ao(me, n_verts):
    """Fibonacci cosine rays from each flesh vertex against the flesh and the ground: the escaping fraction."""
    tree = BVHTree.FromPolygons([v.co for v in me.vertices], [tuple(p.vertices) for p in me.polygons])
    dirs = []
    for i in range(AO_RAYS):
        u = (i + 0.5) / AO_RAYS
        r, phi = math.sqrt(u), i * 2.399963
        dirs.append(Vector((r * math.cos(phi), r * math.sin(phi), math.sqrt(1 - u))))
    zup = Vector((0, 0, 1))
    out = []
    for v in me.vertices[:n_verts]:
        q = zup.rotation_difference(v.normal)
        o = v.co + v.normal * 0.01 * S
        hit = 0
        for dd in dirs:
            dd = q @ dd
            if tree.ray_cast(o, dd, 0.6 * S)[0] is not None or (dd.z < -1e-4 and -o.z / dd.z < 0.6 * S):
                hit += 1
        out.append(1.0 - hit / AO_RAYS)
    return out


ao = bake_ao(body_me, n_body)
ca = body_me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
for v in body_me.vertices:
    p = v.co / S
    if v.index >= n_body:
        ca.data[v.index].color = (*extra_rgb.get(v.index, (0.55, 0.5, 0.4)), 1.0)
        continue
    n = v.normal
    # pale where the surface faces down (belly, throat, under the tail and jaw), dark on the back
    belly = smooth(0.25, -0.6, n.z) * (0.35 + 0.65 * smooth(0.6, 1.1, p.z))
    stripe = 0.5 + 0.5 * math.sin(p.x * (11 if KIND == "raptor" else 6) + 1.7 * math.sin(p.y * 9) + 0.9 * math.sin(p.z * 7))
    stripe = smooth(0.55, 0.85, stripe) * (1 - belly) * smooth(-2.6, -2.0, p.x) * (1 - smooth(hx + 0.05, hx + 0.2, p.x))
    c = [SKIN_TOP[i] + (SKIN_BELLY[i] - SKIN_TOP[i]) * belly for i in range(3)]
    c = [c[i] + (STRIPE[i] - c[i]) * stripe * 0.85 for i in range(3)]
    feet = 1 - smooth(0.25, 0.45, p.z)                        # scaly shins and feet go darker and greyer
    c = [c[i] * (1 - 0.35 * feet) + 0.02 * feet for i in range(3)]
    lip = (1 - smooth(0.006 * D, 0.014 * D, abs(p.z - mouth_z(v.co.x) / S))) * smooth(hx + 0.02 * H, hx + 0.07 * H, p.x)
    c = [c[i] + (MOUTH[i] - c[i]) * lip for i in range(3)]
    shade = rng.uniform(0.93, 1.07) * (0.35 + 0.65 * ao[v.index] ** 1.3)
    ca.data[v.index].color = (*(x * shade for x in c), 1.0)
body_me.color_attributes.active_color = ca
body_me.color_attributes.render_color_index = body_me.color_attributes.find("Col")

# ---------------------------------------------------------------- face -Y (the repo's forward: Three.js +Z)
# everything above is authored facing +X with +Y to the left; one rotation puts it in the export frame
ROT = Matrix.Rotation(-math.pi / 2, 4, "Z")
body_me.transform(ROT)
K = {n: (ROT @ p, r) for n, (p, r) in K.items()}
LATERAL = ROT @ Vector((0, 1, 0))

# ---------------------------------------------------------------- materials (Principled only; the game remaps by name)
def material(name, color, rough, emit=None, strength=0.0, vcol=False):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    if vcol:
        a = m.node_tree.nodes.new("ShaderNodeVertexColor")
        a.layer_name = "Col"
        m.node_tree.links.new(a.outputs["Color"], b.inputs["Base Color"])
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = strength
    return m


body_me.materials.append(material(PREFIX + "Skin", (1, 1, 1), 0.62, vcol=True))
body_me.materials.append(material(PREFIX + "Eye", (0.02, 0.02, 0.02), 0.1, emit=EYE, strength=EYE_STRENGTH))
body_me.materials.append(material(PREFIX + "Keratin", (0.55, 0.5, 0.4), 0.4))
body = bpy.data.objects.new(PREFIX + "Body", body_me)
col.objects.link(body)

# ---------------------------------------------------------------- armature
arm_data = bpy.data.armatures.new(PREFIX + "Rig")
arm = bpy.data.objects.new(PREFIX + "Rig", arm_data)
col.objects.link(arm)
bpy.context.view_layer.objects.active = arm
arm.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
eb = {}
for name, h, t, parent in BONES:
    b = arm_data.edit_bones.new(name)
    b.head, b.tail = P(h), P(t)
    b.align_roll(LATERAL)                # local Z = the lateral axis: rotation about Z is pitch for every bone
    if parent:
        b.parent = eb[parent]
        b.use_connect = (eb[parent].tail - b.head).length < 1e-4
    eb[name] = b
bpy.ops.object.mode_set(mode="OBJECT")
arm["run_speed"] = RUN_SPEED
arm["run_period"] = RUN_PERIOD
arm["kind"] = KIND
arm["scale"] = S
# knot positions for the game's hitboxes, in glTF space (x, z, -y) with the bone that carries each one
import json
arm["knots"] = json.dumps({n: [round(p.x, 4), round(p.z, 4), round(-p.y, 4), round(max(r), 4)] for n, (p, r) in K.items()})

# ---------------------------------------------------------------- skin weights: capsule distance (body) / rigid (extras)
seg = {name: (P(h), P(t), 0.5 * (max(R(h)) + max(R(t)))) for name, h, t, _ in BONES}
for name in seg:
    body.vertex_groups.new(name=name)


def seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length


vg = {g.name: g for g in body.vertex_groups}
for v in body_me.vertices:
    if v.index >= n_body:
        continue
    scores = []
    for name, (a, b, r) in seg.items():
        s = max(seg_dist(v.co, a, b) / r, 1e-3)
        scores.append((s ** -SKIN_SHARP, name))
    scores.sort(reverse=True)
    top = scores[:4]
    tot = sum(w for w, _ in top)
    top = [(w / tot, n) for w, n in top if w / tot > 0.02]
    # in the face, Head vs Jaw is decided by the mouth line, not by distance, so the jaw opens along the lips
    x_pre = -v.co.y                                        # undo ROT: authoring x
    hj = sum(w for w, n in top if n in ("Head", "Jaw"))
    if hj > 0.4 and x_pre > (hx + 0.03 * H) * S:
        up = smooth(-0.01 * S * D, 0.01 * S * D, v.co.z - mouth_z(x_pre))
        top = [(w, n) for w, n in top if n not in ("Head", "Jaw")] + [(hj * up, "Head"), (hj * (1 - up), "Jaw")]
        top = [(w, n) for w, n in top if w > 0.02]
    tot = sum(w for w, _ in top)
    for w, n in top:
        vg[n].add([v.index], w / tot, "REPLACE")
for i, bone in extra.items():
    if isinstance(bone, int):            # a quill: copy the weights of its anchor flesh vertex
        for ge in body_me.vertices[bone].groups:
            body.vertex_groups[ge.group].add([i], ge.weight, "REPLACE")
    else:
        vg[bone].add([i], 1.0, "REPLACE")
mod = body.modifiers.new("Armature", "ARMATURE")
mod.object = arm
body.parent = arm

# ---------------------------------------------------------------- clips (FK, in place)
pb = arm.pose.bones
for b in pb:
    b.rotation_mode = "XYZ"
arm.animation_data_create()


def keyclip(name, frames, fn):
    """fn(t in 0..1) -> {bone: (pitch, yaw, roll)} plus optional 'up' (pelvis rise, m)."""
    act = bpy.data.actions.new(PREFIX + name)
    act.use_fake_user = True
    arm.animation_data.action = act
    for i in range(frames + 1):
        pose = fn(i / frames)
        for b in pb:
            p, y, r = pose.get(b.name, (0, 0, 0))
            b.rotation_euler = Euler((y, r, p), "XYZ")
            b.keyframe_insert("rotation_euler", frame=i, group=b.name)
        up = pose.get("up", 0.0)
        side = pose.get("side", 0.0)
        pb["Pelvis"].location = Vector((up, 0, side))      # pelvis local X = world up, Z = world lateral
        pb["Pelvis"].keyframe_insert("location", frame=i, group="Pelvis")
    return act


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def env(t, keys):
    """Piecewise eased curve through (t, value) keys."""
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * ease((t - t0) / max(t1 - t0, 1e-6))
    return keys[-1][1]


TAU = 2 * math.pi


def run(t):
    ph = TAU * t
    o = {"up": 0.045 * S * math.cos(2 * ph), "Chest": (0.12, 0, 0), "Neck1": (-0.08, 0, 0), "Neck2": (-0.06 + 0.04 * math.sin(2 * ph), 0, 0),
         "Head": (0.05, 0, 0), "Jaw": (0.18, 0, 0)}
    for sd, off in (("L", 0.0), ("R", math.pi)):
        a = ph + off
        swing = max(0.0, math.cos(a))
        o["Thigh." + sd] = (-0.7 * math.sin(a) - 0.05, 0, 0)
        o["Shin." + sd] = (0.95 * swing ** 1.3 + 0.1, 0, 0)
        o["Meta." + sd] = (-0.7 * swing - 0.15 * math.sin(a), 0, 0)
        o["Toe." + sd] = (0.5 * swing + 0.25 * max(0, -math.sin(a)), 0, 0)
        o["Arm." + sd] = (-0.5, 0, 0)
        o["Fore." + sd] = (0.4, 0, 0)
    for k, tb in enumerate(("Tail1", "Tail2", "Tail3", "Tail4")):
        o[tb] = (0.04 * math.sin(2 * ph - k), 0.07 * (k + 1) * math.sin(ph - k * 0.6), 0)
    return o


def idle(t):
    ph = TAU * t
    look = 0.35 * math.sin(ph) * ease(abs(math.sin(ph)) * 1.4)
    o = {"up": 0.012 * S * math.sin(2 * ph), "Chest": (0.03 * math.sin(2 * ph), 0, 0),
         "Neck1": (-0.05, look * 0.4, 0), "Neck2": (0.05 * math.sin(2 * ph + 1), look * 0.6, 0), "Head": (0, look * 0.3, 0),
         "Jaw": (0.06 + 0.06 * max(0, math.sin(3 * ph)), 0, 0)}
    for sd in "LR":
        o["Arm." + sd] = (-0.3 + 0.04 * math.sin(ph), 0, 0)
        o["Fore." + sd] = (0.35, 0, 0)
    for k, tb in enumerate(("Tail1", "Tail2", "Tail3", "Tail4")):
        o[tb] = (0.02 * math.sin(ph - k), 0.08 * (k + 1) * math.sin(ph - k * 0.8), 0)
    return o


def attack(t):
    lunge = env(t, [(0, 0), (0.3, -0.25), (0.5, 1.0), (0.7, 0.8), (1, 0)])
    jaw = env(t, [(0, 0.05), (0.3, 0.3), (0.45, 1.0), (0.58, 0.0), (0.75, 0.1), (1, 0.05)])
    o = {"up": -0.08 * S * max(0, lunge), "Chest": (0.35 * lunge, 0, 0), "Neck1": (0.25 * lunge, 0, 0), "Neck2": (0.15 * lunge, 0, 0),
         "Head": (-0.1 * lunge - 0.25 * jaw, 0, 0), "Jaw": (0.15 + 0.6 * jaw, 0, 0)}
    for sd in "LR":
        o["Arm." + sd] = (-0.8 * max(0, lunge), 0, 0)
        o["Fore." + sd] = (0.2, 0, 0)
        o["Thigh." + sd] = (-0.15 * lunge * (1 if sd == "L" else 0.4), 0, 0)
        o["Shin." + sd] = (0.25 * max(0, lunge), 0, 0)
    for k, tb in enumerate(("Tail1", "Tail2", "Tail3", "Tail4")):
        o[tb] = (-0.12 * lunge, 0, 0)
    return o


def roar(t):
    rise = env(t, [(0, 0), (0.25, 1), (0.8, 1), (1, 0)])
    jaw = env(t, [(0, 0), (0.25, 1.1), (0.8, 1.0), (1, 0)])
    shake = 0.05 * math.sin(t * 60) * rise
    o = {"up": 0.03 * S * rise, "Chest": (-0.2 * rise, 0, 0), "Neck1": (-0.45 * rise, shake, 0), "Neck2": (-0.25 * rise, shake, 0),
         "Head": (-0.2 * rise, 0, shake), "Jaw": (0.1 + 0.62 * jaw, 0, 0)}
    for sd, s in (("L", 1), ("R", -1)):
        o["Arm." + sd] = (-0.9 * rise, s * 0.3 * rise, 0)
        o["Fore." + sd] = (0.2, 0, 0)
    for k, tb in enumerate(("Tail1", "Tail2", "Tail3", "Tail4")):
        o[tb] = (0.12 * rise, 0.06 * math.sin(t * 20 + k) * rise, 0)
    return o


def death(t):
    fall = env(t, [(0, 0), (0.15, -0.1), (0.7, 1.0), (0.8, 0.96), (1, 1.0)])
    limp = env(t, [(0, 0), (0.5, 0.3), (1, 1)])
    hip_h, half = K["hip"][0].z, K["hip"][1][0]
    o = {"up": -(hip_h - half * 1.1) * fall, "Pelvis": (0, 0, 1.45 * fall), "Chest": (0.1 * fall, 0, 0),
         "Neck1": (0.3 * limp, 0.2 * limp, 0), "Neck2": (0.4 * limp, 0.3 * limp, 0), "Head": (0.2 * limp, 0, 0),
         "Jaw": (0.2 + 0.4 * limp, 0, 0)}
    for sd, s in (("L", 1), ("R", -1)):
        o["Thigh." + sd] = (-0.5 * fall * (1.2 if sd == "L" else 0.6), 0, 0)
        o["Shin." + sd] = (0.6 * limp, 0, 0)
        o["Meta." + sd] = (-0.4 * limp, 0, 0)
        o["Arm." + sd] = (-0.6 * limp, 0, 0)
    for k, tb in enumerate(("Tail1", "Tail2", "Tail3", "Tail4")):
        o[tb] = (-0.1 * limp, 0.12 * limp * (k + 1) * 0.5, 0)
    return o


keyclip("Idle", round(2.4 * FPS), idle)
keyclip("Run", round(RUN_PERIOD * FPS), run)
keyclip("Attack", round(0.7 * FPS), attack)
keyclip("Roar", round(1.4 * FPS), roar)
keyclip("Death", round(1.1 * FPS), death)
arm.animation_data.action = bpy.data.actions[PREFIX + "Run"]
for b in pb:
    b.rotation_euler = Euler((0, 0, 0))
    b.location = Vector()
print("DINO", KIND, "verts", len(body_me.vertices), "tris", sum(len(p.vertices) - 2 for p in body_me.polygons),
      "bones", len(BONES))
