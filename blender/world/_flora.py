"""Procedural flora for render scenes: broadleaf trees, palms, ferns, mossy rocks, and a GN scatterer.

Every plant is built into its own collection (kept out of the view layer) so a scatter can instance it:
    trees = [broadleaf_tree(f"Tree{i}", seed=i, height=18) for i in range(5)]
    scatter(ground, trees, density=0.02, seed=1, mask="tree_mask", scale=(0.7, 1.3))
Leaves are real cut geometry (no alpha), instanced by geometry nodes onto points, and sway with the
scene time. Materials pick per-instance variation from Object Info > Random.
"""
import bpy
import bmesh
import math
import random
from mathutils import Vector, Matrix, noise

_HIDDEN = None
WOOD_RES = 3          # bevel resolution of every branch; the real-time export drops it to 0


def _hidden_parent():
    """A collection excluded from the view layer that holds every plant's source collection."""
    global _HIDDEN
    if _HIDDEN is None or _HIDDEN.name not in bpy.data.collections:
        _HIDDEN = bpy.data.collections.new("_FloraSources")
        bpy.context.scene.collection.children.link(_HIDDEN)
        lc = bpy.context.view_layer.layer_collection.children[_HIDDEN.name]
        lc.exclude = True
    return _HIDDEN


def _new_collection(name):
    c = bpy.data.collections.new(name)
    _hidden_parent().children.link(c)
    return c


def _socket(node, name, kind, out=False):
    """Pick a socket by name and type (Random Value etc. have one per data type; 5.x hides some from keys)."""
    socks = node.outputs if out else node.inputs
    hits = [s for s in socks if s.name == name and s.type == kind]
    return next((s for s in hits if s.enabled), hits[0])


