"""Hunting rifle for Mist Hunt's first-person viewmodel: an AR-pattern carbine in black and FDE tan with a
variable-power scope in cantilever rings, a weapon light, an angled foregrip, a curved polymer magazine and a
bronze compensator. Budget: <= 12k tris.

Barrel along +Y (glTF -Z, the camera's forward), bore axis at z = LIFT so it stands on the floor.
Separate objects the game animates or reads: Rifle_Mag (reload), Rifle_Bolt (charging handle kick),
empties Rifle_Muzzle (flash + tracers) and Rifle_Sight (eye point behind the scope's ocular, for ADS).
Material names the game special-cases: *Dot (emissive illumination dot), *Glow (weapon light lens).

    python blender/build.py rifle         (from the repo root; writes assets/rifle_vN.glb)
"""
import bpy
import bmesh
import math
from mathutils import Vector, Matrix

COLLECTION = "Rifle"
PREFIX = "Rifle_"
BEVEL = 0.0025          # edge bevel on the machined parts (m): what catches the flashlight
BARREL_R = 0.0095
SEGS = 16               # round parts
LIFT = 0.21             # raise the whole rifle so the magazine base sits at z = 0 (the bore is then at z = LIFT)
TAN = (0.2, 0.15, 0.09)
BLACK = (0.018, 0.018, 0.02)
GUNMETAL = (0.06, 0.062, 0.066)
BRONZE = (0.4, 0.2, 0.075)
SIGHT_Z = 0.08          # scope axis above the bore
SCOPE_Y = 0.012         # turret saddle position along the scope


def purge_collection(name):
    c = bpy.data.collections.get(name)
    if not c:
        return
    for o in list(c.all_objects):
        d = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if d is not None and d.users == 0 and isinstance(d, bpy.types.Mesh):
            bpy.data.meshes.remove(d)
    bpy.data.collections.remove(c)
    for m in [m for m in bpy.data.materials if m.name.startswith(PREFIX) and m.users == 0]:
        bpy.data.materials.remove(m)


purge_collection(COLLECTION)
col = bpy.data.collections.new(COLLECTION)
bpy.context.scene.collection.children.link(col)


