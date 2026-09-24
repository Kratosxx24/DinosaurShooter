"""Forest house: an Ex Machina-style retreat — concrete slabs, glass curtain walls, timber, a green roof,
a boulder breaking through the glass — hidden in misty rainforest over a stream. Sun shafts through
the canopy, warm interior light, swaying leaves, flowing water.

    blender -b --factory-startup --python renders/forest_house.py -- out.png [--preview]
    blender -b --factory-startup --python renders/forest_house.py -- <frames_dir> --res 1280x720 --fly 288
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
import _flora as fl
import random
from mathutils import noise

SEED = 5
EXT = 80.0                 # terrain half-extent (m)
GRID = 260
WATER_Z = -0.95
HOUSE = Vector((8.0, 10.5, 0.0))      # centre of the house footprint
HOUSE_W, HOUSE_D = 18.0, 9.0           # along x, along y
FLOOR = 0.9                            # finished floor level
CEIL = 4.2
# camera path (the still uses the end pose); ferns are cleared from a corridor around it
CAM_A, CAM_B = Vector((-26.0, -22.0, 1.2)), Vector((-10.5, -8.5, 2.0))
LOOK_A, LOOK_B = Vector((4.0, 10.0, 5.0)), Vector((7.0, 9.0, 2.6))
a = start()
scene = bpy.context.scene
rng = random.Random(SEED)
_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
FLY = int(_argv[_argv.index("--fly") + 1]) if "--fly" in _argv else 0
GAME = "--game" in _argv          # lighter plants for the real-time export (tools/export_forest_game.py)
if GAME:
    fl.WOOD_RES = 0


def stream_y(x):
    return 5.5 * math.sin(x / 26.0) - 1.5 * math.sin(x / 9.0 + 0.7)


def smooth(e0, e1, v):
    t = min(max((v - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def seg_dist(p, a_, b_):
    ab = b_ - a_
    t = max(0.0, min(1.0, (p - a_).dot(ab) / ab.length_squared))
    return (p - (a_ + ab * t)).length


def ground_z(x, y):
    d = abs(y - stream_y(x))
    z = -1.9 * (1 - smooth(2.5, 8.0, d))                       # channel
    side = 1 if y > stream_y(x) else -1
    z += max(0.0, d - 8) * (0.09 if side > 0 else 0.06)          # valley walls, steeper on the house side
    z += 1.3 * noise.fractal(Vector((x / 22, y / 22, 0.5)), 0.55, 2.0, 5) * smooth(3, 10, d)
    z += 0.12 * noise.fractal(Vector((x / 2.5, y / 2.5, 3.1)), 0.6, 2.0, 3)
    # a level pad for the house
    hd = max(abs(x - HOUSE.x) - HOUSE_W / 2, abs(y - HOUSE.y) - HOUSE_D / 2, 0)
    z = z * smooth(0, 5, hd) + (FLOOR - 1.4) * (1 - smooth(0, 5, hd))
    return z


def in_view(p, half=math.radians(30)):
    """1 inside the camera's view wedge (anywhere along the move) and nearer than what it looks at."""
    best = 0.0
    for k in range(6):
        u = k / 5
        c = CAM_A.lerp(CAM_B, u).to_2d()
        tgt = LOOK_A.lerp(LOOK_B, u).to_2d()
        v, w_ = p.to_2d() - c, tgt - c
        if v.length < 0.5:
            return 1.0
        ang = v.angle(w_, 0)
        if v.length < w_.length - 2:
            best = max(best, 1 - smooth(half * 0.8, half * 1.15, ang))
    return best


