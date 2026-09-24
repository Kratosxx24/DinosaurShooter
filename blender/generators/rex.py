"""Tyrannosaurus for the forest shooter (~10.6 m, hip 3.1 m): a sculpted SDF body, 22-bone FK rig, clips
Idle/Run/Attack/Roar/Death, `knots` extras for the game's hitboxes. Same GLB contract as dino.py's raptor
(Rex_Skin / Rex_Eye / Rex_Keratin, bone names, knot names, run_speed), so index.html needs no changes.

Why not dino.py's skin modifier: a knot tree of round tubes can't make a rex skull, drumstick thighs or
three-toed feet. Here the flesh is a signed-distance sculpt (sdf.py): ellipse-swept limbs, ellipsoid
muscles, brow bosses and cheek flares smooth-unioned, a carved lip line and eye sockets. Surface nets
turn it into quads, Newton-projected onto the surface.

    DETAIL = "game"   voxel 4 cm -> decimated to ~GAME_TRIS, the exported GLB
    DETAIL = "hero"   voxel HERO_H, no decimation, extra `Rex_Detail` colour data for Cycles (renders/)

Frame: authored facing +X with +Y to the left in metres; rotated at the end so the rex faces -Y (Three +Z).
"""
import bpy
import bmesh
import json
import math
import os
import random
import sys
import numpy as np
from mathutils import Vector, Matrix, Euler

sys.path.insert(0, os.path.dirname(os.path.abspath(globals().get("__file__", "."))))
import sdf  # noqa: E402

KIND = "rex"
COLLECTION = "Dino_rex"
PREFIX = "Rex_"
DETAIL = globals().get("DETAIL", "game")
HERO_H = float(globals().get("HERO_H", 0.02))
GAME_H = 0.04
GAME_TRIS = 11000
FPS = 24
SKIN_SHARP = 5.0
RUN_SPEED, RUN_PERIOD = 7.0, 0.9
S = 2.35                                    # legacy: the game's raptor-relative scale, only stored as a prop
EYE = (1.0, 0.45, 0.08)
EYE_STRENGTH = 12.0
rng = random.Random(11)

# colours (linear): olive-umber back, dusty tan belly, near-black bands, a rust flush on the face
C_BACK = np.array((0.045, 0.036, 0.022))
C_FLANK = np.array((0.11, 0.085, 0.05))
C_BELLY = np.array((0.34, 0.29, 0.21))
C_BAND = np.array((0.016, 0.013, 0.01))
C_RUST = np.array((0.16, 0.055, 0.025))
C_MOUTH = np.array((0.22, 0.035, 0.03))
C_KERATIN = (0.55, 0.5, 0.4)

# ---------------------------------------------------------------- knots: the rig and the game's hitboxes
K = {}


def knot(name, x, y, z, rw, rh=None):
    K[name] = (Vector((x, y, z)), (rw, rh if rh is not None else rw))


H0 = np.array((3.0, 0.0, 3.85))             # occiput: the head bone's root
knot("tail5", -6.35, 0, 2.2, 0.05)
knot("tail4", -4.7, 0, 2.58, 0.17, 0.24)
knot("tail3", -3.2, 0, 2.88, 0.3, 0.4)
knot("tail2", -1.7, 0, 3.05, 0.44, 0.56)
knot("hip", 0.0, 0, 3.1, 0.62, 0.78)
knot("chest", 1.5, 0, 3.0, 0.62, 0.85)
knot("neck0", 2.35, 0, 3.28, 0.46, 0.56)
knot("neck1", 2.72, 0, 3.62, 0.38, 0.44)
knot("head0", *H0, 0.38, 0.42)
knot("snout", 4.43, 0, 3.6, 0.14, 0.2)
knot("jawtip", 4.33, 0, 3.33, 0.12, 0.12)
knot("quad", 3.1, 0, 3.47, 0.2)             # jaw hinge
knot("skull", 3.55, 0, 3.75, 0.36)          # mesh-free: framing for tools/model_views.py
for s, sd in ((1, "L"), (-1, "R")):
    knot("hip" + sd, 0.05, s * 0.56, 2.85, 0.4, 0.55)
    knot("knee" + sd, 0.58, s * 0.66, 1.72, 0.22, 0.26)
    knot("ankle" + sd, -0.1, s * 0.62, 0.7, 0.11, 0.12)
    knot("ball" + sd, 0.16, s * 0.62, 0.14, 0.11, 0.09)
    knot("toe" + sd, 0.74, s * 0.62, 0.06, 0.06)
    knot("sh" + sd, 1.78, s * 0.5, 2.55, 0.11)
    knot("elbow" + sd, 1.9, s * 0.6, 2.22, 0.08)
    knot("hand" + sd, 2.16, s * 0.57, 2.05, 0.05)

