"""
Anime Grass — driven by the tutorial normal map you provided.

Uses object-space normal mapping + Shader-to-RGB cel shading
(the hand-painted shadow trick from the video).

  blender --background --factory-startup --python anime-grass/build_anime_grass.py -- --stills-only
"""

from __future__ import annotations

import math
import random
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Euler

ROOT = Path(__file__).resolve().parent
BLEND_PATH = ROOT / "anime_grass.blend"
RENDER_DIR = ROOT / "renders"
NORMAL_PATH = ROOT / "textures" / "grass_normal.png"
MASK_NAME = "Grass"
WIND_ATTR = "wind"


def log(msg: str) -> None:
    print(msg, flush=True)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for coll in (bpy.data.node_groups, bpy.data.materials, bpy.data.meshes, bpy.data.images, bpy.data.lights, bpy.data.cameras):
        for block in list(coll):
            coll.remove(block)
    for block in list(bpy.data.collections):
        if block != bpy.context.scene.collection:
            try:
                bpy.data.collections.remove(block)
            except Exception:
                pass


def link(nt, a, b):
    nt.links.new(a, b)


def node(nt, bl_idname, loc=(0, 0), **kwargs):
    n = nt.nodes.new(bl_idname)
    n.location = loc
    for k, v in kwargs.items():
        if hasattr(n, k):
            setattr(n, k, v)
    return n


def add_socket(nt, name, in_out, socket_type, default=None, min_v=None, max_v=None):
    item = nt.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    if default is not None and hasattr(item, "default_value"):
        item.default_value = default
    if min_v is not None and hasattr(item, "min_value"):
        item.min_value = min_v
    if max_v is not None and hasattr(item, "max_value"):
        item.max_value = max_v
    return item


def set_mod_input(obj, mod_name, socket_name, value, frame=None):
    mod = obj.modifiers[mod_name]
    ng = mod.node_group
    for item in ng.interface.items_tree:
        if getattr(item, "name", None) == socket_name and getattr(item, "in_out", "") == "INPUT":
            mod[item.identifier] = value
            if frame is not None:
                obj.keyframe_insert(
                    data_path=f'modifiers["{mod_name}"]["{item.identifier}"]',
                    frame=frame,
                )
            return True
    return False


def load_normal_image() -> bpy.types.Image:
    if not NORMAL_PATH.exists():
        raise FileNotFoundError(f"Missing normal map: {NORMAL_PATH}")
    img = bpy.data.images.load(str(NORMAL_PATH))
    img.colorspace_settings.name = "Non-Color"
    img.name = "GrassNormal"
    return img


# ---------------------------------------------------------------------------
# Assets — solid low-poly clumps (~tutorial 16-tri spirit)
# ---------------------------------------------------------------------------

def make_clump(name: str, seed: int) -> bpy.types.Object:
    rng = random.Random(seed)
    verts = []
    faces = []
    # 4–5 wide tapered blades in a tuft
    for i in range(5):
        yaw = i * (math.tau / 5) + rng.uniform(-0.25, 0.25)
        h = rng.uniform(0.35, 0.55)
        w = rng.uniform(0.035, 0.055)
        lean = rng.uniform(0.02, 0.07)
        bend = rng.uniform(0.03, 0.09)
        cy, sy = math.cos(yaw), math.sin(yaw)
        local = [
            (-w, 0, 0),
            (w, 0, 0),
            (-w * 1.05, lean * 0.4, h * 0.4),
            (w * 1.05, lean * 0.4, h * 0.4),
            (-w * 0.45, lean * 0.8 + bend * 0.3, h * 0.75),
            (w * 0.45, lean * 0.8 + bend * 0.3, h * 0.75),
            (0.0, lean + bend, h),
        ]
        base = len(verts)
        for lx, ly, lz in local:
            verts.append((lx * cy - ly * sy, lx * sy + ly * cy, lz))
        faces += [
            (base, base + 1, base + 3, base + 2),
            (base + 2, base + 3, base + 5, base + 4),
            (base + 4, base + 5, base + 6),
        ]

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    col = bpy.context.scene.collection
    col.objects.link(obj)

    # Double-sided (tutorial)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.duplicate()
    bpy.ops.mesh.flip_normals()
    bpy.ops.transform.shrink_fatten(value=0.006)
    bpy.ops.object.mode_set(mode="OBJECT")

    # Flat normals from a plane so each tuft shades painterly
    plane_mesh = bpy.data.meshes.new(name + "_plane")
    plane_mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    plane = bpy.data.objects.new(name + "_plane", plane_mesh)
    col.objects.link(plane)
    dt = obj.modifiers.new("FlatN", "DATA_TRANSFER")
    dt.object = plane
    dt.use_loop_data = True
    dt.data_types_loops = {"CUSTOM_NORMAL"}
    dt.loop_mapping = "NEAREST_POLYNOR"
    bpy.ops.object.modifier_apply(modifier="FlatN")
    bpy.data.objects.remove(plane, do_unlink=True)
    bpy.data.meshes.remove(plane_mesh)

    bpy.ops.object.shade_smooth()
    if hasattr(obj.data, "use_auto_smooth"):
        obj.data.use_auto_smooth = True
        obj.data.auto_smooth_angle = math.radians(180)
    try:
        bpy.ops.mesh.customdata_custom_splitnormals_add()
    except Exception:
        pass
    obj.select_set(False)
    return obj