# ---------------------------------------------------------------- terrain + masks
xs = [(-EXT + 2 * EXT * i / (GRID - 1)) for i in range(GRID)]
y0_ = HOUSE.y - HOUSE_D / 2
verts, tree_m, fern_m, rock_m = [], [], [], []
for y in xs:
    for x in xs:
        z = ground_z(x, y)
        verts.append((x, y, z))
        d = abs(y - stream_y(x))
        p = Vector((x, y, 0))
        hd = max(abs(x - HOUSE.x) - HOUSE_W / 2, abs(y - HOUSE.y) - HOUSE_D / 2, 0)
        path = seg_dist(p, CAM_A.to_2d().to_3d(), CAM_B.to_2d().to_3d())
        view = seg_dist(p, CAM_B.to_2d().to_3d(), Vector((HOUSE.x, HOUSE.y - 3, 0)))   # keep the sightline open
        front = max(0.0, (y0_ - y)) if abs(x - HOUSE.x) < HOUSE_W / 2 + 4 else 0.0
        clear_house = smooth(2.0, 7.0, hd) * (1 if front <= 0 else smooth(9, 12, front))
        inside = smooth(0.6, 2.0, hd)            # nothing grows through the floor
        tree_m.append(smooth(7, 11, d) * clear_house * smooth(3, 8, path) * smooth(7, 13, view) * (1 - in_view(p)))
        fern_m.append(smooth(3.2, 4.5, d) * inside * smooth(0.35, 1.5, path) *
                      (0.55 + 0.45 * noise.noise(Vector((x / 6, y / 6, 9)))))
        rock_m.append(smooth(1.5, 3.0, d) * (1 - smooth(4.5, 7, d)) * inside * smooth(0.8, 1.8, path))
faces = [(j * GRID + i, j * GRID + i + 1, (j + 1) * GRID + i + 1, (j + 1) * GRID + i)
         for j in range(GRID - 1) for i in range(GRID - 1)]
tme = bpy.data.meshes.new("Terrain")
tme.from_pydata(verts, [], faces)
for poly in tme.polygons:
    poly.use_smooth = True
for nm, vals in (("tree_mask", tree_m), ("fern_mask", fern_m), ("rock_mask", rock_m)):
    at = tme.attributes.new(nm, "FLOAT", "POINT")
    at.data.foreach_set("value", vals)
terrain = link(bpy.data.objects.new("Terrain", tme))
assign(terrain, fl.mossy_material("M_ForestFloor", base=(0.07, 0.045, 0.025), moss=(0.04, 0.09, 0.015),
                                  moss_from=0.05, scale=0.6))

# ---------------------------------------------------------------- water
water = mat("M_Stream", (0.8, 0.85, 0.8), 0.02, **{"Transmission Weight": 1.0, "IOR": 1.33})
wn = water.node_tree
vol = wn.nodes.new("ShaderNodeVolumeAbsorption")
vol.inputs["Color"].default_value = (0.35, 0.45, 0.25, 1)
vol.inputs["Density"].default_value = 1.2
wn.links.new(vol.outputs[0], next(n for n in wn.nodes if n.type == "OUTPUT_MATERIAL").inputs["Volume"])
wtc = wn.nodes.new("ShaderNodeTexCoord")
wmap = wn.nodes.new("ShaderNodeMapping")
wmap.name = "Flow"
wmap.inputs["Scale"].default_value = (0.35, 1.2, 1.0)        # ripples stretched along the flow (x)
wn.links.new(wtc.outputs["Object"], wmap.inputs["Vector"])
rip = wn.nodes.new("ShaderNodeTexNoise")
rip.name = "Ripple"
rip.noise_dimensions = "4D"
rip.inputs["Scale"].default_value = 3.0
rip.inputs["Detail"].default_value = 6
wn.links.new(wmap.outputs["Vector"], rip.inputs["Vector"])
wb = wn.nodes.new("ShaderNodeBump")
wb.inputs["Strength"].default_value = 0.18
wn.links.new(rip.outputs["Fac"], wb.inputs["Height"])
wn.links.new(wb.outputs["Normal"], bsdf(water).inputs["Normal"])
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, WATER_Z - 1.5))
wat = bpy.context.object
wat.name = "Stream"
wat.scale = (2 * EXT, 2 * EXT, 3.0)
assign(wat, water)