# ---------------------------------------------------------------- materials
def leaf_material(name, greens=((0.03, 0.12, 0.015), (0.09, 0.22, 0.02), (0.16, 0.24, 0.03)), translucency=0.35):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    B = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    oi = nt.nodes.new("ShaderNodeObjectInfo")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.elements[0].color = (*greens[0], 1)
    cr.elements[1].color = (*greens[-1], 1)
    for i, g in enumerate(greens[1:-1]):
        cr.elements.new((i + 1) / (len(greens) - 1)).color = (*g, 1)
    nt.links.new(oi.outputs["Random"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], B.inputs["Base Color"])
    B.inputs["Roughness"].default_value = 0.45
    B.inputs["Specular IOR Level"].default_value = 0.35
    tr = nt.nodes.new("ShaderNodeBsdfTranslucent")
    lift = nt.nodes.new("ShaderNodeHueSaturation")
    lift.inputs["Saturation"].default_value = 1.3
    lift.inputs["Value"].default_value = 1.6
    nt.links.new(ramp.outputs["Color"], lift.inputs["Color"])
    nt.links.new(lift.outputs["Color"], tr.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs[0].default_value = translucency
    nt.links.new(B.outputs[0], mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return m


def mossy_material(name, base=(0.08, 0.06, 0.045), moss=(0.05, 0.12, 0.02), moss_from=0.35, scale=2.0):
    """Bark/stone with moss wherever the surface faces up (normal.z), broken up by noise."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    B = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    n1 = nt.nodes.new("ShaderNodeTexNoise")
    n1.inputs["Scale"].default_value = scale
    n1.inputs["Detail"].default_value = 10
    nt.links.new(tc.outputs["Object"], n1.inputs["Vector"])
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Normal"], sep.inputs[0])
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "MULTIPLY_ADD"
    add.inputs[1].default_value = 0.5
    nt.links.new(n1.outputs["Fac"], add.inputs[0])
    nt.links.new(sep.outputs["Z"], add.inputs[2])
    mm = nt.nodes.new("ShaderNodeMapRange")
    mm.inputs["From Min"].default_value = moss_from + 0.25
    mm.inputs["From Max"].default_value = moss_from + 0.4
    nt.links.new(add.outputs[0], mm.inputs["Value"])
    base_r = nt.nodes.new("ShaderNodeValToRGB")
    base_r.color_ramp.elements[0].color = (*[c * 0.4 for c in base], 1)
    base_r.color_ramp.elements[1].color = (*base, 1)
    nt.links.new(n1.outputs["Fac"], base_r.inputs["Fac"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["B"].default_value = (*moss, 1)
    nt.links.new(mm.outputs["Result"], mix.inputs["Factor"])
    nt.links.new(base_r.outputs["Color"], mix.inputs["A"])
    nt.links.new(mix.outputs["Result"], B.inputs["Base Color"])
    rough = nt.nodes.new("ShaderNodeMapRange")
    rough.inputs["To Min"].default_value = 0.55
    rough.inputs["To Max"].default_value = 0.95
    nt.links.new(n1.outputs["Fac"], rough.inputs["Value"])
    nt.links.new(rough.outputs["Result"], B.inputs["Roughness"])
    n2 = nt.nodes.new("ShaderNodeTexNoise")
    n2.inputs["Scale"].default_value = scale * 12
    n2.inputs["Detail"].default_value = 6
    nt.links.new(tc.outputs["Object"], n2.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.5
    nt.links.new(n2.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], B.inputs["Normal"])
    return m


# ---------------------------------------------------------------- leaf geometry
def leaf_mesh(name, length=0.12, width=0.05, fold=0.25, segments=4):
    """A single folded leaf along +X from the origin (its stalk end), lying in XY, midrib folded up."""
    bm = bmesh.new()
    S = segments
    rib = [bm.verts.new((length * i / S, 0, 0)) for i in range(S + 1)]
    for side in (1, -1):
        sv = [None] + [bm.verts.new((length * i / S, side * width * 0.5 * math.sin(math.pi * (i / S) ** 0.8),
                                     width * 0.5 * math.sin(math.pi * (i / S) ** 0.8) * fold)) for i in range(1, S)]
        faces = [(rib[0], rib[1], sv[1])]
        faces += [(rib[i], rib[i + 1], sv[i + 1], sv[i]) for i in range(1, S - 1)]
        faces.append((rib[S - 1], rib[S], sv[S - 1]))
        for f in faces:
            bm.faces.new(f if side > 0 else tuple(reversed(f)))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    return ob


# ---------------------------------------------------------------- instancing nodes
def _leaf_instancer(name, leaf_obj, mat, sway=0.25):
    """GN group: instance leaf_obj on every point, oriented by 'rot' and sized by 'scale', swaying in wind."""
    gn = bpy.data.node_groups.new(name, "GeometryNodeTree")
    gn.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    gn.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N = gn.nodes
    L = gn.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    info = N.new("GeometryNodeObjectInfo")
    info.inputs["Object"].default_value = leaf_obj
    rot = N.new("GeometryNodeInputNamedAttribute")
    rot.data_type = "FLOAT_VECTOR"
    rot.inputs["Name"].default_value = "rot"
    sc = N.new("GeometryNodeInputNamedAttribute")
    sc.data_type = "FLOAT"
    sc.inputs["Name"].default_value = "scale"
    # wind: noise of (position + time) added to the euler angles
    pos = N.new("GeometryNodeInputPosition")
    t = N.new("GeometryNodeInputSceneTime")
    tvec = N.new("ShaderNodeCombineXYZ")
    L.new(t.outputs["Seconds"], tvec.inputs["X"])
    L.new(t.outputs["Seconds"], tvec.inputs["Z"])
    p2 = N.new("ShaderNodeVectorMath")
    p2.operation = "MULTIPLY_ADD"
    p2.inputs[1].default_value = (0.35, 0.35, 0.35)
    L.new(pos.outputs[0], p2.inputs[0])
    L.new(tvec.outputs[0], p2.inputs[2])
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 1.0
    L.new(p2.outputs[0], nz.inputs["Vector"])
    cen = N.new("ShaderNodeVectorMath")
    cen.operation = "SUBTRACT"
    cen.inputs[1].default_value = (0.5, 0.5, 0.5)
    L.new(nz.outputs["Color"], cen.inputs[0])
    amp = N.new("ShaderNodeVectorMath")
    amp.operation = "SCALE"
    amp.inputs["Scale"].default_value = sway
    L.new(cen.outputs[0], amp.inputs[0])
    tot = N.new("ShaderNodeVectorMath")
    tot.operation = "ADD"
    L.new(rot.outputs["Attribute"], tot.inputs[0])
    L.new(amp.outputs[0], tot.inputs[1])
    iop = N.new("GeometryNodeInstanceOnPoints")
    L.new(gi.outputs[0], iop.inputs["Points"])
    L.new(info.outputs["Geometry"], iop.inputs["Instance"])
    try:
        e2r = N.new("FunctionNodeEulerToRotation")
        L.new(tot.outputs[0], e2r.inputs[0])
        L.new(e2r.outputs[0], iop.inputs["Rotation"])
    except RuntimeError:
        L.new(tot.outputs[0], iop.inputs["Rotation"])
    L.new(sc.outputs["Attribute"], iop.inputs["Scale"])
    setm = N.new("GeometryNodeSetMaterial")
    setm.inputs["Material"].default_value = mat
    L.new(iop.outputs[0], setm.inputs["Geometry"])
    L.new(setm.outputs[0], go.inputs[0])
    return gn


def _points_object(name, pts, rots, scales, col):
    me = bpy.data.meshes.new(name)
    me.from_pydata(pts, [], [])
    a = me.attributes.new("rot", "FLOAT_VECTOR", "POINT")
    a.data.foreach_set("vector", [c for r in rots for c in r])
    s = me.attributes.new("scale", "FLOAT", "POINT")
    s.data.foreach_set("value", scales)
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    return ob


def _branch_curve(name, splines, mat, col, resolution=None):
    """splines: list of [(point, radius), ...]. One curve object, bevelled round, tapering by point radius."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = 1.0
    cu.bevel_resolution = WOOD_RES if resolution is None else min(resolution, WOOD_RES)
    cu.use_fill_caps = True
    for pts in splines:
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for p, (co, r) in zip(sp.points, pts):
            p.co = (*co, 1)
            p.radius = r
    ob = bpy.data.objects.new(name, cu)
    ob.data.materials.append(mat)
    col.objects.link(ob)
    return ob


# ---------------------------------------------------------------- plants
def broadleaf_tree(name, seed, height=16.0, bark=None, leaf=None, leaf_obj=None, leaves_per_twig=26,
                   crown=0.55, buttress=True, lean=0.08):
    """A rainforest broadleaf: straight-ish trunk, optional buttress roots, 2-level branching into an
    umbrella crown, leaf clusters at every twig. Returns its collection (origin at the trunk base)."""
    rng = random.Random(seed)
    col = _new_collection(name)
    splines = []
    leaf_pts, leaf_rot, leaf_sc = [], [], []

    def grow(start, direction, length, r0, segs, bend):
        pts = []
        p = Vector(start)
        d = Vector(direction).normalized()
        for i in range(segs + 1):
            t = i / segs
            pts.append((p.copy(), r0 * (1 - 0.8 * t) + 0.004))
            wob = Vector((noise.noise(p * 0.4 + Vector((seed, 0, 0))), noise.noise(p * 0.4 + Vector((0, seed, 3))), 0))
            d = (d + wob * bend + Vector((0, 0, 0.04))).normalized()
            p = p + d * (length / segs)
        return pts

    base_dir = Vector((rng.uniform(-lean, lean), rng.uniform(-lean, lean), 1))
    trunk_r = height * 0.022
    trunk = grow((0, 0, -0.3), base_dir, height, trunk_r, 12, 0.08)
    splines.append(trunk)
    if buttress:
        for k in range(rng.randint(3, 5)):
            a = k / 4 * 2 * math.pi + rng.uniform(-0.4, 0.4)
            out = Vector((math.cos(a), math.sin(a), 0))
            splines.append([(Vector((0, 0, trunk_r * 5)), trunk_r * 0.5), (out * trunk_r * 2.2 + Vector((0, 0, trunk_r * 1.5)), trunk_r * 0.45),
                            (out * trunk_r * 4.5 + Vector((0, 0, -0.1)), trunk_r * 0.25)])
    top = trunk[-1][0]
    n_branch = rng.randint(5, 8)
    for b in range(n_branch):
        t = 1 - crown * (b / n_branch) * rng.uniform(0.8, 1.0)
        idx = int(t * (len(trunk) - 1))
        start = trunk[idx][0]
        az = b * 2.39996 + rng.uniform(-0.3, 0.3)
        up = rng.uniform(0.45, 0.9)
        d = Vector((math.cos(az), math.sin(az), up))
        L = height * rng.uniform(0.26, 0.38) * (1.15 - 0.3 * (idx / len(trunk)))
        br = grow(start, d, L, trunk[idx][1] * 0.55, 6, 0.25)
        splines.append(br)
        for s in range(rng.randint(4, 7)):
            j = rng.randint(2, len(br) - 1)
            sd = (Vector(d) + Vector((rng.gauss(0, 0.7), rng.gauss(0, 0.7), rng.uniform(0.1, 0.6)))).normalized()
            tw = grow(br[j][0], sd, L * rng.uniform(0.3, 0.5), br[j][1] * 0.6, 3, 0.35)
            splines.append(tw)
            # a leaf cluster around the twig's outer half
            end = tw[-1][0]
            mid = tw[len(tw) // 2][0]
            for _ in range(leaves_per_twig):
                u = rng.random()
                c = mid.lerp(end, u) + Vector((rng.gauss(0, 0.6), rng.gauss(0, 0.6), rng.gauss(0.0, 0.4))) * height * 0.05
                leaf_pts.append(c)
                leaf_rot.append((rng.uniform(-0.5, 0.5), rng.uniform(-0.9, 0.2), rng.uniform(0, 2 * math.pi)))
                leaf_sc.append(rng.uniform(0.7, 1.3))
    _branch_curve(name + "_Wood", splines, bark, col)
    pts = _points_object(name + "_Leaves", leaf_pts, leaf_rot, leaf_sc, col)
    pts.modifiers.new("leaves", "NODES").node_group = _leaf_instancer(name + "_GN", leaf_obj, leaf)
    return col


def palm(name, seed, height=11.0, bark=None, leaf=None, fronds=14):
    """A curved-trunk palm with a crown of long arching pinnate fronds (real leaflet geometry)."""
    rng = random.Random(seed)
    col = _new_collection(name)
    lean = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0)).normalized() * rng.uniform(0.04, 0.14)
    trunk = []
    for i in range(16):
        t = i / 15
        p = Vector((0, 0, 0)) + lean * height * t * t + Vector((0, 0, height * t))
        trunk.append((p, 0.2 * (1 - 0.35 * t) + 0.03 * math.sin(i * 2.7) ** 2))
    _branch_curve(name + "_Trunk", [trunk], bark, col, resolution=4 if WOOD_RES >= 3 else WOOD_RES)
    top = trunk[-1][0]
    bm = bmesh.new()
    for f in range(fronds):
        az = f * 2.39996
        droop = rng.uniform(0.2, 0.9)
        L = rng.uniform(3.0, 4.2)
        d = Vector((math.cos(az), math.sin(az), 0))
        side = Vector((-d.y, d.x, 0))
        prev = None
        for i in range(24):
            t = i / 23
            p = top + d * L * t + Vector((0, 0, L * (0.45 * t - droop * t * t)))
            if i % 1 == 0 and 0.05 < t < 0.97:
                ll = 0.75 * math.sin(math.pi * min(1, t * 1.15)) + 0.12
                for s in (1, -1):
                    tip = p + side * s * ll + d * 0.18 + Vector((0, 0, -0.25 * ll))
                    base_a = bm.verts.new(p)
                    base_b = bm.verts.new(p + d * 0.11)
                    t_v = bm.verts.new(tip)
                    bm.faces.new((base_a, base_b, t_v))
            prev = p
    me = bpy.data.meshes.new(name + "_Fronds")
    bm.to_mesh(me)
    bm.free()
    fo = bpy.data.objects.new(name + "_Fronds", me)
    fo.data.materials.append(leaf)
    col.objects.link(fo)
    return col


def fern(name, seed, size=1.0, leaf=None, fronds=11):
    """A ground fern: arching fronds of paired leaflets shrinking to the tip."""
    rng = random.Random(seed)
    col = _new_collection(name)
    bm = bmesh.new()
    for f in range(fronds):
        az = f * 2.39996 + rng.uniform(-0.2, 0.2)
        L = size * rng.uniform(0.8, 1.25)
        rise = rng.uniform(0.6, 1.0)
        d = Vector((math.cos(az), math.sin(az), 0))
        side = Vector((-d.y, d.x, 0))
        n = 18
        for i in range(n):
            t = i / (n - 1)
            p = d * L * t + Vector((0, 0, L * (rise * t - (rise + 0.35) * t * t)))
            nxt_t = (i + 1) / (n - 1)
            if 0.12 < t < 0.98:
                ll = L * 0.22 * math.sin(math.pi * (t - 0.1) / 0.9) + 0.01
                for s in (1, -1):
                    a = bm.verts.new(p)
                    b = bm.verts.new(p + d * L * 0.045)
                    c = bm.verts.new(p + side * s * ll + d * L * 0.03 + Vector((0, 0, -0.05 * ll)))
                    bm.faces.new((a, b, c))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(leaf)
    col.objects.link(ob)
    return col


def rock(name, seed, size=1.0, mat=None, squash=0.6, detail=4):
    rng = random.Random(seed)
    col = _new_collection(name)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=detail, radius=size)
    off = Vector((seed * 3.1, seed * 1.7, 0.3))
    for v in bm.verts:
        d = v.co.normalized()
        r = size * (1 + 0.25 * noise.fractal(d * 1.3 + off, 0.55, 2.0, 5) + 0.06 * noise.noise(d * 6 + off))
        p = d * r
        p.z *= squash
        v.co = p
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(mat)
    col.objects.link(ob)
    return col