BONES = [("Pelvis", "hip", "chest", None), ("Chest", "chest", "neck0", "Pelvis"),
         ("Neck1", "neck0", "neck1", "Chest"), ("Neck2", "neck1", "head0", "Neck1"),
         ("Head", "head0", "snout", "Neck2"), ("Jaw", "quad", "jawtip", "Head"),
         ("Tail1", "hip", "tail2", "Pelvis"), ("Tail2", "tail2", "tail3", "Tail1"),
         ("Tail3", "tail3", "tail4", "Tail2"), ("Tail4", "tail4", "tail5", "Tail3")]
for sd in "LR":
    BONES += [(f"Thigh.{sd}", "hip" + sd, "knee" + sd, "Pelvis"), (f"Shin.{sd}", "knee" + sd, "ankle" + sd, f"Thigh.{sd}"),
              (f"Meta.{sd}", "ankle" + sd, "ball" + sd, f"Shin.{sd}"), (f"Toe.{sd}", "ball" + sd, "toe" + sd, f"Meta.{sd}"),
              (f"Arm.{sd}", "sh" + sd, "elbow" + sd, "Chest"), (f"Fore.{sd}", "elbow" + sd, "hand" + sd, f"Arm.{sd}")]
# skinning radius per bone (smaller than the flesh on the legs so the belly doesn't ride the thighs)
WEIGHT_R = {"Pelvis": 0.8, "Chest": 0.85, "Neck1": 0.5, "Neck2": 0.42, "Head": 0.35, "Jaw": 0.25, "Tail1": 0.55,
            "Tail2": 0.42, "Tail3": 0.28, "Tail4": 0.14}
for sd in "LR":
    WEIGHT_R.update({f"Thigh.{sd}": 0.34, f"Shin.{sd}": 0.2, f"Meta.{sd}": 0.11, f"Toe.{sd}": 0.08,
                     f"Arm.{sd}": 0.09, f"Fore.{sd}": 0.06})


# ---------------------------------------------------------------- the sculpt
def hp(x, z, y=0.0):
    """Head-local profile coords (x forward from the occiput, z up) -> world."""
    return H0 + np.array((x, y, z))


def lip_z(x):
    """Upper/lower jaw parting line, head-local. Slightly sinuous like a rex tooth row."""
    return np.interp(x, [0.0, 0.2, 0.55, 0.95, 1.25, 1.45], [-0.3, -0.33, -0.39, -0.4, -0.37, -0.33])