def make_flower(name: str) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    # tiny 5-petal flat-ish bloom
    verts = [(0, 0, 0.02)]
    faces = []
    for i in range(5):
        a0 = i * math.tau / 5
        a1 = (i + 0.5) * math.tau / 5
        a2 = (i + 1) * math.tau / 5
        for a, r, z in ((a0, 0.04, 0.02), (a1, 0.11, 0.05), (a2, 0.04, 0.02)):
            verts.append((math.cos(a) * r, math.sin(a) * r, z))
        b = 1 + i * 3
        faces.append((0, b, b + 1, b + 2))
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def build_collections():
    grass_col = bpy.data.collections.new("GrassClumps")
    flower_col = bpy.data.collections.new("Flowers")
    scene = bpy.context.scene.collection
    scene.children.link(grass_col)
    scene.children.link(flower_col)
    for i, seed in enumerate((1, 2, 3, 4)):
        c = make_clump(f"Clump_{i}", seed)
        scene.objects.unlink(c)
        grass_col.objects.link(c)
        c.location = (0, 0, -50)
    f = make_flower("Flower")
    scene.objects.unlink(f)
    flower_col.objects.link(f)
    f.location = (0, 0, -50)
    return grass_col, flower_col


def create_ground(size=8.0, cuts=72):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=cuts, y_subdivisions=cuts, size=size)
    ground = bpy.context.active_object
    ground.name = "Ground"
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    mesh = ground.data
    attr = mesh.color_attributes.new(name=MASK_NAME, type="FLOAT_COLOR", domain="POINT")
    for i, v in enumerate(mesh.vertices):
        x, y = v.co.x, v.co.y
        path = abs(y - 0.9 * math.sin(x * 0.65) - 0.2 * math.sin(x * 1.8))
        dirt = 1.0 - min(1.0, max(0.0, (path - 0.4) / 0.38))
        edge = max(abs(x), abs(y)) / (size * 0.5)
        fade = 1.0 if edge < 0.9 else max(0.0, 1.0 - (edge - 0.9) / 0.1)
        g = max(0.0, min(1.0, (1.0 - dirt) * fade))
        attr.data[i].color = (g, g, g, 1.0)
    return ground


# ---------------------------------------------------------------------------
# Material — YOUR normal map drives the hand-painted shadows
# ---------------------------------------------------------------------------