# ---------------------------------------------------------------- the house
concrete = fl.mossy_material("M_Concrete", base=(0.36, 0.35, 0.33), moss=(0.08, 0.12, 0.04), moss_from=0.62, scale=1.5)
timber = mat("M_Timber", (0.09, 0.05, 0.028), 0.55)
tt = timber.node_tree
tw = tt.nodes.new("ShaderNodeTexWave")
tw.bands_direction = "Z"
tw.inputs["Scale"].default_value = 1.2
tw.inputs["Distortion"].default_value = 6
tw.inputs["Detail"].default_value = 6
twr = tt.nodes.new("ShaderNodeValToRGB")
twr.color_ramp.elements[0].color = (0.045, 0.024, 0.013, 1)
twr.color_ramp.elements[1].color = (0.13, 0.075, 0.04, 1)
tt.links.new(tw.outputs["Fac"], twr.inputs["Fac"])
tt.links.new(twr.outputs["Color"], bsdf(timber).inputs["Base Color"])
floor_wood = mat("M_FloorWood", (0.25, 0.15, 0.08), 0.35, **{"Coat Weight": 0.3})
glass = mat("M_Glass", (1, 1, 1), 0.02, **{"Transmission Weight": 1.0, "IOR": 1.5})
steel = mat("M_Steel", (0.015, 0.015, 0.016), 0.35, metal=0.9)
fabric = mat("M_Sofa", (0.33, 0.3, 0.26), 0.9)
green_roof = fl.mossy_material("M_GreenRoof", base=(0.05, 0.08, 0.02), moss=(0.07, 0.16, 0.03), moss_from=-0.5, scale=3)


def box(name, center, size, m, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    o = bpy.context.object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    if bevel:
        b = o.modifiers.new("bevel", "BEVEL")
        b.width = bevel
        b.segments = 2
    assign(o, m)
    return o


hx, hy = HOUSE.x, HOUSE.y
x0, x1 = hx - HOUSE_W / 2, hx + HOUSE_W / 2
y0, y1 = hy - HOUSE_D / 2, hy + HOUSE_D / 2
box("Plinth", (hx, hy, FLOOR - 2.2), (HOUSE_W + 0.4, HOUSE_D + 0.4, 4.0), concrete, 0.02)
box("FloorFinish", (hx, hy, FLOOR - 0.02), (HOUSE_W - 0.3, HOUSE_D - 0.3, 0.04), floor_wood)
box("Roof", (hx - 0.5, hy - 0.6, CEIL + 0.25), (HOUSE_W + 3.0, HOUSE_D + 3.2, 0.5), concrete, 0.02)
box("RoofGarden", (hx - 0.5, hy - 0.6, CEIL + 0.52), (HOUSE_W + 2.6, HOUSE_D + 2.8, 0.06), green_roof)
# back wall: concrete core with timber slats outside
box("BackWall", (hx, y1 - 0.2, (FLOOR + CEIL) / 2), (HOUSE_W, 0.4, CEIL - FLOOR), concrete)
for i in range(int(HOUSE_W / 0.14)):
    box(f"Slat{i}", (x0 + 0.07 + i * 0.14, y1 + 0.05, (FLOOR + CEIL) / 2), (0.09, 0.06, CEIL - FLOOR), timber)
# a stone side wall at the west end, glass everywhere else
box("StoneWall", (x0 + 0.25, hy + 1.2, (FLOOR + CEIL) / 2), (0.5, HOUSE_D - 2.4, CEIL - FLOOR), concrete)
# glass curtain walls with black mullions: front (stream side) and east end
H_GLASS = CEIL - FLOOR
box("GlassFront", (hx, y0 + 0.1, FLOOR + H_GLASS / 2), (HOUSE_W - 0.2, 0.02, H_GLASS), glass)
box("GlassEast", (x1 - 0.1, hy, FLOOR + H_GLASS / 2), (0.02, HOUSE_D - 0.4, H_GLASS), glass)
n_mull = int(HOUSE_W / 1.8)
for i in range(n_mull + 1):
    box(f"Mullion{i}", (x0 + i * HOUSE_W / n_mull, y0 + 0.1, FLOOR + H_GLASS / 2), (0.06, 0.1, H_GLASS), steel)
for i in range(5):
    box(f"MullionE{i}", (x1 - 0.1, y0 + 0.1 + i * (HOUSE_D - 0.4) / 4, FLOOR + H_GLASS / 2), (0.1, 0.06, H_GLASS), steel)
box("Transom", (hx, y0 + 0.1, CEIL - 0.03), (HOUSE_W, 0.12, 0.08), steel)
# cantilevered deck over the stream, glass balustrade
DX = hx + 3.5
box("Deck", (DX, y0 - 3.0, FLOOR - 0.2), (7.0, 6.0, 0.4), concrete, 0.02)
box("DeckTop", (DX, y0 - 3.0, FLOOR + 0.01), (6.8, 5.8, 0.02), timber)
box("RailGlass", (DX, y0 - 5.95, FLOOR + 0.55), (7.0, 0.02, 1.0), glass)
box("RailGlassS", (DX + 3.45, y0 - 3.0, FLOOR + 0.55), (0.02, 6.0, 1.0), glass)
# interior: sofa, table, pendant lamps, a warm ceiling wash
box("Sofa", (hx - 3.0, hy + 1.8, FLOOR + 0.25), (3.2, 1.0, 0.5), fabric, 0.06)
box("SofaBack", (hx - 3.0, hy + 2.3, FLOOR + 0.55), (3.2, 0.25, 0.6), fabric, 0.06)
box("Table", (hx + 2.5, hy + 0.5, FLOOR + 0.75), (3.0, 1.1, 0.06), timber, 0.01)
for lx in (-0.8, 0.8):
    box(f"TableLeg{lx}", (hx + 2.5 + lx, hy + 0.5, FLOOR + 0.37), (0.08, 0.9, 0.72), steel)
lamp = emission_mat("M_Lamp", (1.0, 0.62, 0.3), 25)
for i, lx in enumerate((-0.9, 0.0, 0.9)):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.14, location=(hx + 2.5 + lx, hy + 0.5, FLOOR + 1.9))
    assign(bpy.context.object, lamp)
    light("POINT", (hx + 2.5 + lx, hy + 0.5, FLOOR + 1.85), 60, (1.0, 0.62, 0.3), size=0.14, name=f"Pendant{i}")