def sculpt():
    E, Op, sweep = sdf.Ellipsoid, sdf.Op, sdf.sweep
    mid, side = [], []                      # side ops are authored on +Y and mirrored

    # --- trunk: tail tip -> hips -> barrel chest -> neck base (centres sit below the spine: deep body)
    mid += sweep([((-6.45, 0, 2.18), (0.02, 0.025)), ((-5.8, 0, 2.35), (0.07, 0.1)), ((-4.7, 0, 2.6), (0.15, 0.22)),
                  ((-3.2, 0, 2.88), (0.27, 0.38)), ((-1.7, 0, 3.02), (0.42, 0.55)), ((-0.5, 0, 2.98), (0.55, 0.64)),
                  ((0.4, 0, 2.86), (0.6, 0.78)), ((1.15, 0, 2.8), (0.61, 0.82)), ((1.85, 0, 2.95), (0.5, 0.64)),
                  ((2.4, 0, 3.3), (0.42, 0.5))], k=0.0)
    mid += [Op(E((0.35, 0, 2.08), (0.42, 0.2, 0.2)), k=0.35)]                       # pubic boot keel
    mid += [Op(E((0.9, 0, 2.15), (0.7, 0.42, 0.25)), k=0.4)]                        # gastralia belly
    mid += [Op(E((-0.1, 0, 3.52), (0.9, 0.34, 0.16)), k=0.35)]                      # hip ridge (ilia)
    mid += [Op(E((-1.4, 0, 3.45), (1.2, 0.16, 0.14)), k=0.3)]                       # tail-base spines
    side += [Op(E((-1.1, 0.26, 2.72), (1.1, 0.26, 0.42)), k=0.35)]                 # caudofemoralis
    side += [Op(E((1.65, 0.3, 2.5), (0.35, 0.2, 0.3)), k=0.3)]                      # pectoral / shoulder

    # --- neck: thick S-curve into the back of the skull, throat pouch under the jaw
    mid += sweep([((2.2, 0, 3.2), (0.46, 0.56)), ((2.72, 0, 3.58), (0.38, 0.45)), ((3.05, 0, 3.8), (0.33, 0.36))], k=0.0)
    mid += [Op(E((2.2, 0, 3.72), (0.55, 0.3, 0.2), ), k=0.3)]                       # nuchal muscle hump
    mid += [Op(E((2.95, 0, 3.3), (0.42, 0.3, 0.28)), k=0.3)]                        # throat

    # --- skull (head-local profile): broad at the back, narrow snout, flat-ish top
    up = [(0.05, 0.02, 0.37, 0.3), (0.33, -0.01, 0.36, 0.33), (0.68, -0.07, 0.25, 0.3), (1.02, -0.13, 0.18, 0.25),
          (1.3, -0.18, 0.13, 0.19), (1.42, -0.2, 0.1, 0.14)]
    mid += [Op(sdf.ESeg(hp(a[0], a[1]), hp(b[0], b[1]), a[2:], b[2:]), 0.0) for a, b in zip(up, up[1:])]
    lo = [(0.02, -0.4, 0.3, 0.17), (0.4, -0.5, 0.27, 0.16), (0.82, -0.53, 0.19, 0.14), (1.18, -0.51, 0.13, 0.12),
          (1.36, -0.47, 0.09, 0.1)]
    jaw = [Op(sdf.ESeg(hp(a[0], a[1]), hp(b[0], b[1]), a[2:], b[2:]), 0.0) for a, b in zip(lo, lo[1:])]
    mid += [Op(j.p, k=0.06) for j in jaw]
    side += [Op(E(hp(0.12, 0.08, 0.22), (0.26, 0.15, 0.2)), k=0.12)]               # jaw adductors (temporal)
    side += [Op(E(hp(0.2, -0.22, 0.3), (0.3, 0.1, 0.13), rot=_rot_y(-0.15)), k=0.1)]  # jugal cheek flare
    side += [Op(E(hp(0.1, -0.44, 0.26), (0.22, 0.09, 0.12)), k=0.1)]              # surangular bulge
    side += [Op(E(hp(0.44, 0.24, 0.2), (0.12, 0.08, 0.065), rot=_rot_y(0.25)), k=0.07)]  # lacrimal horn
    side += [Op(E(hp(0.3, 0.2, 0.26), (0.07, 0.07, 0.06)), k=0.05)]               # postorbital boss
    side += [Op(E(hp(0.43, 0.1, 0.33), (0.075, 0.08, 0.075)), k=0.05, sub=True)]   # orbit
    side += [Op(E(hp(1.36, -0.08, 0.085), (0.04, 0.03, 0.028)), k=0.03, sub=True)]  # nostril
    side += [Op(E(hp(0.62, -0.12, 0.24), (0.2, 0.05, 0.09)), k=0.06, sub=True)]   # antorbital hollow
    side += [Op(E(hp(0.85 + 0.12 * i, -0.33, 0.17 - 0.03 * i), (0.07, 0.04, 0.03)), k=0.04) for i in range(4)]  # lip scutes
    r = random.Random(5)
    for i in range(14):                                                            # nasal rugosity
        x = 0.62 + 0.72 * i / 13
        topz = np.interp(x, [u[0] for u in up], [u[1] + u[3] for u in up])
        yy = r.uniform(-0.05, 0.05)
        mid += [Op(E(hp(x, topz - 0.015, yy), (r.uniform(0.03, 0.05), 0.035, 0.022)), k=0.03)]
    # parting line: a thin slab from the snout back to the hinge (the corner of the mouth stays skin)
    mouth = []
    xs = np.linspace(0.3, 1.5, 13)
    for a, b in zip(xs, xs[1:]):
        wa = np.interp(a, [0.3, 1.0, 1.5], [0.36, 0.25, 0.14])
        wb = np.interp(b, [0.3, 1.0, 1.5], [0.36, 0.25, 0.14])
        mouth.append(Op(sdf.ESeg(hp(a, lip_z(a)), hp(b, lip_z(b)), (wa, 0.012), (wb, 0.012), cap=0.02), k=0.015, sub=True))
    mid += mouth

    # --- legs (+Y side): drumstick thigh, calf, slim metatarsus, three toes and a dewclaw
    side += sweep([((0.02, 0.5, 2.95), (0.36, 0.58)), ((0.32, 0.6, 2.25), (0.34, 0.48)), ((0.58, 0.66, 1.72), (0.19, 0.23))], k=0.3)
    side += [Op(E((0.3, 0.63, 2.35), (0.55, 0.34, 0.8), rot=_rot_y(-0.42)), k=0.25)]   # quad/iliotibialis mass
    side += sweep([((0.58, 0.66, 1.72), (0.19, 0.23)), ((0.3, 0.64, 1.22), (0.15, 0.18)), ((-0.1, 0.62, 0.7), (0.095, 0.11))], k=0.12)
    side += [Op(E((0.16, 0.64, 1.3), (0.15, 0.16, 0.45), rot=_rot_y(0.55)), k=0.12)]    # gastrocnemius
    side += [Op(E((0.62, 0.66, 1.75), (0.14, 0.17, 0.14)), k=0.1)]                     # knee cap
    side += sweep([((-0.1, 0.62, 0.7), (0.1, 0.11)), ((0.03, 0.62, 0.4), (0.09, 0.085)), ((0.16, 0.62, 0.14), (0.12, 0.09))], k=0.08)
    side += [Op(E((-0.13, 0.62, 0.72), (0.1, 0.11, 0.1)), k=0.06)]                     # heel
    for dy, reach, rr in ((0.0, 0.6, 1.0), (0.2, 0.46, 0.9), (-0.19, 0.44, 0.88)):      # digits III, IV, II
        a = np.array((0.16, 0.62, 0.12))
        dirv = np.array((1.0, dy / 0.55, 0.0))
        dirv /= np.linalg.norm(dirv)
        b = a + dirv * reach * 0.5 + np.array((0, 0, -0.04))
        c = a + dirv * reach + np.array((0, 0, -0.07))
        side += sweep([(a, (0.08 * rr, 0.07)), (b, (0.065 * rr, 0.055)), (c, (0.042 * rr, 0.038))], k=0.07)
        side += [Op(E(b + np.array((0, 0, -0.01)), (0.08, 0.07 * rr, 0.05)), k=0.03)]   # toe pad
    side += sweep([((0.02, 0.52, 0.34), (0.035, 0.04)), ((0.1, 0.49, 0.2), (0.025, 0.025))], k=0.05)  # dewclaw

    # --- arms: tiny but muscular, two fingers
    side += sweep([((1.72, 0.44, 2.6), (0.13, 0.13)), ((1.9, 0.6, 2.22), (0.085, 0.09)), ((2.14, 0.57, 2.05), (0.055, 0.05))], k=0.12)
    for dy in (0.025, -0.025):
        side += sweep([((2.14, 0.57 + dy, 2.05), (0.03, 0.03)), ((2.24, 0.57 + dy * 1.6, 1.97), (0.02, 0.02))], k=0.03)

    return mid + side + sdf.mirror_y(side), mouth


