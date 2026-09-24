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

KIND = globals().get("KIND", "raptor")
COLLECTION = "Dino_" + KIND
PREFIX = KIND.capitalize() + "_"
SEED = 7 if KIND == "raptor" else 11
FPS = 24
SKIN_SHARP = 5.0
MB_RES = 0.02             # metaball tessellation (raptor metres; scales with S) before decimation
CHAIN = 0.75              # a dense metaball chain's surface radius ~= 0.75 x element radius
STEP = 0.35               # element spacing along a chain, as a fraction of the local radius
BODY_TRIS = 9000          # decimation target for the flesh (the normal map carries the fine detail)
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
    SKIN_TOP, SKIN_BELLY, STRIPE = (0.014, 0.015, 0.019), (0.07, 0.07, 0.07), (0.01, 0.011, 0.014)
    EYE = (1.0, 0.8, 0.2)
FEATHERS = KIND == "raptor"      # blue-black plumage over the flesh; legs, feet and snout stay bare and scaly
FACE = (0.3, 0.3, 0.28)          # pale scaly face under the dark eye band
CLAW = (0.025, 0.024, 0.024) if FEATHERS else (0.55, 0.5, 0.4)
EYE_GLOW = 1.5          # emission on the iris texture: eyeshine in the fog without looking like a lamp

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
dl = bm.verts.layers.deform.active       # drop the decimation's Detail weights: skinning starts from nothing
if dl is not None:
    bm.verts.layers.deform.remove(dl)
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
        for q in ((ring[i], ring[j], mid[j], mid[i]), (mid[i], mid[j], tip)):
            fq = bm.faces.new(q)
            fq.material_index, fq.smooth = mat, True
    bm.faces.new(list(reversed(ring))).material_index = mat
    for v in ring + mid + [tip]:
        extra_bone[v] = bone


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
# eyes: a glossy eyeball set into a socket under the brow, ringed by lids; the iris is painted on in the UV pass
EYE_R = 0.027 * H ** 0.6 * S
EYE_X, EYE_Z = (hx + 0.15 * H) * S, (hz + 0.022 * D) * S
EYES = []                # (centre, look axis, side axis, up axis, radius) for the iris projection
extra_col = {}           # BMVert -> vertex colour for skin-material extras (the lids)
LID = tuple(c * 0.12 for c in FACE) if FEATHERS else tuple(c * 1.3 for c in SKIN_TOP)


def eye(center, axis, r):
    a = axis.normalized()
    side = a.cross(Vector((0, 0, 1))).normalized()
    up = side.cross(a).normalized()
    res = bmesh.ops.create_uvsphere(bm, u_segments=18, v_segments=12, radius=r)
    for v in res["verts"]:
        x, y, z = v.co
        v.co = center + side * x + up * y + a * z * 0.85
        extra_bone[v] = "Head"
    for fc in {fc for v in res["verts"] for fc in v.link_faces}:
        fc.material_index = 1
    EYES.append((center, a, side, up, r))
    # lids: a torus around the front of the eyeball, the upper lid heavier, hooding the eye from above
    ring, n_a, n_t = [], 20, 6
    for i in range(n_a):
        th = 2 * math.pi * i / n_a
        radial = side * math.cos(th) + up * math.sin(th)
        hood = max(0.0, math.sin(th))
        c = center + a * r * (0.3 + 0.1 * hood) + radial * r * (0.98 - 0.1 * hood)
        t = r * (0.17 + 0.17 * hood)
        ring.append([bm.verts.new(c + (radial * math.cos(2 * math.pi * j / n_t) + a * math.sin(2 * math.pi * j / n_t)) * t)
                     for j in range(n_t)])
    for i in range(n_a):
        for j in range(n_t):
            q = (ring[i][j], ring[(i + 1) % n_a][j], ring[(i + 1) % n_a][(j + 1) % n_t], ring[i][(j + 1) % n_t])
            fq = bm.faces.new(q)
            fq.material_index, fq.smooth = 0, True
    for v in (v for rv in ring for v in rv):
        extra_bone[v] = "Head"
        extra_col[v] = LID


for s in (1, -1):
    loc, nrm = surface(Vector((EYE_X, 0, EYE_Z)), Vector((0, s, 0)))
    look = nrm * 0.78 + Vector((0.3, 0, 0.04))
    eye(loc - nrm * EYE_R * 0.5, look, EYE_R)