# ---------------------------------------------------------------- scatter
def scatter(ground, collections, density, seed, mask=None, scale=(0.8, 1.2), name="Scatter", tilt=0.05, sink=0.0):
    """Instance a random pick of `collections` over `ground` (Poisson-free random distribute).
    mask: name of a float point attribute on the ground (0..1) multiplying the density."""
    parent = bpy.data.collections.new(name + "_Pick")
    _hidden_parent().children.link(parent)
    for c in collections:
        parent.children.link(c)
    me = ground.data.copy()
    ob = bpy.data.objects.new(name, me)
    ob.matrix_world = ground.matrix_world.copy()
    bpy.context.scene.collection.objects.link(ob)
    gn = bpy.data.node_groups.new(name + "_GN", "GeometryNodeTree")
    gn.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    gn.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = gn.nodes, gn.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    dist = N.new("GeometryNodeDistributePointsOnFaces")
    dist.distribute_method = "RANDOM"
    _socket(dist, "Density", "VALUE").default_value = density
    _socket(dist, "Seed", "INT").default_value = seed
    L.new(gi.outputs[0], dist.inputs["Mesh"])
    if mask:
        m = N.new("GeometryNodeInputNamedAttribute")
        m.data_type = "FLOAT"
        m.inputs["Name"].default_value = mask
        mul = N.new("ShaderNodeMath")          # Random mode: Density is itself a field (Density Factor is Poisson-only)
        mul.operation = "MULTIPLY"
        mul.inputs[1].default_value = density
        L.new(m.outputs["Attribute"], mul.inputs[0])
        L.new(mul.outputs[0], _socket(dist, "Density", "VALUE"))
    ci = N.new("GeometryNodeCollectionInfo")
    ci.inputs["Collection"].default_value = parent
    ci.inputs["Separate Children"].default_value = True
    ci.inputs["Reset Children"].default_value = True
    iop = N.new("GeometryNodeInstanceOnPoints")
    iop.inputs["Pick Instance"].default_value = True
    L.new(dist.outputs["Points"], iop.inputs["Points"])
    L.new(ci.outputs[0], iop.inputs["Instance"])
    ri = N.new("FunctionNodeRandomValue")
    ri.data_type = "INT"
    _socket(ri, "Min", "INT").default_value = 0
    _socket(ri, "Max", "INT").default_value = len(collections) - 1
    _socket(ri, "Seed", "INT").default_value = seed + 1
    L.new(_socket(ri, "Value", "INT", out=True), iop.inputs["Instance Index"])
    rr = N.new("FunctionNodeRandomValue")
    rr.data_type = "FLOAT_VECTOR"
    _socket(rr, "Min", "VECTOR").default_value = (-tilt, -tilt, 0)
    _socket(rr, "Max", "VECTOR").default_value = (tilt, tilt, 2 * math.pi)
    _socket(rr, "Seed", "INT").default_value = seed + 2
    try:
        e2r = N.new("FunctionNodeEulerToRotation")
        L.new(_socket(rr, "Value", "VECTOR", out=True), e2r.inputs[0])
        L.new(e2r.outputs[0], iop.inputs["Rotation"])
    except RuntimeError:
        L.new(_socket(rr, "Value", "VECTOR", out=True), iop.inputs["Rotation"])
    rs = N.new("FunctionNodeRandomValue")
    rs.data_type = "FLOAT"
    _socket(rs, "Min", "VALUE").default_value = scale[0]
    _socket(rs, "Max", "VALUE").default_value = scale[1]
    _socket(rs, "Seed", "INT").default_value = seed + 3
    L.new(_socket(rs, "Value", "VALUE", out=True), iop.inputs["Scale"])
    last = iop.outputs[0]
    if sink:
        tr = N.new("GeometryNodeTranslateInstances")
        tr.inputs["Translation"].default_value = (0, 0, -sink)
        L.new(last, tr.inputs["Instances"])
        last = tr.outputs[0]
    L.new(last, go.inputs[0])
    ob.modifiers.new("scatter", "NODES").node_group = gn
    return ob