wash = light("AREA", (hx, hy + 1.0, CEIL - 0.1), 600, (1.0, 0.7, 0.42), size=1, target=(hx, hy + 1.0, FLOOR), name="CeilingWash")
wash.data.shape = "RECTANGLE"
wash.data.size, wash.data.size_y = HOUSE_W - 2, HOUSE_D - 3
light("AREA", (hx, y1 - 0.6, FLOOR + 2.8), 250, (1.0, 0.68, 0.4), size=HOUSE_W * 0.8, target=(hx, y1 - 0.1, FLOOR + 1.5), name="SlatGrazer")

# the boulder that the house was built around: through the glass at the front-west corner
boulder = fl.rock("Boulder", seed=77, size=2.6, mat=fl.mossy_material("M_Boulder", base=(0.2, 0.2, 0.19),
                                                                     moss=(0.05, 0.13, 0.02), moss_from=0.1, scale=1.2), squash=0.75)
bo = bpy.data.objects.new("BoulderInst", None)
bo.instance_type = "COLLECTION"
bo.instance_collection = boulder
bo.location = (x0 + 3.2, y0 + 0.3, FLOOR + 0.4)
bo.rotation_euler = (0.1, 0.05, 0.7)
link(bo)

# ---------------------------------------------------------------- rainforest
leaf_big = fl.leaf_mesh("LeafBig", length=0.62, width=0.26, fold=0.3)
leaf_small = fl.leaf_mesh("LeafSmall", length=0.4, width=0.16, fold=0.2)
bark = fl.mossy_material("M_Bark", base=(0.12, 0.1, 0.08), moss=(0.06, 0.13, 0.02), moss_from=-0.1, scale=3)
canopy = fl.leaf_material("M_Canopy")
canopy2 = fl.leaf_material("M_Canopy2", greens=((0.05, 0.14, 0.02), (0.14, 0.26, 0.03), (0.26, 0.3, 0.05)))
understory = fl.leaf_material("M_Understory", greens=((0.02, 0.08, 0.01), (0.05, 0.16, 0.02), (0.1, 0.2, 0.02)), translucency=0.45)
lpt = 9 if GAME else (30 if a.preview else 48)
trees = [fl.broadleaf_tree(f"Tree{i}", seed=SEED * 10 + i, height=rng.uniform(15, 26), bark=bark,
                           leaf=(canopy, canopy2)[i % 2], leaf_obj=(leaf_big, leaf_small)[i % 2], leaves_per_twig=lpt)
         for i in range(6)]