def _rot_y(a):
    """Rotation about the lateral axis (pitch) as a 3x3 whose columns are the local axes."""
    c, s = math.cos(a), math.sin(a)
    return np.array(((c, 0, s), (0, 1, 0), (-s, 0, c)))


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

# ---------------------------------------------------------------- body mesh
OPS, MOUTH = sculpt()
V, F = sdf.mesh(OPS, HERO_H if DETAIL == "hero" else GAME_H)
body_me = bpy.data.meshes.new(PREFIX + "Body")
body_me.vertices.add(len(V))
body_me.vertices.foreach_set("co", V.astype(np.float32).ravel())
body_me.loops.add(F.size)
body_me.loops.foreach_set("vertex_index", F.astype(np.int32).ravel())
body_me.polygons.add(len(F))
body_me.polygons.foreach_set("loop_start", np.arange(0, F.size, 4, dtype=np.int32))
body_me.update(calc_edges=True)
body_me.validate()
if DETAIL != "hero":
    tmp = bpy.data.objects.new("_dec", body_me)
    col.objects.link(tmp)
    dm = tmp.modifiers.new("Dec", "DECIMATE")
    dm.ratio = min(1.0, GAME_TRIS / (2 * len(body_me.polygons)))
    dm.use_collapse_triangulate = True
    dg = bpy.context.evaluated_depsgraph_get()
    dec = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.meshes.remove(body_me)
    body_me = dec
    body_me.name = PREFIX + "Body"
for p in body_me.polygons:
    p.use_smooth = True
n_body = len(body_me.vertices)


# ---------------------------------------------------------------- rigid extras: teeth, claws, eyes
bm = bmesh.new()
bm.from_mesh(body_me)
extra_bone = {}
TOOTH_SEGS = 7 if DETAIL == "hero" else 4


def horn(base, direction, length, radius, bone, bend=Vector((0, 0, 0)), flat=1.0, mat=2, rings=None, segs=None):
    """A curved cone (tooth, claw): rings along a quadratic curve, laterally flattened by `flat`."""
    rings = rings or (5 if DETAIL == "hero" else 2)
    segs = segs or TOOTH_SEGS
    d = direction.normalized()
    side = d.cross(Vector((0, 0, 1)))
    if side.length < 1e-3:
        side = d.cross(Vector((1, 0, 0)))
    side.normalize()
    up = side.cross(d).normalized()
    prev = None
    for i in range(rings + 1):
        t = i / rings
        c = base + d * length * t + bend * length * t * t
        tan = (d * length + bend * length * 2 * t).normalized()
        sd_ = tan.cross(up).normalized()
        u_ = sd_.cross(tan).normalized()
        rr = radius * (1 - t) ** 0.9
        if i == rings:
            tip = bm.verts.new(c)
            extra_bone[tip] = bone
            for j in range(segs):
                f = bm.faces.new((prev[j], prev[(j + 1) % segs], tip))
                f.material_index = mat
            break
        ring = []
        for j in range(segs):
            a = 2 * math.pi * j / segs
            v = bm.verts.new(c + (sd_ * math.cos(a) * flat + u_ * math.sin(a)) * rr)
            extra_bone[v] = bone
            ring.append(v)
        if prev is None:
            f = bm.faces.new(list(reversed(ring)))
            f.material_index = mat
        else:
            for j in range(segs):
                f = bm.faces.new((prev[j], prev[(j + 1) % segs], ring[(j + 1) % segs], ring[j]))
                f.material_index = mat
        prev = ring