def make_grass_material(normal_img: bpy.types.Image, empty: bpy.types.Object) -> bpy.types.Material:
    mat = bpy.data.materials.new("AnimeGrass")
    mat.use_nodes = True
    mat.blend_method = "OPAQUE"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "NONE"
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = True

    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (1200, 40))

    # Object-space coords from Empty — syncs ground + grass (tutorial trick)
    texcoord = node(nt, "ShaderNodeTexCoord", (-1000, 40))
    texcoord.object = empty
    mapping = node(nt, "ShaderNodeMapping", (-800, 40))
    mapping.inputs["Scale"].default_value = (0.16, 0.16, 0.16)
    link(nt, texcoord.outputs["Object"], mapping.inputs["Vector"])

    ntex = node(nt, "ShaderNodeTexImage", (-580, 40))
    ntex.image = normal_img
    ntex.interpolation = "Cubic"
    link(nt, mapping.outputs["Vector"], ntex.inputs["Vector"])

    # Normal Map in WORLD space (tutorial)
    nmap = node(nt, "ShaderNodeNormalMap", (-320, -200))
    nmap.space = "WORLD"
    nmap.inputs["Strength"].default_value = 2.4
    link(nt, ntex.outputs["Color"], nmap.inputs["Color"])

    # Color variation + hard painted shadow blobs from the normal map
    rgb2bw = node(nt, "ShaderNodeRGBToBW", (-320, 200))
    link(nt, ntex.outputs["Color"], rgb2bw.inputs["Color"])
    paint = node(nt, "ShaderNodeValToRGB", (-100, 220))
    paint.color_ramp.interpolation = "LINEAR"
    paint.color_ramp.elements[0].position = 0.2
    paint.color_ramp.elements[0].color = (0.10, 0.32, 0.09, 1)  # deep painted shadow
    paint.color_ramp.elements[1].position = 0.8
    paint.color_ramp.elements[1].color = (0.78, 0.94, 0.30, 1)  # bright lime
    mid = paint.color_ramp.elements.new(0.48)
    mid.color = (0.28, 0.58, 0.15, 1)
    link(nt, rgb2bw.outputs["Val"], paint.inputs["Fac"])

    mix_d = node(nt, "ShaderNodeMix", (-100, 20), data_type="RGBA")
    mix_d.inputs["A"].default_value = (0.76, 0.60, 0.38, 1)
    mix_d.inputs["B"].default_value = (0.48, 0.36, 0.22, 1)
    link(nt, rgb2bw.outputs["Val"], mix_d.inputs["Factor"])

    attr = node(nt, "ShaderNodeAttribute", (-320, -40))
    attr.attribute_name = MASK_NAME
    mix_t = node(nt, "ShaderNodeMix", (160, 100), data_type="RGBA")
    link(nt, attr.outputs["Color"], mix_t.inputs["Factor"])
    link(nt, mix_d.outputs["Result"], mix_t.inputs["A"])
    link(nt, paint.outputs["Color"], mix_t.inputs["B"])

    # Wind darken
    wattr = node(nt, "ShaderNodeAttribute", (-100, -300))
    wattr.attribute_name = WIND_ATTR
    wmul = node(nt, "ShaderNodeMath", (160, -300), operation="MULTIPLY")
    wmul.inputs[1].default_value = 0.35
    link(nt, wattr.outputs["Fac"], wmul.inputs[0])
    mix_w = node(nt, "ShaderNodeMix", (360, 40), data_type="RGBA")
    mix_w.inputs["B"].default_value = (0.10, 0.28, 0.09, 1)
    link(nt, wmul.outputs["Value"], mix_w.inputs["Factor"])
    link(nt, mix_t.outputs["Result"], mix_w.inputs["A"])

    # Cel: Diffuse lit by YOUR normals → Shader to RGB → hard ramp
    diffuse = node(nt, "ShaderNodeBsdfDiffuse", (160, -140))
    diffuse.inputs["Color"].default_value = (1, 1, 1, 1)
    link(nt, nmap.outputs["Normal"], diffuse.inputs["Normal"])
    sh2rgb = node(nt, "ShaderNodeShaderToRGB", (360, -140))
    link(nt, diffuse.outputs["BSDF"], sh2rgb.inputs["Shader"])

    cel = node(nt, "ShaderNodeValToRGB", (560, -140))
    cel.color_ramp.interpolation = "CONSTANT"
    cel.color_ramp.elements[0].position = 0.0
    cel.color_ramp.elements[0].color = (0.40, 0.34, 0.62, 1)
    cel.color_ramp.elements[1].position = 0.58
    cel.color_ramp.elements[1].color = (1.0, 1.0, 0.97, 1)
    link(nt, sh2rgb.outputs["Color"], cel.inputs["Fac"])

    mul = node(nt, "ShaderNodeMix", (800, 20), data_type="RGBA", blend_type="MULTIPLY")
    mul.inputs["Factor"].default_value = 1.0
    link(nt, mix_w.outputs["Result"], mul.inputs["A"])
    link(nt, cel.outputs["Color"], mul.inputs["B"])

    emit = node(nt, "ShaderNodeEmission", (1000, 20))
    emit.inputs["Strength"].default_value = 1.0
    link(nt, mul.outputs["Result"], emit.inputs["Color"])
    link(nt, emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def make_flower_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("AnimeFlower")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (300, 0))
    emit = node(nt, "ShaderNodeEmission", (80, 0))
    emit.inputs["Color"].default_value = (0.95, 0.48, 0.72, 1)
    emit.inputs["Strength"].default_value = 1.0
    link(nt, emit.outputs["Emission"], out.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# Geometry Nodes
# ---------------------------------------------------------------------------

def build_grass_nodes(grass_col, flower_col, grass_mat, flower_mat):
    nt = bpy.data.node_groups.new("AnimeGrass", "GeometryNodeTree")
    add_socket(nt, "Geometry", "INPUT", "NodeSocketGeometry")
    add_socket(nt, "Density", "INPUT", "NodeSocketFloat", 90.0, 1.0, 300.0)
    add_socket(nt, "Scale", "INPUT", "NodeSocketFloat", 1.1, 0.2, 3.0)
    add_socket(nt, "Flower Density", "INPUT", "NodeSocketFloat", 2.0, 0.0, 20.0)
    add_socket(nt, "Wind Speed", "INPUT", "NodeSocketFloat", 0.5, 0.0, 3.0)
    add_socket(nt, "Wind Strength", "INPUT", "NodeSocketFloat", 0.32, 0.0, 1.5)
    add_socket(nt, "Seed", "INPUT", "NodeSocketInt", 4, 0, 9999)
    add_socket(nt, "Geometry", "OUTPUT", "NodeSocketGeometry")

    nin = node(nt, "NodeGroupInput", (-1700, 40))
    nout = node(nt, "NodeGroupOutput", (1500, 40))

    named = node(nt, "GeometryNodeInputNamedAttribute", (-1500, -220), data_type="FLOAT_COLOR")
    named.inputs["Name"].default_value = MASK_NAME
    sep = node(nt, "FunctionNodeSeparateColor", (-1300, -220))
    link(nt, named.outputs["Attribute"], sep.inputs["Color"])
    mask = sep.outputs["Red"]

    dens = node(nt, "ShaderNodeMath", (-1300, 140), operation="MULTIPLY")
    link(nt, nin.outputs["Density"], dens.inputs[0])
    link(nt, mask, dens.inputs[1])

    dist = node(nt, "GeometryNodeDistributePointsOnFaces", (-1100, 160))
    dist.distribute_method = "RANDOM"
    link(nt, nin.outputs["Geometry"], dist.inputs["Mesh"])
    link(nt, dens.outputs["Value"], dist.inputs["Density"])
    link(nt, nin.outputs["Seed"], dist.inputs["Seed"])

    # Wind
    time = node(nt, "GeometryNodeInputSceneTime", (-1500, -420))
    pos = node(nt, "GeometryNodeInputPosition", (-1500, -540))
    wspeed = node(nt, "ShaderNodeMath", (-1300, -460), operation="MULTIPLY")
    link(nt, time.outputs["Seconds"], wspeed.inputs[0])
    link(nt, nin.outputs["Wind Speed"], wspeed.inputs[1])
    wave = node(nt, "ShaderNodeTexNoise", (-1100, -400))
    wave.noise_dimensions = "4D"
    wave.inputs["Scale"].default_value = 0.3
    link(nt, pos.outputs["Position"], wave.inputs["Vector"])
    link(nt, wspeed.outputs["Value"], wave.inputs["W"])
    flutter = node(nt, "ShaderNodeTexNoise", (-1100, -580))
    flutter.noise_dimensions = "4D"
    flutter.inputs["Scale"].default_value = 1.5
    link(nt, pos.outputs["Position"], flutter.inputs["Vector"])
    w2 = node(nt, "ShaderNodeMath", (-1300, -640), operation="MULTIPLY")
    w2.inputs[1].default_value = 2.3
    link(nt, wspeed.outputs["Value"], w2.inputs[0])
    link(nt, w2.outputs["Value"], flutter.inputs["W"])
    fl = node(nt, "ShaderNodeMath", (-900, -540), operation="MULTIPLY")
    fl.inputs[1].default_value = 0.28
    link(nt, flutter.outputs["Fac"], fl.inputs[0])
    mixw = node(nt, "ShaderNodeMath", (-900, -400), operation="ADD")
    link(nt, wave.outputs["Fac"], mixw.inputs[0])
    link(nt, fl.outputs["Value"], mixw.inputs[1])
    centered = node(nt, "ShaderNodeMath", (-720, -400), operation="SUBTRACT")
    centered.inputs[1].default_value = 0.5
    link(nt, mixw.outputs["Value"], centered.inputs[0])
    wind = node(nt, "ShaderNodeMath", (-540, -400), operation="MULTIPLY")
    link(nt, centered.outputs["Value"], wind.inputs[0])
    link(nt, nin.outputs["Wind Strength"], wind.inputs[1])
    wabs = node(nt, "ShaderNodeMath", (-540, -520), operation="ABSOLUTE")
    link(nt, wind.outputs["Value"], wabs.inputs[0])

    store = node(nt, "GeometryNodeStoreNamedAttribute", (-540, 80), data_type="FLOAT", domain="POINT")
    store.inputs["Name"].default_value = WIND_ATTR
    link(nt, dist.outputs["Points"], store.inputs["Geometry"])
    link(nt, wabs.outputs["Value"], store.inputs["Value"])

    colinfo = node(nt, "GeometryNodeCollectionInfo", (-540, -100), transform_space="ORIGINAL")
    colinfo.inputs["Collection"].default_value = grass_col
    colinfo.inputs["Separate Children"].default_value = True
    colinfo.inputs["Reset Children"].default_value = True

    align = node(nt, "FunctionNodeAlignEulerToVector", (-320, 200), axis="Z")
    link(nt, dist.outputs["Normal"], align.inputs["Vector"])
    idn = node(nt, "GeometryNodeInputID", (-540, -240))
    ryaw = node(nt, "FunctionNodeRandomValue", (-320, -40), data_type="FLOAT")
    ryaw.inputs["Min"].default_value = 0.0
    ryaw.inputs["Max"].default_value = math.tau
    link(nt, idn.outputs["ID"], ryaw.inputs["ID"])
    link(nt, nin.outputs["Seed"], ryaw.inputs["Seed"])
    yaw = node(nt, "ShaderNodeCombineXYZ", (-140, -40))
    link(nt, ryaw.outputs["Value"], yaw.inputs["Z"])

    sample = node(nt, "GeometryNodeSampleNearestSurface", (-320, -240), data_type="FLOAT")
    link(nt, nin.outputs["Geometry"], sample.inputs["Mesh"])
    link(nt, mask, sample.inputs["Value"])
    link(nt, pos.outputs["Position"], sample.inputs["Sample Position"])

    rs = node(nt, "FunctionNodeRandomValue", (-320, -420), data_type="FLOAT")
    rs.inputs["Min"].default_value = 0.7
    rs.inputs["Max"].default_value = 1.4
    link(nt, idn.outputs["ID"], rs.inputs["ID"])
    seed2 = node(nt, "ShaderNodeMath", (-540, -480), operation="ADD")
    seed2.inputs[1].default_value = 23
    link(nt, nin.outputs["Seed"], seed2.inputs[0])
    link(nt, seed2.outputs["Value"], rs.inputs["Seed"])
    s1 = node(nt, "ShaderNodeMath", (-140, -360), operation="MULTIPLY")
    link(nt, rs.outputs["Value"], s1.inputs[0])
    link(nt, nin.outputs["Scale"], s1.inputs[1])
    s2 = node(nt, "ShaderNodeMath", (40, -360), operation="MULTIPLY")
    link(nt, s1.outputs["Value"], s2.inputs[0])
    link(nt, sample.outputs["Value"], s2.inputs[1])
    svec = node(nt, "ShaderNodeCombineXYZ", (200, -360))
    link(nt, s2.outputs["Value"], svec.inputs[0])
    link(nt, s2.outputs["Value"], svec.inputs[1])
    link(nt, s2.outputs["Value"], svec.inputs[2])

    ri = node(nt, "FunctionNodeRandomValue", (-140, -180), data_type="INT")
    for sock in ri.inputs:
        if sock.name == "Min" and sock.type == "INT":
            sock.default_value = 0
        if sock.name == "Max" and sock.type == "INT":
            sock.default_value = 3
    link(nt, idn.outputs["ID"], ri.inputs["ID"])
    link(nt, nin.outputs["Seed"], ri.inputs["Seed"])

    iop = node(nt, "GeometryNodeInstanceOnPoints", (200, 100))
    link(nt, store.outputs["Geometry"], iop.inputs["Points"])
    link(nt, colinfo.outputs["Instances"], iop.inputs["Instance"])
    iop.inputs["Pick Instance"].default_value = True
    link(nt, ri.outputs["Value"], iop.inputs["Instance Index"])
    link(nt, align.outputs["Rotation"], iop.inputs["Rotation"])
    link(nt, svec.outputs["Vector"], iop.inputs["Scale"])

    rot_yaw = node(nt, "GeometryNodeRotateInstances", (420, 100))
    link(nt, iop.outputs["Instances"], rot_yaw.inputs["Instances"])
    link(nt, yaw.outputs["Vector"], rot_yaw.inputs["Rotation"])

    we = node(nt, "ShaderNodeCombineXYZ", (420, -160))
    link(nt, wind.outputs["Value"], we.inputs["X"])
    wz = node(nt, "ShaderNodeMath", (240, -240), operation="MULTIPLY")
    wz.inputs[1].default_value = 0.3
    link(nt, wind.outputs["Value"], wz.inputs[0])
    link(nt, wz.outputs["Value"], we.inputs["Z"])
    rot_w = node(nt, "GeometryNodeRotateInstances", (640, 60))
    link(nt, rot_yaw.outputs["Instances"], rot_w.inputs["Instances"])
    link(nt, we.outputs["Vector"], rot_w.inputs["Rotation"])

    realize = node(nt, "GeometryNodeRealizeInstances", (840, 60))
    link(nt, rot_w.outputs["Instances"], realize.inputs["Geometry"])
    setm = node(nt, "GeometryNodeSetMaterial", (1040, 60))
    setm.inputs["Material"].default_value = grass_mat
    link(nt, realize.outputs["Geometry"], setm.inputs["Geometry"])

    # Flowers
    fd = node(nt, "ShaderNodeMath", (-1300, -760), operation="MULTIPLY")
    link(nt, nin.outputs["Flower Density"], fd.inputs[0])
    link(nt, mask, fd.inputs[1])
    fdist = node(nt, "GeometryNodeDistributePointsOnFaces", (-1100, -760))
    fdist.distribute_method = "RANDOM"
    link(nt, nin.outputs["Geometry"], fdist.inputs["Mesh"])
    link(nt, fd.outputs["Value"], fdist.inputs["Density"])
    fseed = node(nt, "ShaderNodeMath", (-1300, -860), operation="ADD")
    fseed.inputs[1].default_value = 91
    link(nt, nin.outputs["Seed"], fseed.inputs[0])
    link(nt, fseed.outputs["Value"], fdist.inputs["Seed"])
    fcol = node(nt, "GeometryNodeCollectionInfo", (-860, -760), transform_space="ORIGINAL")
    fcol.inputs["Collection"].default_value = flower_col
    fcol.inputs["Separate Children"].default_value = True
    fcol.inputs["Reset Children"].default_value = True
    falign = node(nt, "FunctionNodeAlignEulerToVector", (-660, -680), axis="Z")
    link(nt, fdist.outputs["Normal"], falign.inputs["Vector"])
    fiop = node(nt, "GeometryNodeInstanceOnPoints", (-460, -760))
    link(nt, fdist.outputs["Points"], fiop.inputs["Points"])
    link(nt, fcol.outputs["Instances"], fiop.inputs["Instance"])
    link(nt, falign.outputs["Rotation"], fiop.inputs["Rotation"])
    frs = node(nt, "FunctionNodeRandomValue", (-660, -860), data_type="FLOAT")
    frs.inputs["Min"].default_value = 0.8
    frs.inputs["Max"].default_value = 1.5
    fid = node(nt, "GeometryNodeInputID", (-860, -880))
    link(nt, fid.outputs["ID"], frs.inputs["ID"])
    link(nt, fseed.outputs["Value"], frs.inputs["Seed"])
    link(nt, frs.outputs["Value"], fiop.inputs["Scale"])
    freal = node(nt, "GeometryNodeRealizeInstances", (-260, -760))
    link(nt, fiop.outputs["Instances"], freal.inputs["Geometry"])
    fmat = node(nt, "GeometryNodeSetMaterial", (-60, -760))
    fmat.inputs["Material"].default_value = flower_mat
    link(nt, freal.outputs["Geometry"], fmat.inputs["Geometry"])

    gmat = node(nt, "GeometryNodeSetMaterial", (1040, -80))
    gmat.inputs["Material"].default_value = grass_mat
    link(nt, nin.outputs["Geometry"], gmat.inputs["Geometry"])

    join = node(nt, "GeometryNodeJoinGeometry", (1240, 20))
    link(nt, gmat.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, setm.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, fmat.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, join.outputs["Geometry"], nout.inputs["Geometry"])
    return nt


def setup_scene():
    world = bpy.data.worlds.new("AnimeWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputWorld", (260, 0))
    bg = node(nt, "ShaderNodeBackground", (60, 0))
    bg.inputs["Color"].default_value = (0.82, 0.90, 0.96, 1)
    bg.inputs["Strength"].default_value = 0.45
    link(nt, bg.outputs["Background"], out.inputs["Surface"])

    empty = bpy.data.objects.new("TexSync", None)
    empty.empty_display_type = "CUBE"
    empty.empty_display_size = 3.0
    empty.scale = (3.2, 3.2, 3.2)
    bpy.context.collection.objects.link(empty)

    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam)
    cam_data.lens = 50
    # Diamond isometric like the tutorial thumbnail
    cam.location = (6.8, -6.8, 5.8)
    cam.rotation_euler = Euler((math.radians(55), 0, math.radians(45)), "XYZ")
    bpy.context.scene.camera = cam

    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = Euler((math.radians(38), math.radians(10), math.radians(130)), "XYZ")
    sun.data.energy = 5.5
    sun.data.angle = math.radians(1.2)
    sun.data.color = (1.0, 0.98, 0.92)

    fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", "AREA"))
    bpy.context.collection.objects.link(fill)
    fill.location = (-5, -2, 3.5)
    fill.rotation_euler = Euler((math.radians(65), 0, math.radians(-45)), "XYZ")
    fill.data.energy = 12
    fill.data.size = 7
    fill.data.color = (0.7, 0.8, 1.0)
    return cam, empty