def material(name, color, rough, metal=0.0, emit=None, strength=0.0):
    m = bpy.data.materials.new(PREFIX + name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = strength
    return m


M_BLACK = material("Anodized", BLACK, 0.42, metal=0.6)
M_TAN = material("Cerakote", TAN, 0.62, metal=0.15)
M_METAL = material("Gunmetal", GUNMETAL, 0.3, metal=0.9)
M_RUBBER = material("Rubber", (0.012, 0.012, 0.012), 0.9)
M_BRONZE = material("Bronze", BRONZE, 0.32, metal=1.0)
M_COATED = material("Coated", (0.004, 0.012, 0.02), 0.06, metal=0.5)     # multicoated scope glass: dark, blue-green sheen
M_DOT = material("Dot", (0.02, 0.0, 0.0), 0.3, emit=(1.0, 0.05, 0.03), strength=25)
M_GLOW = material("Glow", (0.8, 0.8, 0.75), 0.1, emit=(1.0, 0.95, 0.82), strength=3)
MATS = [M_BLACK, M_TAN, M_METAL, M_RUBBER, M_BRONZE, M_COATED, M_DOT, M_GLOW]
MI = {m: i for i, m in enumerate(MATS)}

# every part goes into one of these bmeshes (one object each); parts carry a material index
parts = {n: bmesh.new() for n in ("Body", "Mag", "Bolt")}


def box(target, center, size, mat, rot=None):
    bm = parts[target]
    res = bmesh.ops.create_cube(bm, size=1.0)
    vs = res["verts"]
    bmesh.ops.scale(bm, vec=Vector(size), verts=vs)
    if rot:
        bmesh.ops.rotate(bm, cent=Vector(), matrix=rot, verts=vs)
    bmesh.ops.translate(bm, vec=Vector(center), verts=vs)
    for f in {f for v in vs for f in v.link_faces}:
        f.material_index = MI[mat]
    return vs


def axis_frame(axis):
    """(along, u, w) unit vectors: lathe profiles run along `along`, rings sweep the u-w plane."""
    X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    return {"Y": (Y, X, Z), "Z": (Z, X, Y), "X": (X, Y, Z)}[axis]


def lathe(target, profile, mat, origin=(0, 0, 0), axis="Y", segs=SEGS, cap_mats=(None, None), phase=0.0, caps=True):
    """Surface of revolution: profile is [(t, r), ...] along the axis from origin. Ends are capped
    (with cap_mats[i] if given, else mat) unless their radius is 0 or caps is False."""
    bm = parts[target]
    o = Vector(origin)
    along, u, w = axis_frame(axis)
    rings = []
    for t, r in profile:
        rings.append([bm.verts.new(o + along * t + u * (r * math.cos(phase + 2 * math.pi * i / segs))
                                   + w * (r * math.sin(phase + 2 * math.pi * i / segs))) for i in range(segs)])
    faces = []
    for A, B in zip(rings, rings[1:]):
        for i in range(segs):
            j = (i + 1) % segs
            f = bm.faces.new((A[i], A[j], B[j], B[i]))
            f.material_index = MI[mat]
    for ring, r, cm in ((rings[0], profile[0][1], cap_mats[0]), (rings[-1], profile[-1][1], cap_mats[1])):
        if r > 0 and caps:
            f = bm.faces.new(ring)
            f.material_index = MI[cm or mat]
    return rings


def collar(target, t0, t1, r_in, r_out, mat, origin=(0, 0, 0), axis="Y", segs=SEGS):
    """Hollow ring (a band around a round part, leaving what's inside it visible)."""
    return lathe(target, [(t0, r_in), (t0, r_out), (t1, r_out), (t1, r_in), (t0, r_in)], mat, origin, axis, segs, caps=False)


def tube(target, y0, y1, r, mat, z=0.0, x=0.0, segs=SEGS, r1=None):
    """Capped cylinder along +Y from y0 to y1 (optionally tapering to r1)."""
    return lathe(target, [(y0, r), (y1, r if r1 is None else r1)], mat, origin=(x, 0, z), segs=segs)


def knurl(target, origin, axis, t0, t1, r, n, mat, height=0.0022, width=0.0026):
    """n raised ridges around a round part (grip rings on turrets and the power ring)."""
    along, u, w = axis_frame(axis)
    o = Vector(origin)
    for i in range(n):
        a = 2 * math.pi * (i + 0.5) / n
        radial = u * math.cos(a) + w * math.sin(a)
        tang = along.cross(radial)
        c = o + along * ((t0 + t1) / 2) + radial * r
        m = Matrix((radial, along, tang)).transposed()       # local x = radial, y = along, z = tangential
        box(target, c, (height * 2, t1 - t0, width), mat, rot=m)


def rot_x(deg):
    return Matrix.Rotation(math.radians(deg), 3, "X")


# ---------------------------------------------------------------- receiver + rail
box("Body", (0, 0.03, 0.018), (0.032, 0.26, 0.045), M_BLACK)                 # upper receiver
box("Body", (0, 0.035, -0.022), (0.03, 0.17, 0.04), M_BLACK)                 # lower receiver
box("Body", (0, 0.07, -0.058), (0.028, 0.07, 0.035), M_BLACK)                # magwell
box("Body", (0, 0.072, -0.074), (0.032, 0.078, 0.007), M_BLACK)              # magwell flare
box("Body", (0.0162, 0.05, 0.02), (0.002, 0.06, 0.016), M_METAL)             # ejection port cover (right side)
box("Body", (0.0166, 0.048, 0.027), (0.0012, 0.04, 0.004), M_BRONZE)         # bolt carrier showing through the port
box("Body", (0.019, 0.01, 0.028), (0.007, 0.014, 0.014), M_BLACK)            # brass deflector
lathe("Body", [(-0.012, 0.0055), (0.012, 0.0055), (0.016, 0.0045)], M_METAL, origin=(0.018, 0, 0.024), segs=10)  # forward assist
box("Body", (-0.0165, 0.075, 0.0), (0.004, 0.012, 0.012), M_METAL)          # bolt release
for s in (1, -1):
    box("Body", (s * 0.0168, -0.01, -0.018), (0.003, 0.02, 0.006), M_METAL, rot=rot_x(-20))   # ambi safety lever
box("Body", (0.0165, 0.076, -0.036), (0.004, 0.011, 0.011), M_METAL)         # mag release
for i in range(46):                                                           # picatinny teeth, receiver to muzzle end
    y = -0.09 + i * 0.0105
    box("Body", (0, y, 0.043), (0.021, 0.0055, 0.004), M_BLACK)
box("Body", (0, 0.16, 0.0395), (0.016, 0.52, 0.004), M_BLACK)                # rail spine
box("Body", (0, 0.385, 0.051), (0.016, 0.03, 0.008), M_BLACK)               # folded flip-up front sight

# ---------------------------------------------------------------- handguard (octagonal, tan) + barrel + compensator
tube("Body", 0.16, 0.43, 0.029, M_TAN, segs=8)
lathe("Body", [(0.428, 0.0275), (0.438, 0.0275), (0.44, 0.024)], M_BLACK, segs=8)   # end cap
for k in range(5):                                                            # M-LOK slots: dark insets, sides and bottom
    y = 0.2 + k * 0.045
    for s in (1, -1):
        box("Body", (s * 0.0275, y, 0.0), (0.004, 0.028, 0.009), M_BLACK)
    if k != 3:
        box("Body", (0, y, -0.0275), (0.009, 0.028, 0.004), M_BLACK)
tube("Body", 0.43, 0.575, BARREL_R, M_METAL)
box("Body", (0, 0.45, 0.0125), (0.02, 0.018, 0.024), M_METAL)                # gas block
for s in (1, -1):
    box("Body", (s * 0.0101, 0.453, 0.012), (0.0012, 0.004, 0.004), M_BRONZE)   # gas block pins
lathe("Body", [(0.568, 0.011), (0.572, 0.0148), (0.632, 0.0148), (0.638, 0.0128), (0.641, 0.0128), (0.641, 0.006)],
      M_BRONZE, segs=12)                                                     # compensator
for k in range(3):
    y = 0.584 + k * 0.016
    for s in (1, -1):
        box("Body", (s * 0.0137, y, 0.003), (0.004, 0.008, 0.013), M_BLACK)   # side ports: dark cuts in the bronze
    box("Body", (0, y + 0.004, 0.0142), (0.006, 0.005, 0.002), M_BLACK)      # top vents (climb control)

# ---------------------------------------------------------------- weapon light at 3 o'clock, angled foregrip underneath
LIGHT = (0.037, 0, -0.004)
box("Body", (0.031, 0.38, -0.004), (0.012, 0.034, 0.014), M_BLACK)          # rail mount
lathe("Body", [(0.328, 0.0085), (0.336, 0.0098), (0.395, 0.0098), (0.405, 0.0135), (0.425, 0.0142), (0.428, 0.0136)],
      M_BLACK, origin=LIGHT, segs=14)
knurl("Body", LIGHT, "Y", 0.345, 0.385, 0.0098, 10, M_BLACK, height=0.0008, width=0.002)
lathe("Body", [(0.4282, 0.0118), (0.4288, 0.0118)], M_GLOW, origin=LIGHT, segs=14)   # lens
box("Body", (0, 0.315, -0.046), (0.022, 0.078, 0.022), M_RUBBER, rot=rot_x(-24))   # angled foregrip
box("Body", (0, 0.318, -0.033), (0.02, 0.07, 0.008), M_BLACK)                # its rail clamp

# ---------------------------------------------------------------- grip, trigger, guard
box("Body", (0, -0.02, -0.095), (0.026, 0.038, 0.1), M_RUBBER, rot=rot_x(-18))
for k in range(5):                                                            # ridges down the backstrap, in grip space
    p = rot_x(-18) @ Vector((0, -0.02, 0.03 - k * 0.015)) + Vector((0, -0.02, -0.095))
    box("Body", p, (0.024, 0.004, 0.006), M_RUBBER, rot=rot_x(-18))
box("Body", (0, -0.005, -0.143), (0.028, 0.045, 0.012), M_RUBBER, rot=rot_x(-18))    # grip base flare
box("Body", (0, -0.022, -0.042), (0.026, 0.02, 0.01), M_BLACK)                       # beavertail
box("Body", (0, 0.035, -0.058), (0.005, 0.006, 0.026), M_BRONZE, rot=rot_x(12))      # trigger
box("Body", (0, 0.035, -0.078), (0.014, 0.07, 0.004), M_BLACK)                        # trigger guard bottom
box("Body", (0, 0.07, -0.063), (0.014, 0.004, 0.03), M_BLACK)                         # guard front post

# ---------------------------------------------------------------- stock: buffer tube, tan stock, rubber pad, cheek riser
tube("Body", -0.25, -0.1, 0.0155, M_BLACK)
lathe("Body", [(-0.106, 0.018), (-0.098, 0.018)], M_BLACK, segs=10)          # castle nut
box("Body", (0, -0.215, -0.012), (0.034, 0.12, 0.062), M_TAN)
box("Body", (0, -0.19, 0.026), (0.03, 0.1, 0.02), M_TAN)                     # cheek riser
box("Body", (0, -0.25, -0.03), (0.03, 0.04, 0.045), M_TAN, rot=rot_x(8))      # toe of the stock
box("Body", (0, -0.28, -0.012), (0.036, 0.014, 0.09), M_RUBBER)              # butt pad
for k in range(6):
    box("Body", (0, -0.2875, -0.048 + k * 0.0145), (0.034, 0.003, 0.005), M_RUBBER)   # pad ridges
box("Body", (0, -0.14, -0.03), (0.02, 0.035, 0.012), M_BLACK)                # stock latch
lathe("Body", [(0.0, 0.0065), (0.003, 0.0065)], M_BRONZE, origin=(0.017, -0.24, -0.02), axis="X", segs=10)  # QD sling cup
lathe("Body", [(-0.003, 0.0065), (0.0, 0.0065)], M_BRONZE, origin=(-0.017, -0.24, -0.02), axis="X", segs=10)

# ---------------------------------------------------------------- scope: 1-6x in a cantilever mount
Z = SIGHT_Z
box("Body", (0, 0.02, 0.05), (0.026, 0.11, 0.01), M_BLACK)                   # cantilever base on the rail
for y in (-0.025, 0.062):                                                    # rings
    box("Body", (0, y, Z - 0.017), (0.02, 0.013, 0.02), M_BLACK)
    lathe("Body", [(y - 0.0065, 0.0182), (y + 0.0065, 0.0182)], M_BLACK, origin=(0, 0, Z))
    for s in (1, -1):
        box("Body", (s * 0.0165, y, Z + 0.009), (0.006, 0.009, 0.006), M_METAL)   # ring cap screws
lathe("Body", [(-0.119, 0.0155), (-0.125, 0.0155), (-0.125, 0.0178), (-0.123, 0.0202), (-0.085, 0.0202),
               (-0.083, 0.0186), (-0.062, 0.0186), (-0.052, 0.0152), (0.08, 0.0152), (0.11, 0.0228),
               (0.15, 0.0228), (0.153, 0.0212), (0.153, 0.0192), (0.147, 0.0192)],
      M_BLACK, origin=(0, 0, Z), segs=20, cap_mats=(M_COATED, M_COATED))
knurl("Body", (0, 0, Z), "Y", -0.082, -0.064, 0.0186, 16, M_BLACK)          # magnification ring grip
box("Body", (0.021, -0.073, Z + 0.006), (0.012, 0.006, 0.006), M_BRONZE, rot=Matrix.Rotation(math.radians(-25), 3, "Y"))  # throw lever
collar("Body", -0.128, -0.121, 0.0165, 0.0206, M_RUBBER, origin=(0, 0, Z), segs=20)       # eyecup
collar("Body", 0.148, 0.155, 0.0198, 0.0233, M_BRONZE, origin=(0, 0, Z), segs=20)        # objective accent ring
box("Body", (0, SCOPE_Y, Z), (0.03, 0.036, 0.03), M_BLACK)                  # turret saddle
# elevation (top) and windage (right): black knobs, knurled, bronze cap rings
for axis, origin in (("Z", (0, SCOPE_Y, Z)), ("X", (0, SCOPE_Y, Z))):
    lathe("Body", [(0.014, 0.0115), (0.03, 0.0115), (0.031, 0.0105)], M_BLACK, origin=origin, axis=axis)
    knurl("Body", origin, axis, 0.018, 0.029, 0.0115, 14, M_BLACK, height=0.0012, width=0.0022)
    lathe("Body", [(0.031, 0.0108), (0.0335, 0.0108), (0.0345, 0.008)], M_BRONZE, origin=origin, axis=axis)
# illumination knob on the left, with the lit dot showing
lathe("Body", [(-0.014, 0.0125), (-0.027, 0.0125), (-0.028, 0.011)], M_BLACK, origin=(0, SCOPE_Y, Z), axis="X")
knurl("Body", (0, SCOPE_Y, Z), "X", -0.026, -0.017, 0.0125, 14, M_BLACK, height=0.0012, width=0.0022)
lathe("Body", [(-0.028, 0.0028), (-0.0288, 0.0028)], M_DOT, origin=(0, SCOPE_Y, Z), axis="X", segs=8)

# ---------------------------------------------------------------- charging handle (animated)
box("Bolt", (0, -0.095, 0.034), (0.012, 0.03, 0.008), M_BLACK)
box("Bolt", (0, -0.112, 0.034), (0.036, 0.008, 0.009), M_BLACK)               # T-latch
for s in (1, -1):
    box("Bolt", (s * 0.017, -0.112, 0.034), (0.004, 0.0085, 0.0095), M_BRONZE)   # latch tips

# ---------------------------------------------------------------- curved polymer magazine (animated): a rectangle lofted down an arc
MAG_TOP = Vector((0, 0.072, -0.045))
MAG_W, MAG_D, MAG_LEN, MAG_BEND = 0.024, 0.062, 0.17, math.radians(24)


def mag_loft(width, depth, f0=0.0, f1=1.0, n=10, mat=M_TAN):
    """Loft the mag cross-section along the arc from fraction f0 to f1 of its length."""
    bm = parts["Mag"]
    rings = []
    R = MAG_LEN / MAG_BEND
    for k in range(n + 1):
        a = MAG_BEND * (f0 + (f1 - f0) * k / n)
        # centre line: straight down, curving forward (toward +Y) along a circle of radius R
        c = MAG_TOP + Vector((0, R * (1 - math.cos(a)), -R * math.sin(a)))
        fwd = Vector((0, math.cos(a), math.sin(a)))          # across the mag, front-to-back direction
        ring = [bm.verts.new(c + Vector((sx * width / 2, 0, 0)) + fwd * (sy * depth / 2))
                for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        rings.append(ring)
    for A, B in zip(rings, rings[1:]):
        for i in range(4):
            f = bm.faces.new((A[i], A[(i + 1) % 4], B[(i + 1) % 4], B[i]))
            f.material_index = MI[mat]
    for ring in (rings[0], rings[-1]):
        f = bm.faces.new(ring)
        f.material_index = MI[mat]
    return rings


mag_loft(MAG_W, MAG_D)
mag_loft(MAG_W + 0.003, MAG_D + 0.003, 0.2, 0.24, n=1)                       # stop ridge below the magwell
mag_loft(MAG_W + 0.002, MAG_D * 0.7, 0.5, 0.82, n=4, mat=M_BLACK)           # texture panel on each side
# base plate: a slightly oversized block at the end of the arc, tilted with it
R = MAG_LEN / MAG_BEND
tip = MAG_TOP + Vector((0, R * (1 - math.cos(MAG_BEND)), -R * math.sin(MAG_BEND)))
box("Mag", tip + Vector((0, 0.006, -0.004)), (MAG_W + 0.006, MAG_D + 0.01, 0.012), M_BLACK, rot=rot_x(math.degrees(MAG_BEND)))


# ---------------------------------------------------------------- objects, bevels, empties
def make(name, bm, bevel=True):
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)       # parts are closed shells: point every face outward
    me = bpy.data.meshes.new(PREFIX + name)
    bm.to_mesh(me)
    bm.free()
    for m in MATS:
        me.materials.append(m)
    ob = bpy.data.objects.new(PREFIX + name, me)
    col.objects.link(ob)
    if bevel:
        b = ob.modifiers.new("bevel", "BEVEL")
        b.width = BEVEL
        b.segments = 1
        b.limit_method = "ANGLE"
        b.angle_limit = math.radians(40)
        b.harden_normals = True
        ob.modifiers.new("wn", "WEIGHTED_NORMAL").keep_sharp = True
    return ob


body = make("Body", parts["Body"])
mag = make("Mag", parts["Mag"])
bolt = make("Bolt", parts["Bolt"])
# the magazine pivots from the magwell for the reload: put its origin there
pivot = MAG_TOP.copy()
mag.data.transform(Matrix.Translation(-pivot))
mag.location = pivot
for name, loc in (("Muzzle", (0, 0.645, 0)), ("Sight", (0, -0.13, SIGHT_Z))):
    e = bpy.data.objects.new(PREFIX + name, None)
    e.empty_display_type = "PLAIN_AXES"
    e.empty_display_size = 0.02
    e.location = loc
    col.objects.link(e)

for o in col.objects:
    o.location.z += LIFT
dg = bpy.context.evaluated_depsgraph_get()
tris = sum(sum(len(p.vertices) - 2 for p in o.evaluated_get(dg).data.polygons) for o in (body, mag, bolt))
print("RIFLE tris", tris)