def sphere(center, r, bone, mat):
    res = bmesh.ops.create_uvsphere(bm, u_segments=16 if DETAIL == "hero" else 10, v_segments=10 if DETAIL == "hero" else 6, radius=r)
    for v in res["verts"]:
        v.co += center
        extra_bone[v] = bone
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = mat
        f.smooth = True


def HV(x, z, y=0.0):
    return Vector(hp(x, z, y))


def jaw_w(x, upper):
    xs = [0.3, 0.7, 1.0, 1.3, 1.45]
    return float(np.interp(x, xs, [0.33, 0.24, 0.18, 0.12, 0.08] if upper else [0.26, 0.2, 0.15, 0.1, 0.07]))


# upper teeth: premaxillary incisors at the front, big maxillary daggers behind, shrinking toward the hinge
for i in range(13):
    x = 1.38 - i * 0.078
    L = 0.07 + 0.09 * math.sin(math.pi * min(1.0, (i + 1.5) / 11)) if i > 1 else 0.06
    L *= rng.uniform(0.85, 1.1)
    for s in (1, -1):
        w = jaw_w(x, True) * (0.8 if i > 1 else 0.55)
        base = HV(x, float(lip_z(x)) + 0.03, s * w)
        horn(base, Vector((0.05, -s * 0.12, -1)), L, L * 0.28, "Head", bend=Vector((-0.25, 0, 0)), flat=0.7)
# lower teeth sit inside the upper row (hidden when the mouth is shut)
for i in range(11):
    x = 1.3 - i * 0.085
    L = (0.06 + 0.06 * math.sin(math.pi * min(1.0, (i + 1) / 9))) * rng.uniform(0.85, 1.1)
    for s in (1, -1):
        w = jaw_w(x, False) * 0.72
        base = HV(x, float(lip_z(x)) - 0.03, s * w)
        horn(base, Vector((0.08, s * 0.05, 1)), L, L * 0.28, "Jaw", bend=Vector((-0.2, 0, 0)), flat=0.7)
# eyes, set in the orbits under the lacrimal horn
EYE_C = []
for s in (1, -1):
    c = HV(0.44, 0.1, s * 0.285)
    EYE_C.append(c)
    sphere(c, 0.05, "Head", 1)
# foot claws (digits II-IV and the dewclaw), hand claws
for sd, s in (("L", 1), ("R", -1)):
    for dy, reach in ((0.0, 0.6), (0.2, 0.46), (-0.19, 0.44)):
        dirv = Vector((1.0, s * dy / 0.55, 0.0)).normalized()
        tip = Vector((0.16, s * 0.62, 0.12)) + dirv * reach + Vector((0, 0, -0.07))
        horn(tip - dirv * 0.02, dirv + Vector((0, 0, -0.1)), 0.15, 0.04, "Toe." + sd, bend=Vector((0, 0, -0.6)), flat=0.75)
    horn(Vector((0.1, s * 0.49, 0.2)), Vector((0.4, 0, -1)), 0.07, 0.022, "Meta." + sd, bend=Vector((0.4, 0, 0)))
    for dy in (0.025, -0.025):
        horn(Vector((2.23, s * (0.57 + dy * 1.6), 1.975)), Vector((0.6, 0, -1)), 0.07, 0.016, "Fore." + sd,
             bend=Vector((-0.5, 0, 0)), flat=0.7)

bm.verts.index_update()
extra = {v.index: bone for v, bone in extra_bone.items()}
bm.to_mesh(body_me)
bm.free()
for p in body_me.polygons:
    if p.material_index == 1:
        p.use_smooth = True

# ---------------------------------------------------------------- colour: countershading, bands, face rust, mouth
co = np.empty(len(body_me.vertices) * 3, np.float32)
body_me.vertices.foreach_get("co", co)
P = co.reshape(-1, 3).astype(np.float64)
Nb = sdf.normals(OPS, P[:n_body], 0.03)


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def colours(P, N):
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    # "dorsal" from the normal, lifted on the head/neck so the throat stays pale but the face stays dark
    belly = smooth(0.05, -0.55, N[:, 2]) * smooth(3.9, 2.4, z)
    legs = smooth(1.9, 0.9, z) * (np.abs(y) > 0.3)
    flank = smooth(0.8, 0.1, N[:, 2]) * (1 - belly)
    c = C_BACK[None] * (1 - flank[:, None]) + C_FLANK[None] * flank[:, None]
    c = c * (1 - belly[:, None]) + C_BELLY[None] * belly[:, None]
    # dark bands across back and tail, broken by a wobble, fading down the flanks and toward the head
    wob = 0.35 * np.sin(z * 3.1 + y * 2.2) + 0.2 * np.sin(x * 1.7)
    band = 0.5 + 0.5 * np.sin(x * 4.2 + wob * 2.2 + np.abs(y) * 1.4)
    band = smooth(0.62, 0.9, band) * smooth(-0.1, 0.55, N[:, 2]) * (1 - belly) * smooth(3.0, 1.6, x)
    c = c * (1 - 0.85 * band[:, None]) + C_BAND[None] * 0.85 * band[:, None]
    # rust flush over the snout and around the eyes, pale lower jaw
    hx = x - H0[0]
    face = smooth(0.1, 0.5, hx) * smooth(-0.45, -0.1, z - H0[2]) * (1 - belly)
    c = c * (1 - 0.7 * face[:, None]) + C_RUST[None] * 0.7 * face[:, None]
    legs_dark = legs * 0.4
    c = c * (1 - legs_dark[:, None]) + C_BACK[None] * legs_dark[:, None]
    # mouth interior: within the carved parting slab
    lz = H0[2] + lip_z(np.clip(hx, 0, 1.5))
    inside = (hx > 0.28) & (np.abs(z - lz) < 0.045) & (np.abs(y) < np.interp(hx, [0.3, 1.0, 1.5], [0.3, 0.2, 0.1]))
    c[inside] = C_MOUTH
    return np.clip(c, 0, 1), inside