# claws: a hooked claw on each ground toe, the raised sickle on digit II, three on each hand
for sd, s in (("L", 1), ("R", -1)):
    tips = [(P("toe" + sd), Vector((1, 0, -0.35))), (Vector((0.29, s * 0.285 * B, 0.022)) * S, Vector((1, s * 0.25, -0.4)))]
    for p, d in tips:
        cone(p - d.normalized() * 0.012 * S * B, d, 0.07 * S * B, 0.014 * S * B, "Toe." + sd, mat=3, segs=8, curl=0.35)
    if KIND == "raptor":
        cone(Vector((0.17, s * 0.19, 0.1)) * S, Vector((0.55, 0, 1.0)), 0.17 * S, 0.024 * S, "Toe." + sd, mat=3, segs=10,
             curl=0.7, curl_axis=Vector((1, 0, -0.3)).normalized())
    else:
        cone(Vector((0.17, s * 0.19 * B, 0.1)) * S, Vector((1, 0, -0.2)), 0.05 * S, 0.014 * S, "Toe." + sd, mat=3, curl=0.25)
    hand = P("hand" + sd)
    for dy in (-0.018, 0.0, 0.018):
        cone(hand + Vector((0.0, dy * S * ARM, 0)), Vector((0.55, dy * 12, -1)), 0.09 * S * ARM, 0.012 * S * ARM,
             "Fore." + sd, mat=3, segs=8, curl=0.6, curl_axis=Vector((-1, 0, 0)))

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
    if FEATHERS:                                              # pale face below a dark band through the eye
        face = smooth(hx + 0.02 * H, hx + 0.1 * H, p.x) * smooth(0.35, 0.0, n.z) * smooth(hz + 0.03 * D, hz - 0.0 * D, p.z)
        c = [c[i] + (FACE[i] - c[i]) * face * 0.9 for i in range(3)]
    lip = (1 - smooth(0.006 * D, 0.014 * D, abs(p.z - mouth_z(v.co.x) / S))) * smooth(hx + 0.02 * H, hx + 0.07 * H, p.x)
    c = [c[i] + (MOUTH[i] - c[i]) * lip for i in range(3)]
    shade = rng.uniform(0.93, 1.07) * (0.35 + 0.65 * ao[v.index] ** 1.3)
    ca.data[v.index].color = (*(x * shade for x in c), 1.0)
body_me.color_attributes.active_color = ca
body_me.color_attributes.render_color_index = body_me.color_attributes.find("Col")

# ---------------------------------------------------------------- feathers (raptor): alpha-tested cards on a skinned mesh
# A painted atlas of four feather shapes (grey detail x the card's vertex colour = the plumage pattern), cards laid
# over the flesh by region with a Poisson-disc spacing, a distichous fan down the tail and long remiges off the arms.
# Every card vertex copies the weights of one anchor (the flesh vertex under its root, or a bone), so a card rides
# the body rigidly; its normals copy the flesh normal, so plumage shades like a soft coat, not like a pile of blades.
ATLAS_W, ATLAS_H, CELLS = 1024, 512, 4
FEATHER_SEED = 21
BLACK = (0.03, 0.033, 0.045)      # blue-black plumage
PALE = (0.42, 0.42, 0.4)           # the pale streaks: behind the eye, down the neck, blotches on the flanks
GREY = (0.16, 0.16, 0.16)          # belly and under the tail


def feather_atlas():
    """Four cells, root at the bottom, tip at the top: 0 contour, 1 shaggy ruff, 2 flight feather, 3 ragged contour."""
    import numpy as np
    cw = ATLAS_W // CELLS
    v, u = np.mgrid[0:ATLAS_H, 0:cw].astype(np.float32)
    v = v / (ATLAS_H - 1)                      # 0 root .. 1 tip
    u = (u / (cw - 1)) * 2 - 1                 # -1 .. 1 across
    au = np.abs(u)
    frng = np.random.default_rng(FEATHER_SEED)
    out = np.zeros((ATLAS_H, ATLAS_W, 4), np.float32)

    def ss(e0, e1, x):
        t = np.clip((x - e0) / (e1 - e0), 0, 1)
        return t * t * (3 - 2 * t)

    def vane(width, rag, barb_freq, rachis):
        splits = np.zeros_like(v)
        for vn in frng.uniform(0.25, 0.9, rag):   # the gaps where barbs have split apart
            side = frng.choice([-1, 1])
            splits += np.exp(-((v - vn - 0.25 * au) * 55) ** 2) * ss(0.2, 0.6, u * side)
        edge = width - au - 0.35 * splits * width
        alpha = ss(0.0, 0.04, edge)
        barbs = 0.5 + 0.5 * np.sin((v * barb_freq - au * barb_freq * 0.45) * 2 * np.pi)
        tone = 0.72 + 0.2 * barbs + 0.25 * np.exp(-(u / rachis) ** 2) * (1 - v * 0.6)
        tone *= 0.45 + 0.55 * ss(0.0, 0.3, v)     # darker at the root, where it tucks under its neighbours
        tone *= 1.0 - 0.25 * (1 - ss(0.0, 0.5, edge / np.maximum(width, 1e-3)))
        return tone, alpha

    prof = np.sin(np.pi * np.clip(v * 0.98 + 0.02, 0, 1)) ** 0.55
    cells = []
    cells.append(vane(0.9 * prof * (1 - 0.15 * v), 3, 34, 0.035))
    # shaggy: seven tapering strands from a common root, splayed a little
    alpha = np.zeros_like(v)
    tone = np.zeros_like(v)
    for c in frng.uniform(-0.65, 0.65, 7):
        cu = c * ss(0.0, 0.6, v) + 0.08 * np.sin(v * 9 + c * 5)
        w = 0.14 * (1 - v) ** 0.7 + 0.01
        a = ss(0.0, 0.03, w - np.abs(u - cu)) * (v < frng.uniform(0.75, 1.0))
        alpha = np.maximum(alpha, a)
        tone = np.maximum(tone, a * (0.75 + 0.25 * np.cos((u - cu) / w * 1.5)))
    tone *= 0.45 + 0.55 * ss(0.0, 0.35, v)
    cells.append((tone, alpha))
    # flight feather: long, narrow leading vane, broad trailing vane, pointed tip
    fp = np.clip(np.sin(np.pi * np.clip(v, 0, 1)) ** 0.35 * (1 - v ** 3), 0, 1)
    width = np.where(u < 0, 0.45, 0.85) * fp
    cells.append(vane(width, 2, 60, 0.03))
    cells.append(vane(0.95 * prof, 6, 28, 0.04))
    for i, (t, a) in enumerate(cells):
        sl = slice(i * cw, (i + 1) * cw)
        t = np.clip(t, 0, 1)
        out[:, sl, 0], out[:, sl, 1], out[:, sl, 2], out[:, sl, 3] = t, t, t * 1.02, a
    out[:, :, :3] = np.clip(out[:, :, :3], 0, 1) ** 2.2    # author in sRGB-ish tone, store linear
    img = bpy.data.images.get(PREFIX + "FeatherAtlas")
    if img:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(PREFIX + "FeatherAtlas", ATLAS_W, ATLAS_H, alpha=True, float_buffer=False)
    img.pixels.foreach_set(out.ravel())
    img.pack()
    return img