def conifer(name, seed, height=12.0, bark=None, needles=None, tiers=9):
    """A spruce: a thin trunk under stacked, drooping, jagged needle tiers (low-poly, reads at distance).
    Give `needles` a material with snow on up-facing faces (mossy_material with a white 'moss')."""
    rng = random.Random(seed)
    col = _new_collection(name)
    trunk = [(Vector((0, 0, h)), 0.06 + 0.12 * (1 - h / height)) for h in (0, height * 0.5, height)]
    _branch_curve(name + "_Trunk", [trunk], bark, col)
    bm = bmesh.new()
    n = 14
    for k in range(tiers):
        t = k / tiers
        z0 = height * (0.12 + 0.86 * t)
        r = height * 0.28 * (1 - t) ** 1.1 + 0.15
        top = bm.verts.new((0, 0, z0 + height * 0.14))
        rim = []
        for i in range(n):
            a = 2 * math.pi * i / n + rng.uniform(-0.1, 0.1)
            rr = r * (1.0 if i % 2 == 0 else 0.72) * rng.uniform(0.85, 1.1)     # jagged star outline
            rim.append(bm.verts.new((rr * math.cos(a), rr * math.sin(a), z0 - r * 0.25 * rng.uniform(0.6, 1.2))))
        for i in range(n):
            bm.faces.new((top, rim[i], rim[(i + 1) % n]))
    me = bpy.data.meshes.new(name + "_Needles")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name + "_Needles", me)
    ob.data.materials.append(needles)
    col.objects.link(ob)
    return col
