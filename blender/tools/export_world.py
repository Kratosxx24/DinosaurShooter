"""Export the forest-house world for the game (assets/). Builds world/forest_house.py in --game mode in a
BACKGROUND Blender, then writes:

  world_v1.glb      terrain, house (every box, slats, glass), the boulder, all Y-up
  plants_v1.glb     one mesh per plant variant (P_Tree0.., P_Palm0.., P_Fern0.., P_Rock0.., P_Boulder),
                    branches + leaves realized into a single object at the origin
  instances_v1.json {variant: [16-float column-major Three.js matrices]} for every scattered plant

    python blender/build.py world         (from the repo root)
"""
import bpy
import json
import os
import runpy
import sys
from mathutils import Matrix, Vector

BLENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(BLENDER_DIR), "assets")
RADIUS = 58.0                     # keep plants within this distance of the house
VER = sys.argv[sys.argv.index("--ver") + 1] if "--ver" in sys.argv else "v1"
os.makedirs(OUT, exist_ok=True)

sys.argv = [sys.argv[0], "--", "--game"]
g = runpy.run_path(os.path.join(BLENDER_DIR, "world", "forest_house.py"))
scene = bpy.context.scene
house = g["HOUSE"]
# Blender Z-up -> Three.js Y-up: (x, y, z) -> (x, z, -y)
C = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
Ci = C.inverted()

# ---------------------------------------------------------------- which object stands for each plant
sources = bpy.data.collections["_FloraSources"]
variants = {}
for c in sources.children:
    if c.name.endswith("_Pick"):
        continue
    objs = list(c.objects)
    root = next((o for o in objs if o.name.endswith(("_Wood", "_Trunk"))), None) or objs[0]
    variants[root.name] = c
print("variants:", sorted(v.name for v in variants.values()))

# ---------------------------------------------------------------- instance transforms
dg = bpy.context.evaluated_depsgraph_get()
inst = {c.name: [] for c in variants.values()}
for oi in dg.object_instances:
    if not oi.is_instance or oi.object.name not in variants:
        continue
    m = oi.matrix_world.copy()
    if (m.translation.to_2d() - house.to_2d()).length > RADIUS:
        continue
    m3 = C @ m @ Ci
    inst[variants[oi.object.name].name].append([round(m3[r][c], 4) for c in range(4) for r in range(4)])
print("instances:", {k: len(v) for k, v in inst.items()})

# ---------------------------------------------------------------- one realized mesh per variant
exp_col = bpy.data.collections.new("_Export")
scene.collection.children.link(exp_col)


def realize(ob):
    """Evaluated mesh of ob with any geometry-node instances realized (leaves on their points)."""
    if ob.type == "MESH" and any(m.type == "NODES" for m in ob.modifiers):
        for m in ob.modifiers:
            if m.type == "NODES":
                tree = m.node_group
                outn = next(n for n in tree.nodes if n.type == "GROUP_OUTPUT")
                link = outn.inputs[0].links[0]
                if link.from_node.type != "REALIZE_INSTANCES":
                    rz = tree.nodes.new("GeometryNodeRealizeInstances")
                    tree.links.new(link.from_socket, rz.inputs[0])
                    tree.links.new(rz.outputs[0], outn.inputs[0])
    dgx = bpy.context.evaluated_depsgraph_get()
    return bpy.data.meshes.new_from_object(ob.evaluated_get(dgx), preserve_all_data_layers=False, depsgraph=dgx)


plant_objs = []
for c in variants.values():
    parts = []
    for o in c.objects:
        me = realize(o)
        po = bpy.data.objects.new(c.name + "_" + o.name, me)
        exp_col.objects.link(po)
        parts.append(po)
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    if len(parts) > 1:
        bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.name = "P_" + c.name           # P_ prefix: the source objects already own the bare names
    joined.data.name = "P_" + c.name
    plant_objs.append(joined)


def export(path, objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    kw = dict(filepath=path, export_format="GLB", use_selection=True, export_apply=True, export_yup=True,
              export_draco_mesh_compression_enable=False, export_lights=False, export_cameras=False)
    try:
        bpy.ops.export_scene.gltf(**kw)
    except TypeError:
        kw.pop("export_lights"); kw.pop("export_cameras")
        bpy.ops.export_scene.gltf(**kw)
    print("wrote", path, os.path.getsize(path) // 1024, "KB")


tris = {o.name: sum(len(p.vertices) - 2 for p in o.data.polygons) for o in plant_objs}
print("tris per variant:", tris)
print("total instanced tris:", sum(tris["P_" + k] * len(v) for k, v in inst.items()))
export(os.path.join(OUT, f"plants_{VER}.glb"), plant_objs)

# ---------------------------------------------------------------- the world: terrain, house, boulder
skip = {"Mist", "Stream", "Canopy", "MidStorey", "Ferns", "StreamRocks"}
world = [o for o in bpy.context.view_layer.objects          # excluded plant sources aren't in the view layer
         if o.type == "MESH" and o.name not in skip and exp_col not in o.users_collection]
export(os.path.join(OUT, f"world_{VER}.glb"), world)

meta = {"instances": inst, "water_y": g["WATER_Z"], "floor_y": g["FLOOR"],
        "spawn": list((C @ Vector((*g["CAM_B"].xy, 0))).xyz), "look": list((C @ g["LOOK_B"].to_4d()).xyz),
        "house": list((C @ house.to_4d()).xyz)}
with open(os.path.join(OUT, f"instances_{VER}.json"), "w") as f:
    json.dump(meta, f)
print("wrote instances", os.path.getsize(os.path.join(OUT, f"instances_{VER}.json")) // 1024, "KB")