def nearest_bone(p):
    best, name = 1e9, None
    for bn, h, t, _ in BONES:
        a, b = P(h), P(t)
        ab = b - a
        tt = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
        d = (p - (a + ab * tt)).length / max(0.5 * (max(R(h)) + max(R(t))), 1e-3)
        if d < best:
            best, name = d, bn
    return name


def plumage(p, n, bone):
    """(length, width, flow direction, lift, atlas cell, colour) for a card rooted at p (raptor metres), or None."""
    x, y, z = p
    side = abs(y)
    # pale markings: slanting bars on the lower flanks, not noise, so they read as a pattern
    blotch = 2.0 * (math.sin(x * 6.5 - z * 5 + 0.8 * math.sin(z * 9)) > 0.8) * (-0.45 < n.z < 0.3)
    if bone in ("Head", "Jaw"):
        if x > hx + 0.1 * H or z < hz - 0.03 * D:           # the snout and jaw stay scaly
            return None
        eye = Vector(((hx + 0.15 * H), math.copysign(0.07 * H, y), hz + 0.022 * D))
        if (Vector(p) - eye).length < 0.05 * H:
            return None
        streak = smooth(hz + 0.02 * D, hz - 0.02 * D, z) * smooth(0.02, 0.05, side)   # pale line back from the eye
        colour = PALE if streak > 0.5 else BLACK
        return 0.07, 0.05, Vector((-1, 0, 0.35)), 0.55, 1, colour
    if bone in ("Neck1", "Neck2"):
        t = smooth(K["neck0"][0].x / S, hx, x)
        streak = smooth(0.25, 0.7, side / max(0.08, 0.13 - 0.05 * t)) * smooth(0.2, -0.3, n.z + 0.3 * (1 - t))
        colour = PALE if streak > 0.5 or (blotch > 1.0 and n.z < 0.3) else BLACK
        return 0.21 - 0.05 * t, 0.085, Vector((-1, 0, -0.55)), 0.55, 1 if rng.random() < 0.7 else 3, colour
    if bone in ("Chest", "Pelvis"):
        belly = n.z < -0.45
        colour = GREY if belly else PALE if (blotch > 1.05 and n.z < 0.5) else BLACK
        return 0.17, 0.062, Vector((-1, 0, -0.45)), 0.38, 0 if rng.random() < 0.6 else 3, colour
    if bone.startswith("Tail"):
        colour = GREY if n.z < -0.5 else PALE if (blotch > 1.2 and n.z < 0.3) else BLACK
        return 0.14, 0.058, Vector((-1, 0, -0.1)), 0.28, 0, colour
    if bone.startswith("Thigh"):
        if z < 0.84:                                       # feathered drumstick, bare below the knee
            return None
        colour = PALE if blotch > 1.1 else BLACK
        return 0.12, 0.058, Vector((-0.5, 0, -1)), 0.28, 3, colour
    if bone.startswith("Arm"):
        return 0.08, 0.06, Vector((-0.4, 0, -1)), 0.3, 0, BLACK
    return None