C, MOUTH_V = colours(P[:n_body], Nb)
r = np.random.default_rng(11)
C *= r.uniform(0.9, 1.1, (len(C), 1))
allc = np.tile(np.array((*C_KERATIN, 1.0)), (len(P), 1))
allc[:n_body, :3] = C
ca = body_me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
ca.data.foreach_set("color", allc.astype(np.float32).ravel())
body_me.color_attributes.active_color = ca
body_me.color_attributes.render_color_index = body_me.color_attributes.find("Col")
if DETAIL == "hero":
    # masks the hero shader wants: R = dorsal (bigger scales), G = mouth, B = belly; plus eye-local coords
    dorsal = smooth(-0.2, 0.7, Nb[:, 2])
    belly = smooth(0.05, -0.55, Nb[:, 2])
    m = np.zeros((len(P), 4), np.float32)
    m[:, 3] = 1
    m[:n_body, 0], m[:n_body, 1], m[:n_body, 2] = dorsal, MOUTH_V, belly
    da = body_me.color_attributes.new(PREFIX + "Detail", "FLOAT_COLOR", "POINT")
    da.data.foreach_set("color", m.ravel())
    ev = np.zeros((len(P), 3), np.float32)
    for s, c in zip((1, -1), EYE_C):
        fwd = Vector((0.55, s * 0.84, 0.0)).normalized()     # eyes look forward-outward
        lat = Vector((0, 0, 1)).cross(fwd).normalized()
        near = np.linalg.norm(P - np.array(c), axis=1) < 0.06
        q = P[near] - np.array(c)
        ev[near] = np.stack([q @ np.array(lat), q[:, 2], q @ np.array(fwd)], 1) / 0.05
    ea = body_me.attributes.new(PREFIX + "EyeUV", "FLOAT_VECTOR", "POINT")
    ea.data.foreach_set("vector", ev.ravel())

# ---------------------------------------------------------------- face -Y (Three +Z)
ROT = Matrix.Rotation(-math.pi / 2, 4, "Z")
body_me.transform(ROT)
K = {n: (ROT @ p, r_) for n, (p, r_) in K.items()}
LATERAL = ROT @ Vector((0, 1, 0))


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
body_me.materials.append(material(PREFIX + "Keratin", C_KERATIN, 0.4))
body = bpy.data.objects.new(PREFIX + "Body", body_me)
col.objects.link(body)


def Pk(n):
    return K[n][0]


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
    b.head, b.tail = Pk(h), Pk(t)
    b.align_roll(LATERAL)                # local Z = lateral: rotation about Z is pitch for every bone
    if parent:
        b.parent = eb[parent]
        b.use_connect = (eb[parent].tail - b.head).length < 1e-4
    eb[name] = b
bpy.ops.object.mode_set(mode="OBJECT")
arm["run_speed"] = RUN_SPEED
arm["run_period"] = RUN_PERIOD
arm["kind"] = KIND
arm["scale"] = S
arm["knots"] = json.dumps({n: [round(p.x, 4), round(p.z, 4), round(-p.y, 4), round(max(r_), 4)] for n, (p, r_) in K.items()})

# ---------------------------------------------------------------- skin weights (vectorised capsule distance)
body_me.vertices.foreach_get("co", co)
Pw = co.reshape(-1, 3).astype(np.float64)
names = [b[0] for b in BONES]
A = np.array([Pk(h) for _, h, _, _ in BONES])
B = np.array([Pk(t) for _, _, t, _ in BONES])
Rw = np.array([WEIGHT_R[n] for n in names])
Q = Pw[:n_body, None, :]
AB = (B - A)[None]
t = np.clip(((Q - A[None]) * AB).sum(-1) / (AB * AB).sum(-1), 0, 1)
dist = np.linalg.norm(Q - (A[None] + AB * t[..., None]), axis=-1)
score = np.maximum(dist / Rw[None], 1e-3) ** -SKIN_SHARP
# sidedness: .L bones only move the +X (rest-frame left) side, and never the belly midline above the knees
lat = Pw[:n_body, 0]                  # after ROT, authored +Y (left) is +X
for j, n in enumerate(names):
    if n.endswith((".L", ".R")):
        sgn = 1 if n.endswith(".L") else -1
        high = smooth(1.6, 2.1, Pw[:n_body, 2])
        score[:, j] *= 1 - high * (1 - smooth(0.12, 0.4, sgn * lat))
        score[:, j] *= smooth(-0.05, 0.1, sgn * lat)