palms = [fl.palm(f"Palm{i}", seed=SEED * 20 + i, height=rng.uniform(7, 12), bark=bark, leaf=canopy2) for i in range(3)]
small = [fl.broadleaf_tree(f"Sapling{i}", seed=SEED * 30 + i, height=rng.uniform(4, 7), bark=bark, leaf=understory,
                           leaf_obj=leaf_big, leaves_per_twig=lpt, buttress=False, crown=0.8) for i in range(3)]
ferns = [fl.fern(f"Fern{i}", seed=SEED * 40 + i, size=rng.uniform(0.8, 1.4), leaf=understory) for i in range(4)]
rocks = [fl.rock(f"Rock{i}", seed=SEED * 50 + i, size=rng.uniform(0.4, 1.1),
                 mat=fl.mossy_material(f"M_Rock{i}", base=(0.16, 0.16, 0.15), moss_from=0.0)) for i in range(4)]
fl.scatter(terrain, trees, 0.016, 1, mask="tree_mask", scale=(0.75, 1.25), name="Canopy", sink=0.3)
fl.scatter(terrain, palms + small, 0.025 if GAME else 0.05, 2, mask="tree_mask", scale=(0.8, 1.2), name="MidStorey", sink=0.2)
fl.scatter(terrain, ferns, 0.3 if GAME else (0.35 if a.preview else 0.8), 3, mask="fern_mask", scale=(0.7, 1.9), name="Ferns", tilt=0.2)
fl.scatter(terrain, rocks, 0.05, 4, mask="rock_mask", scale=(0.5, 1.6), name="StreamRocks", tilt=0.5, sink=0.25)

# ---------------------------------------------------------------- light, sky, mist
w = world_color((0.55, 0.7, 0.8), 0.9)
sun = light("SUN", (0, 0, 50), 7.0, (1.0, 0.88, 0.7), size=math.radians(0.6), name="Sun")
sun.rotation_euler = Vector((0.55, 0.9, 0.62)).to_track_quat("Z", "Y").to_euler()
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 12))
mist = bpy.context.object
mist.name = "Mist"
mist.scale = (2 * EXT, 2 * EXT, 30)
mm = bpy.data.materials.new("M_Mist")
mm.use_nodes = True
mn = mm.node_tree
for n in list(mn.nodes):
    mn.nodes.remove(n)
pv = mn.nodes.new("ShaderNodeVolumePrincipled")
pv.inputs["Anisotropy"].default_value = 0.6
pv.inputs["Color"].default_value = (0.85, 0.92, 0.95, 1)
mtc = mn.nodes.new("ShaderNodeTexCoord")
msep = mn.nodes.new("ShaderNodeSeparateXYZ")
mn.links.new(mtc.outputs["Object"], msep.inputs[0])
fall = mn.nodes.new("ShaderNodeMapRange")
fall.inputs["From Min"].default_value = -0.5
fall.inputs["From Max"].default_value = 0.0
fall.inputs["To Min"].default_value = 0.01
fall.inputs["To Max"].default_value = 0.0015
mn.links.new(msep.outputs["Z"], fall.inputs["Value"])
mnz = mn.nodes.new("ShaderNodeTexNoise")
mnz.name = "MistNoise"
mnz.noise_dimensions = "4D"
mnz.inputs["Scale"].default_value = 6
mn.links.new(mtc.outputs["Object"], mnz.inputs["Vector"])
wisps = mn.nodes.new("ShaderNodeMapRange")
wisps.inputs["To Min"].default_value = 0.2
wisps.inputs["To Max"].default_value = 1.8
mn.links.new(mnz.outputs["Fac"], wisps.inputs["Value"])
dens = mn.nodes.new("ShaderNodeMath")
dens.operation = "MULTIPLY"
mn.links.new(fall.outputs["Result"], dens.inputs[0])
mn.links.new(wisps.outputs["Result"], dens.inputs[1])
mn.links.new(dens.outputs[0], pv.inputs["Density"])
mo = mn.nodes.new("ShaderNodeOutputMaterial")
mn.links.new(pv.outputs[0], mo.inputs["Volume"])
assign(mist, mm)