def build_feathers():
    img = feather_atlas()
    frng = random.Random(FEATHER_SEED)
    fverts, ffaces, fuvs, fcols, fnorms, fanchor = [], [], [], [], [], []
    cw = 1.0 / CELLS

    def card(root, flow, nrm, length, width, lift, cell, colour, anchor, shade=1.0, droop=0.5):
        f_ = (flow - nrm * flow.dot(nrm)).normalized()
        sd = nrm.cross(f_).normalized()
        d0 = (f_ * math.cos(lift) + nrm * math.sin(lift)).normalized()
        d1 = (f_ * math.cos(lift * (1 - droop)) + nrm * math.sin(lift * (1 - droop))).normalized()
        mid = root + d0 * length * 0.5
        tip = mid + d1 * length * 0.5
        base = len(fverts)
        u0, u1 = cell * cw + 0.004, (cell + 1) * cw - 0.004
        for row, (c, vv) in enumerate(((root, 0.0), (mid, 0.5), (tip, 1.0))):
            w = width * (0.8 if row == 0 else 1.0)
            for k_, uu in ((-1, u0), (1, u1)):
                fverts.append(c + sd * w * 0.5 * k_)
                fuvs.append((uu, vv * 0.995 + 0.002))
                fnorms.append(nrm)
                fanchor.append(anchor)
                fcols.append(tuple(ch * shade for ch in colour))
        ffaces.extend([(base, base + 1, base + 3, base + 2), (base + 2, base + 3, base + 5, base + 4)])

    # --- body plumage: area-weighted samples on the flesh, thinned to a Poisson-disc by a hash grid
    flesh = [poly for poly in body_me.polygons if all(i < n_body for i in poly.vertices)]
    areas = [poly.area for poly in flesh]
    samples = frng.choices(flesh, weights=areas, k=26000)
    grid, cell_size, placed = {}, 0.035 * S, 0
    for poly in samples:
        vs = [body_me.vertices[i] for i in poly.vertices[:3]]
        a_, b_ = frng.random(), frng.random()
        if a_ + b_ > 1:
            a_, b_ = 1 - a_, 1 - b_
        p = vs[0].co + (vs[1].co - vs[0].co) * a_ + (vs[2].co - vs[0].co) * b_
        nrm = poly.normal.copy()
        bone = nearest_bone(p)
        spec = plumage(p / S, nrm, bone)
        if spec is None:
            continue
        length, width, flow, lift, cell, colour = spec
        length *= frng.uniform(0.85, 1.15) * S
        width *= frng.uniform(0.9, 1.1) * S
        spacing = width * 0.62
        gx, gy, gz = (int(c // cell_size) for c in p)
        reach = int(spacing // cell_size) + 1
        if any((q - p).length < spacing for i in range(gx - reach, gx + reach + 1)
               for j in range(gy - reach, gy + reach + 1) for k2 in range(gz - reach, gz + reach + 1)
               for q in grid.get((i, j, k2), ())):
            continue
        grid.setdefault((gx, gy, gz), []).append(p)
        anchor = min(poly.vertices, key=lambda i: (body_me.vertices[i].co - p).length)
        if abs(p.y) > 0.02 * S:                              # flanks: splay a little outward
            flow = flow + Vector((0, math.copysign(0.25, p.y), 0))
        card(p - nrm * 0.006 * S, flow, nrm, length, width, lift, cell, colour, anchor,
             shade=frng.uniform(0.8, 1.15) * (0.45 + 0.55 * ao[anchor]))
        placed += 1

    # --- tail fan: rectrices in two layers either side, lengthening toward the tip, splayed back and out
    for s_ in (1, -1):
        for layer in (0, 1):
            n_ = 26
            for i in range(n_):
                t = (i + 0.5 * layer) / n_
                x = (-0.8 - 1.65 * t) * S
                loc, nrm_ = surface(Vector((x, 0, P("tail3").z * (1 - t) + P("tail5").z * t + 0.01 * S)),
                                    Vector((0, s_, 0.15 * layer)))
                if loc is None:
                    continue
                spread = 0.8 - 0.45 * t
                d = Vector((-1, s_ * spread, -0.1 * (1 - layer)))
                length = (0.2 + 0.3 * t ** 0.8) * S * frng.uniform(0.9, 1.1)
                anchor = body_kd_find(loc)
                pale = frng.random() < 0.22 + 0.2 * layer
                fan_n = Vector((0, s_ * 0.5, 0.86))       # the fan droops at its edges, so it has depth from the side
                card(loc - Vector((0, s_ * 0.01, 0)) * S, d, fan_n, length, 0.11 * S, 0.06 + 0.05 * layer, 2,
                     PALE if pale else BLACK, anchor, shade=frng.uniform(0.85, 1.1), droop=0.2)
    for j in range(5):                                      # the tip: straight back
        a = (j / 4 - 0.5) * 0.7
        loc = P("tail5").lerp(P("tail4"), 0.15)
        card(loc, Vector((-1, math.sin(a), 0.02)), Vector((0, 0, 1)), 0.45 * S, 0.11 * S, 0.05, 2, BLACK,
             body_kd_find(loc), droop=0.2)

    # --- arms: remiges hanging from the forearm and hand like a folded wing, coverts over their roots
    for sd, s_ in (("L", 1), ("R", -1)):
        for layer in (0, 1):
            for i in range(11):
                t = (i + 0.5 * layer) / 10.5
                root = P("elbow" + sd).lerp(P("hand" + sd), 0.05 + 0.95 * t) + Vector((-0.012, s_ * 0.004, 0)) * S
                d = Vector((-0.55 + 0.45 * t, s_ * 0.05, -1))
                length = ((0.26 + 0.16 * t) if layer == 0 else (0.13 + 0.06 * t)) * S * ARM
                card(root, d, Vector((0, s_, 0)), length, 0.085 * S * ARM, 0.05, 2 if layer == 0 else 0,
                     PALE if (layer == 0 and i in (2, 6, 9)) else BLACK, "Fore." + sd, shade=frng.uniform(0.85, 1.1),
                     droop=0.25)

    me = bpy.data.meshes.new(PREFIX + "Feathers")
    me.from_pydata(fverts, [], ffaces)
    uv = me.uv_layers.new(name="UV")
    for loop in me.loops:
        uv.data[loop.index].uv = fuvs[loop.vertex_index]
    fc = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    for i, c in enumerate(fcols):
        fc.data[i].color = (*c, 1.0)
    me.color_attributes.active_color = fc
    me.color_attributes.render_color_index = me.color_attributes.find("Col")
    for poly in me.polygons:
        poly.use_smooth = True
    print("FEATHERS cards", len(ffaces) // 2, "body", placed, "tris", len(ffaces) * 2)
    return me, img, fnorms, fanchor


def body_kd_find(p):
    return _kd.find(p)[1]


if FEATHERS:
    from mathutils.kdtree import KDTree
    _kd = KDTree(n_body)
    for v in body_me.vertices[:n_body]:
        _kd.insert(v.co, v.index)
    _kd.balance()
    feather_me, feather_img, feather_normals, feather_anchor = build_feathers()

# ---------------------------------------------------------------- UVs + baked scales, painted irises
# The flesh has no UVs (it came out of metaballs), so: smart-project the skin, give the scaly regions (feet, shins,
# face) more of the sheet, then bake a 3D procedural scale field (Voronoi cells: domed scales, dark grooves) into a
# tangent-space normal map and a grey detail map. The field is 3D, so UV seams don't show in the pattern.
# The detail map multiplies the vertex colours (glTF: baseColorTexture x COLOR_0).
SCALE_TEX = 2048
IRIS_TEX = 512
IRIS = (0.5, 0.26, 0.04)           # deep amber


SCALE_FINE, SCALE_BIG = 0.011, 0.017      # scale diameters (raptor m): face/legs, and the scutes down the foot


def scale_fields():
    """Per-vertex ScaleMask (0 smooth .. 1 fully scaled) and ScaleBig (0 fine scales .. 1 big scutes). Two fixed
    sizes blended, never a varying Voronoi scale: a scale that changes across the surface smears the cells."""
    mask = body_me.attributes.new("ScaleMask", "FLOAT", "POINT")
    big = body_me.attributes.new("ScaleBig", "FLOAT", "POINT")
    for v in body_me.vertices:
        p = v.co / S
        bone = nearest_bone(v.co)
        m, b_ = 0.3, 0.0                         # pebbly skin under the feathers: barely there
        if bone.startswith(("Meta", "Toe")):
            m, b_ = 1.0, 1.0
        elif bone.startswith("Shin"):
            m, b_ = 1.0, 0.5
        elif bone.startswith("Thigh"):
            m = 1.0 - 0.7 * smooth(0.78, 0.9, p.z)
        elif bone in ("Head", "Jaw"):
            m = 0.45 + 0.55 * smooth(hx - 0.01 * H, hx + 0.06 * H, p.x)
        elif bone.startswith(("Arm", "Fore")):
            m = 0.7
        if not FEATHERS:
            m = max(m, 0.7)                      # the rex is scaly all over
        mask.data[v.index].value = m
        big.data[v.index].value = b_


def unwrap():
    ob = bpy.data.objects.new(PREFIX + "UVTmp", body_me)
    col.objects.link(ob)
    vl = bpy.context.view_layer
    vl.update()
    for o in vl.objects:
        if o is not None:
            o.select_set(False)
    ob.select_set(True)
    vl.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    ebm = bmesh.from_edit_mesh(body_me)
    for fc in ebm.faces:
        fc.select_set(fc.material_index == 0)
    bmesh.update_edit_mesh(body_me)
    bpy.ops.uv.smart_project(angle_limit=math.radians(78), island_margin=0.002, scale_to_bounds=False)
    # islands: faces joined across edges whose UVs agree; scale each by how scaly it is, then repack
    ebm = bmesh.from_edit_mesh(body_me)
    uvl = ebm.loops.layers.uv.active
    ml = ebm.verts.layers.float["ScaleMask"]
    faces = [fc for fc in ebm.faces if fc.material_index == 0]
    parent = {fc.index: fc.index for fc in faces}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for e in ebm.edges:
        lf = [l for l in e.link_loops if l.face.material_index == 0]
        if len(lf) != 2:
            continue
        a_, b_ = lf
        # the two loops run opposite ways along a shared edge: a.vert == b.next.vert
        if (a_[uvl].uv - b_.link_loop_next[uvl].uv).length < 1e-5 and (a_.link_loop_next[uvl].uv - b_[uvl].uv).length < 1e-5:
            parent[find(a_.face.index)] = find(b_.face.index)
    islands = {}
    for fc in faces:
        islands.setdefault(find(fc.index), []).append(fc)
    for isl in islands.values():
        loops = [l for fc in isl for l in fc.loops]
        m = sum(l.vert[ml] for l in loops) / len(loops)
        k = 0.45 + 2.6 * m ** 1.5              # the feathered body gets little; feet and face ~15x its texel area
        c = sum((l[uvl].uv for l in loops), Vector((0, 0))) / len(loops)
        for l in loops:
            l[uvl].uv = c + (l[uvl].uv - c) * k
    bmesh.update_edit_mesh(body_me)
    bpy.ops.uv.pack_islands(rotate=True, margin=0.002)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.data.objects.remove(ob, do_unlink=True)


def new_image(name, w, h, data):
    img = bpy.data.images.get(name)
    if img:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(name, w, h, alpha=False, is_data=data)
    return img


def store_jpeg(img):
    """Save as JPEG and pack, so the glTF exporter embeds a JPEG rather than a multi-MB PNG."""
    import os
    path = os.path.join(bpy.app.tempdir or os.environ.get("TEMP", "."), img.name + ".jpg")
    img.filepath_raw = path
    img.file_format = "JPEG"
    scene.render.image_settings.quality = 90
    img.save()
    img.pack()


def bake_scales():
    """Bake on a copy holding only the skin faces, so teeth/eyes/claws never write into the sheet."""
    me = body_me.copy()
    me.name = PREFIX + "BakeTmp"
    tbm = bmesh.new()
    tbm.from_mesh(me)
    bmesh.ops.delete(tbm, geom=[fc for fc in tbm.faces if fc.material_index != 0], context="FACES")
    tbm.to_mesh(me)
    tbm.free()
    me.materials.clear()
    mat = bpy.data.materials.new(PREFIX + "BakeTmp")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    N = nt.nodes.new
    out = N("ShaderNodeOutputMaterial")
    coord = N("ShaderNodeTexCoord")
    msk = N("ShaderNodeAttribute")
    msk.attribute_name = "ScaleMask"
    bigw = N("ShaderNodeAttribute")
    bigw.attribute_name = "ScaleBig"

    def layer(size):
        """Voronoi at one fixed size -> (height, groove, cell colour) sockets."""
        vor = N("ShaderNodeTexVoronoi")          # F1: the dome of each scale
        vor.voronoi_dimensions = "3D"
        edg = N("ShaderNodeTexVoronoi")          # distance to edge: the grooves between them
        edg.voronoi_dimensions = "3D"
        edg.feature = "DISTANCE_TO_EDGE"
        for vn in (vor, edg):
            vn.inputs["Randomness"].default_value = 0.85
            vn.inputs["Scale"].default_value = 1.0 / (size * S)
            nt.links.new(coord.outputs["Object"], vn.inputs["Vector"])
        dome = N("ShaderNodeMapRange")
        dome.inputs["From Min"].default_value, dome.inputs["From Max"].default_value = 0.0, 0.65
        dome.inputs["To Min"].default_value, dome.inputs["To Max"].default_value = 1.0, 0.0
        nt.links.new(vor.outputs["Distance"], dome.inputs["Value"])
        groove = N("ShaderNodeMapRange")
        groove.interpolation_type = "SMOOTHERSTEP"
        groove.inputs["From Min"].default_value, groove.inputs["From Max"].default_value = 0.0, 0.1
        nt.links.new(edg.outputs["Distance"], groove.inputs["Value"])
        h = N("ShaderNodeMath")
        h.operation = "MULTIPLY_ADD"
        nt.links.new(dome.outputs["Result"], h.inputs[0])
        h.inputs[1].default_value = 0.45
        nt.links.new(groove.outputs["Result"], h.inputs[2])
        return h.outputs[0], groove.outputs["Result"], vor.outputs["Color"]

    def blend(a_, b_):
        m_ = N("ShaderNodeMix")
        m_.data_type = "FLOAT"
        nt.links.new(bigw.outputs["Fac"], m_.inputs["Factor"])
        nt.links.new(a_, m_.inputs["A"])
        nt.links.new(b_, m_.inputs["B"])
        return m_.outputs["Result"]

    fine, big_ = layer(SCALE_FINE), layer(SCALE_BIG)
    height_out, groove_out = blend(fine[0], big_[0]), blend(fine[1], big_[1])
    cellc = N("ShaderNodeMix")
    cellc.data_type = "RGBA"
    nt.links.new(bigw.outputs["Fac"], cellc.inputs["Factor"])
    nt.links.new(fine[2], cellc.inputs["A"])
    nt.links.new(big_[2], cellc.inputs["B"])
    bump = N("ShaderNodeBump")
    bump.inputs["Distance"].default_value = 0.0025 * S
    strength = N("ShaderNodeMath")
    strength.operation = "MULTIPLY"
    strength.inputs[1].default_value = 0.9
    nt.links.new(msk.outputs["Fac"], strength.inputs[0])
    nt.links.new(strength.outputs[0], bump.inputs["Strength"])
    nt.links.new(height_out, bump.inputs["Height"])
    diff = N("ShaderNodeBsdfDiffuse")
    nt.links.new(bump.outputs["Normal"], diff.inputs["Normal"])
    # grey detail: dark grooves, a little per-scale variation, fading to plain white where the mask is 0
    tone = N("ShaderNodeMapRange")
    tone.inputs["To Min"].default_value, tone.inputs["To Max"].default_value = 0.42, 1.0
    nt.links.new(groove_out, tone.inputs["Value"])
    var = N("ShaderNodeMapRange")
    var.inputs["To Min"].default_value, var.inputs["To Max"].default_value = 0.85, 1.12
    nt.links.new(cellc.outputs["Result"], var.inputs["Value"])
    mul = N("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    nt.links.new(tone.outputs["Result"], mul.inputs[0])
    nt.links.new(var.outputs["Result"], mul.inputs[1])
    mixv = N("ShaderNodeMix")                       # lerp(1, detail, mask)
    mixv.data_type = "FLOAT"
    mixv.inputs["A"].default_value = 1.0
    nt.links.new(msk.outputs["Fac"], mixv.inputs["Factor"])
    nt.links.new(mul.outputs[0], mixv.inputs["B"])
    emit = N("ShaderNodeEmission")
    nt.links.new(mixv.outputs["Result"], emit.inputs["Color"])
    img_n = new_image(PREFIX + "ScaleNormal", SCALE_TEX, SCALE_TEX, True)
    img_d = new_image(PREFIX + "ScaleDetail", SCALE_TEX, SCALE_TEX, False)
    tn = N("ShaderNodeTexImage")
    tn.image = img_n
    td = N("ShaderNodeTexImage")
    td.image = img_d
    me.materials.append(mat)
    ob = bpy.data.objects.new(PREFIX + "BakeTmp", me)
    col.objects.link(ob)
    vl = bpy.context.view_layer
    vl.update()
    for o in vl.objects:
        if o is not None:
            o.select_set(False)
    ob.select_set(True)
    vl.objects.active = ob
    engine = scene.render.engine
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 8
    scene.render.bake.margin = 8
    try:
        nt.links.new(diff.outputs["BSDF"], out.inputs["Surface"])
        nt.nodes.active = tn
        bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", use_clear=True)
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
        nt.nodes.active = td
        bpy.ops.object.bake(type="EMIT", use_clear=True)
    finally:
        scene.render.engine = engine
        bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.meshes.remove(me)
        bpy.data.materials.remove(mat)
    store_jpeg(img_n)
    store_jpeg(img_d)
    return img_n, img_d


def iris_uvs():
    """Front-project each eyeball's UVs from its look axis: the iris sits on the cornea, the back is dark."""
    uvl = body_me.uv_layers.active
    for poly in body_me.polygons:
        if poly.material_index != 1:
            continue
        c0 = poly.center
        center, a, side, up, r = min(EYES, key=lambda e: (e[0] - c0).length)
        for li in poly.loop_indices:
            d = body_me.vertices[body_me.loops[li].vertex_index].co - center
            back = d.dot(a) < 0
            uvl.data[li].uv = (0.02, 0.02) if back else (0.5 + d.dot(side) / (2 * r), 0.5 + d.dot(up) / (2 * r))


def iris_image():
    import numpy as np
    n = IRIS_TEX
    y, x = (np.mgrid[0:n, 0:n].astype(np.float32) / (n - 1)) * 2 - 1
    rr = np.sqrt(x * x + y * y)
    ang = np.arctan2(y, x)
    irng = np.random.default_rng(5)
    ph = irng.uniform(0, 6.28, 5)

    def ss(e0, e1, v):
        t = np.clip((v - e0) / (e1 - e0), 0, 1)
        return t * t * (3 - 2 * t)

    fibres = 0.5 + 0.5 * np.sin(ang * 70 + 3 * np.sin(ang * 7 + ph[0]) + rr * 9)
    flecks = 0.5 + 0.5 * np.sin(ang * 23 + ph[1]) * np.sin(rr * 40 + ph[2])
    iris = np.array(IRIS, np.float32)
    col_ = iris[None, None, :] * (0.55 + 0.55 * fibres[..., None] ** 2) * (0.8 + 0.45 * flecks[..., None] ** 3)
    col_ *= (1.0 + 0.35 * (1 - ss(0.3, 0.5, rr)))[..., None]             # a brighter gold collar round the pupil
    col_ *= (1.0 - 0.75 * ss(0.72, 0.92, rr))[..., None]                 # dark limbal ring
    pupil = 1 - ss(0.26, 0.3, rr)
    col_ *= (1 - pupil)[..., None]
    col_[rr > 0.95] = (0.02, 0.015, 0.01)
    col_ = np.clip(col_, 0, 1)
    rgba = np.concatenate([col_, np.ones((n, n, 1), np.float32)], axis=2)
    img = bpy.data.images.get(PREFIX + "Iris")
    if img:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(PREFIX + "Iris", n, n, alpha=False)
    img.pixels.foreach_set(rgba.astype(np.float32).ravel())
    store_jpeg(img)
    return img


scale_fields()
unwrap()
iris_uvs()
scale_normal_img, scale_detail_img = bake_scales()
iris_img = iris_image()

# ---------------------------------------------------------------- face -Y (the repo's forward: Three.js +Z)
# everything above is authored facing +X with +Y to the left; one rotation puts it in the export frame
ROT = Matrix.Rotation(-math.pi / 2, 4, "Z")
body_me.transform(ROT)
if FEATHERS:
    feather_me.transform(ROT)
    feather_normals = [(ROT.to_3x3() @ n).normalized() for n in feather_normals]
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


def image_node(nt, img, data=False):
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = img
    if data:
        img.colorspace_settings.name = "Non-Color"
    return t


skin = material(PREFIX + "Skin", (1, 1, 1), 0.62, vcol=True)
nt = skin.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
vcn = next(n for n in nt.nodes if n.type == "VERTEX_COLOR")
mix = nt.nodes.new("ShaderNodeMix")            # scale detail x vertex colours: glTF baseColorTexture x COLOR_0
mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
mix.inputs["Factor"].default_value = 1.0
nt.links.new(image_node(nt, scale_detail_img).outputs["Color"], mix.inputs["A"])
nt.links.new(vcn.outputs["Color"], mix.inputs["B"])
nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
nmap = nt.nodes.new("ShaderNodeNormalMap")
nt.links.new(image_node(nt, scale_normal_img, True).outputs["Color"], nmap.inputs["Color"])
nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
body_me.materials.append(skin)
eye_m = material(PREFIX + "Eye", (1, 1, 1), 0.04)
nt = eye_m.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
it = image_node(nt, iris_img)
nt.links.new(it.outputs["Color"], bsdf.inputs["Base Color"])
nt.links.new(it.outputs["Color"], bsdf.inputs["Emission Color"])   # a faint eyeshine: the fog still shows the eyes
bsdf.inputs["Emission Strength"].default_value = EYE_GLOW
bsdf.inputs["Coat Weight"].default_value = 1.0                      # the wet cornea
bsdf.inputs["Coat Roughness"].default_value = 0.02
body_me.materials.append(eye_m)
body_me.materials.append(material(PREFIX + "Keratin", (0.55, 0.5, 0.4), 0.4))
body_me.materials.append(material(PREFIX + "Claw", CLAW, 0.3))
body = bpy.data.objects.new(PREFIX + "Body", body_me)
col.objects.link(body)
if FEATHERS:
    fm = bpy.data.materials.get(PREFIX + "Feather") or bpy.data.materials.new(PREFIX + "Feather")
    fm.use_nodes = True
    nt = fm.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = 0.72
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = feather_img
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = "Col"
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    nt.links.new(tex.outputs["Color"], mix.inputs["A"])
    nt.links.new(vc.outputs["Color"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    clip = nt.nodes.new("ShaderNodeMath")             # Round = alpha clip at 0.5: glTF alphaMode MASK
    clip.operation = "ROUND"
    nt.links.new(tex.outputs["Alpha"], clip.inputs[0])
    nt.links.new(clip.outputs[0], bsdf.inputs["Alpha"])
    fm.use_backface_culling = False
    feather_me.materials.append(fm)
    feather_me.normals_split_custom_set_from_vertices(feather_normals)
    feathers = bpy.data.objects.new(PREFIX + "Feathers", feather_me)
    col.objects.link(feathers)

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
if FEATHERS:                             # each card vertex takes its anchor's weights (a flesh vertex, or a bone)
    for name in seg:
        feathers.vertex_groups.new(name=name)
    for i, a in enumerate(feather_anchor):
        if isinstance(a, str):
            feathers.vertex_groups[a].add([i], 1.0, "REPLACE")
        else:
            for ge in body_me.vertices[a].groups:
                feathers.vertex_groups[body.vertex_groups[ge.group].name].add([i], ge.weight, "REPLACE")
    fmod = feathers.modifiers.new("Armature", "ARMATURE")
    fmod.object = arm
    feathers.parent = arm
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