# jaw vs skull: explicit split along the parting line (capsules can't tell a lip from a palate)
hx = -Pw[:n_body, 1] - H0[0]          # authored x = -world y after ROT
hz = Pw[:n_body, 2] - H0[2]
headzone = smooth(-0.15, 0.1, hx)
below = smooth(0.02, -0.03, hz - lip_z(np.clip(hx, 0, 1.5))) * smooth(-0.05, 0.25, hx) * smooth(0.0, -0.08, hz + 0.18)
jh = names.index("Head"), names.index("Jaw")
hs = score[:, jh[0]] + score[:, jh[1]]
score[:, jh[1]] = score[:, jh[1]] * (1 - headzone) + hs * headzone * below
score[:, jh[0]] = score[:, jh[0]] * (1 - headzone) + hs * headzone * (1 - below)
order = np.argsort(-score, axis=1)[:, :4]
top = np.take_along_axis(score, order, 1)
top /= top.sum(1, keepdims=True)
top[top < 0.02] = 0
top /= top.sum(1, keepdims=True)
for n in names:
    body.vertex_groups.new(name=n)
vg = {g.name: g for g in body.vertex_groups}
q = np.round(top * 255).astype(int)
for j, n in enumerate(names):                # batch by quantised weight: ~22*255 calls instead of 4 per vertex
    for k_ in range(4):
        sel = order[:, k_] == j
        for wq in np.unique(q[sel, k_]):
            if wq == 0:
                continue
            ids = np.nonzero(sel & (q[:, k_] == wq))[0].tolist()
            vg[n].add(ids, wq / 255.0, "REPLACE")
by_bone = {}
for i, bone in extra.items():
    by_bone.setdefault(bone, []).append(i)
for bone, ids in by_bone.items():
    vg[bone].add(ids, 1.0, "REPLACE")
mod = body.modifiers.new("Armature", "ARMATURE")
mod.object = arm
body.parent = arm

# ---------------------------------------------------------------- clips (FK, in place)
pb = arm.pose.bones
for b in pb:
    b.rotation_mode = "XYZ"
arm.animation_data_create()


def keyclip(name, frames, fn):
    """fn(t in 0..1) -> {bone: (pitch, yaw, roll)} plus optional 'up'/'side' pelvis offsets (m)."""
    act = bpy.data.actions.new(PREFIX + name)
    act.use_fake_user = True
    arm.animation_data.action = act
    for i in range(frames + 1):
        pose = fn(i / frames)
        hp_ = pose.get("Head", (0, 0, 0))[0]
        if "Jaw" in pose:                     # clips author the jaw relative to the neck; it hangs off the head here
            j = pose["Jaw"]
            pose["Jaw"] = (j[0] - hp_, j[1], j[2])
        for b in pb:
            p, y, r_ = pose.get(b.name, (0, 0, 0))
            b.rotation_euler = Euler((y, r_, p), "XYZ")
            b.keyframe_insert("rotation_euler", frame=i, group=b.name)
        pb["Pelvis"].location = Vector((pose.get("up", 0.0), 0, pose.get("side", 0.0)))
        pb["Pelvis"].keyframe_insert("location", frame=i, group="Pelvis")
    return act


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def env(t, keys):
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * ease((t - t0) / max(t1 - t0, 1e-6))
    return keys[-1][1]


TAU = 2 * math.pi
TAILS = ("Tail1", "Tail2", "Tail3", "Tail4")


def run(t):
    ph = TAU * t
    o = {"up": 0.1 * math.cos(2 * ph), "Chest": (0.1, 0, 0), "Neck1": (-0.06, 0, 0), "Neck2": (-0.05 + 0.04 * math.sin(2 * ph), 0, 0),
         "Head": (0.05, 0, 0), "Jaw": (0.15, 0, 0)}
    for sd, off in (("L", 0.0), ("R", math.pi)):
        a = ph + off
        swing = max(0.0, math.cos(a))
        o["Thigh." + sd] = (-0.6 * math.sin(a) - 0.05, 0, 0)
        o["Shin." + sd] = (0.85 * swing ** 1.3 + 0.1, 0, 0)
        o["Meta." + sd] = (-0.65 * swing - 0.15 * math.sin(a), 0, 0)
        o["Toe." + sd] = (0.5 * swing + 0.25 * max(0, -math.sin(a)), 0, 0)
        o["Arm." + sd] = (-0.4, 0, 0)
        o["Fore." + sd] = (0.5, 0, 0)
    for k_, tb in enumerate(TAILS):
        o[tb] = (0.04 * math.sin(2 * ph - k_), 0.05 * (k_ + 1) * math.sin(ph - k_ * 0.6), 0)
    return o