# ---------------------------------------------------------------- camera + per-frame motion
cam = camera(CAM_B, LOOK_B, lens=26, fstop=4.0, focus=(Vector((hx, y0, 2)) - CAM_B).length)


def ease(u):
    return u * u * (3 - 2 * u)


def animate(sc, *_):
    f = sc.frame_current
    u = ease((f - 1) / max(1, FLY - 1)) if FLY else 1.0
    pos = CAM_A.lerp(CAM_B, u)
    pos.z = max(pos.z, ground_z(pos.x, pos.y) + 1.3) + 0.12 * math.sin(f / 23.0)   # ride the terrain, slight float
    look = LOOK_A.lerp(LOOK_B, u)
    cam.location = pos
    cam.rotation_euler = (look - pos).to_track_quat("-Z", "Y").to_euler()
    cam.data.dof.focus_distance = (Vector((hx, y0, 2)) - pos).length
    t = f / 24.0
    wmap.inputs["Location"].default_value = (-0.9 * t, 0, 0)  # the stream flows toward -x
    rip.inputs["W"].default_value = 0.6 * t
    mnz.inputs["W"].default_value = 0.05 * t


animate(scene)
bpy.app.handlers.frame_change_pre.append(animate)
scene.cycles.volume_step_rate = 4.0 if a.preview else 2.0


def tune(s):
    s.cycles.volume_bounces = 1
    s.cycles.transparent_max_bounces = 16
    s.render.use_persistent_data = True       # keep the BVH between animation frames


if a.save:
    # a .blend can't keep the Python frame handler, so bake the move into the file: camera keyframes
    # (every 4th frame, the handler's own easing) and frame drivers for the water and mist
    bpy.app.handlers.frame_change_pre.remove(animate)
    SHOT = FLY or 288
    FLY = SHOT
    for f in list(range(1, SHOT + 1, 4)) + [SHOT]:
        scene.frame_set(f)
        animate(scene)
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
        cam.data.dof.keyframe_insert("focus_distance", frame=f)
    for sock, idx, expr in ((wmap.inputs["Location"], 0, "-0.9*frame/24"), (rip.inputs["W"], -1, "0.6*frame/24"),
                            (mnz.inputs["W"], -1, "0.05*frame/24")):
        fc = sock.driver_add("default_value", idx) if idx >= 0 else sock.driver_add("default_value")
        fc.driver.type = "SCRIPTED"
        fc.driver.expression = expr       # a simple expression: runs without enabling Python auto-exec
    scene.frame_start, scene.frame_end = 1, SHOT
    scene.render.fps = 24
    scene.frame_set(SHOT)
    for area_ob in (bpy.data.objects.get("Mist"),):
        area_ob.hide_viewport = True      # the mist box would hide everything in Solid view; it still renders
    finish(a, samples=512, look="AgX - Medium High Contrast", exposure=-0.1, bounces=10, extra=tune)
elif FLY:
    scene.frame_start, scene.frame_end = 1, FLY
    scene.render.use_overwrite = False
    scene.render.use_placeholder = True
    out_dir = a.out
    a.out = None
    finish(a, samples=96, look="AgX - Medium High Contrast", exposure=-0.1, bounces=8, extra=tune)
    scene.render.resolution_percentage = 100
    if "--frames" in _argv:
        for fr in map(int, _argv[_argv.index("--frames") + 1].split(",")):
            scene.frame_set(fr)
            scene.render.filepath = os.path.join(out_dir, f"forest_{fr:04d}.png")
            bpy.ops.render.render(write_still=True)
    else:
        scene.render.filepath = os.path.join(out_dir, "forest_")
        bpy.ops.render.render(animation=True)
else:
    finish(a, samples=512, look="AgX - Medium High Contrast", exposure=-0.1, bounces=10, extra=tune)