def configure_render(scene):
    engines = {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1600
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    if hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 64
    scene.frame_start = 1
    scene.frame_end = 48
    scene.render.fps = 24


def render_still(scene, path: Path, frame: int):
    scene.frame_set(frame)
    scene.render.filepath = str(path)
    log(f"RENDER {path.name} @ {frame}")
    bpy.ops.render.render(write_still=True)


def build():
    log("Clearing…")
    clear_scene()
    log(f"Loading normal map: {NORMAL_PATH}")
    normal_img = load_normal_image()
    log("Assets…")
    grass_col, flower_col = build_collections()
    ground = create_ground()
    cam, empty = setup_scene()
    grass_mat = make_grass_material(normal_img, empty)
    flower_mat = make_flower_material()
    ground.data.materials.append(grass_mat)
    ground.data.materials.append(flower_mat)

    log("Geometry Nodes…")
    nt = build_grass_nodes(grass_col, flower_col, grass_mat, flower_mat)
    mod = ground.modifiers.new("AnimeGrass", "NODES")
    mod.node_group = nt

    if hasattr(ground, "visible_shadow"):
        ground.visible_shadow = False

    configure_render(bpy.context.scene)
    set_mod_input(ground, "AnimeGrass", "Density", 110.0)
    set_mod_input(ground, "AnimeGrass", "Scale", 1.15)
    set_mod_input(ground, "AnimeGrass", "Flower Density", 2.4)
    set_mod_input(ground, "AnimeGrass", "Wind Speed", 0.55)
    set_mod_input(ground, "AnimeGrass", "Wind Strength", 0.28)
    set_mod_input(ground, "AnimeGrass", "Wind Strength", 0.22, 1)
    set_mod_input(ground, "AnimeGrass", "Wind Strength", 0.4, 24)
    set_mod_input(ground, "AnimeGrass", "Wind Strength", 0.25, 48)

    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    deps = bpy.context.evaluated_depsgraph_get()
    ev = ground.evaluated_get(deps)
    m = ev.to_mesh()
    log(f"Evaluated verts: {len(m.vertices)}")
    ev.to_mesh_clear()

    scene = bpy.context.scene
    only_stills = "--stills-only" in sys.argv
    render_still(scene, RENDER_DIR / "anime_grass_hero", 24)
    render_still(scene, RENDER_DIR / "anime_grass_wind_a", 8)
    render_still(scene, RENDER_DIR / "anime_grass_wind_b", 40)

    if not only_stills:
        anim = RENDER_DIR / "anim"
        anim.mkdir(exist_ok=True)
        scene.render.resolution_x = 960
        scene.render.resolution_y = 960
        for f in range(1, 49, 2):
            render_still(scene, anim / f"frame_{f:04d}", f)

    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    log(f"SAVED {BLEND_PATH}")


if __name__ == "__main__":
    try:
        build()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