def idle(t):
    ph = TAU * t
    look = 0.3 * math.sin(ph) * ease(abs(math.sin(ph)) * 1.4)
    o = {"up": 0.02 * math.sin(2 * ph), "Chest": (0.03 * math.sin(2 * ph), 0, 0),
         "Neck1": (-0.04, look * 0.4, 0), "Neck2": (0.04 * math.sin(2 * ph + 1), look * 0.6, 0), "Head": (0, look * 0.3, 0),
         "Jaw": (0.04 + 0.05 * max(0, math.sin(3 * ph)), 0, 0)}
    for sd in "LR":
        o["Arm." + sd] = (-0.25 + 0.04 * math.sin(ph), 0, 0)
        o["Fore." + sd] = (0.45, 0, 0)
    for k_, tb in enumerate(TAILS):
        o[tb] = (0.02 * math.sin(ph - k_), 0.06 * (k_ + 1) * math.sin(ph - k_ * 0.8), 0)
    return o


def attack(t):
    lunge = env(t, [(0, 0), (0.3, -0.25), (0.5, 1.0), (0.7, 0.8), (1, 0)])
    jaw = env(t, [(0, 0.05), (0.3, 0.35), (0.45, 1.0), (0.58, 0.0), (0.75, 0.1), (1, 0.05)])
    o = {"up": -0.19 * max(0, lunge), "Chest": (0.3 * lunge, 0, 0), "Neck1": (0.22 * lunge, 0, 0), "Neck2": (0.12 * lunge, 0, 0),
         "Head": (-0.1 * lunge - 0.2 * jaw, 0, 0), "Jaw": (0.15 + 0.75 * jaw, 0, 0)}
    for sd in "LR":
        o["Arm." + sd] = (-0.6 * max(0, lunge), 0, 0)
        o["Fore." + sd] = (0.3, 0, 0)
        o["Thigh." + sd] = (-0.15 * lunge * (1 if sd == "L" else 0.4), 0, 0)
        o["Shin." + sd] = (0.25 * max(0, lunge), 0, 0)
    for tb in TAILS:
        o[tb] = (-0.1 * lunge, 0, 0)
    return o


def roar(t):
    rise = env(t, [(0, 0), (0.25, 1), (0.8, 1), (1, 0)])
    jaw = env(t, [(0, 0), (0.25, 1.1), (0.8, 1.0), (1, 0)])
    shake = 0.05 * math.sin(t * 60) * rise
    o = {"up": 0.07 * rise, "Chest": (-0.15 * rise, 0, 0), "Neck1": (-0.35 * rise, shake, 0), "Neck2": (-0.2 * rise, shake, 0),
         "Head": (-0.15 * rise, 0, shake), "Jaw": (0.1 + 0.8 * jaw, 0, 0)}
    for sd, s in (("L", 1), ("R", -1)):
        o["Arm." + sd] = (-0.7 * rise, s * 0.2 * rise, 0)
        o["Fore." + sd] = (0.3, 0, 0)
    for k_, tb in enumerate(TAILS):
        o[tb] = (0.1 * rise, 0.05 * math.sin(t * 20 + k_) * rise, 0)
    return o


def death(t):
    fall = env(t, [(0, 0), (0.15, -0.1), (0.7, 1.0), (0.8, 0.96), (1, 1.0)])
    limp = env(t, [(0, 0), (0.5, 0.3), (1, 1)])
    hip_h = K["hip"][0].z
    o = {"up": -(hip_h - 0.62 * 1.1) * fall, "Pelvis": (0, 0, 1.45 * fall), "Chest": (0.1 * fall, 0, 0),
         "Neck1": (0.3 * limp, 0.2 * limp, 0), "Neck2": (0.4 * limp, 0.3 * limp, 0), "Head": (0.2 * limp, 0, 0),
         "Jaw": (0.2 + 0.4 * limp, 0, 0)}
    for sd in "LR":
        o["Thigh." + sd] = (-0.5 * fall * (1.2 if sd == "L" else 0.6), 0, 0)
        o["Shin." + sd] = (0.6 * limp, 0, 0)
        o["Meta." + sd] = (-0.4 * limp, 0, 0)
        o["Arm." + sd] = (-0.6 * limp, 0, 0)
    for k_, tb in enumerate(TAILS):
        o[tb] = (-0.1 * limp, 0.12 * limp * (k_ + 1) * 0.5, 0)
    return o


CLIPS = {"Idle": (2.4, idle), "Run": (RUN_PERIOD, run), "Attack": (0.7, attack), "Roar": (1.4, roar), "Death": (1.1, death)}
for n, (sec, fn) in CLIPS.items():
    keyclip(n, round(sec * FPS), fn)
arm.animation_data.action = bpy.data.actions[PREFIX + "Run"]
for b in pb:
    b.rotation_euler = Euler((0, 0, 0))
    b.location = Vector()
print("DINO", KIND, DETAIL, "verts", len(body_me.vertices), "tris", sum(len(p.vertices) - 2 for p in body_me.polygons),
      "bones", len(BONES))
