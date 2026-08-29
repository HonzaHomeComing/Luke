"""
Anime Grass — Geometry Nodes meadow (anime-style workflow)

Inspired by common anime grass pipelines:
vertex-mask scatter, cel shading, transferred normals, wind.

  blender --background --factory-startup --python anime-grass/build_anime_grass.py
"""

from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Euler

ROOT = Path(__file__).resolve().parent
BLEND_PATH = ROOT / "anime_grass.blend"
RENDER_DIR = ROOT / "renders"
MASK_NAME = "Grass"
WIND_ATTR = "wind"


def log(msg: str) -> None:
    print(msg, flush=True)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in list(bpy.data.node_groups):
        bpy.data.node_groups.remove(block)
    for block in list(bpy.data.materials):
        bpy.data.materials.remove(block)
    for block in list(bpy.data.meshes):
        bpy.data.meshes.remove(block)
    for block in list(bpy.data.collections):
        if block != bpy.context.scene.collection:
            bpy.data.collections.remove(block)


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


def make_blade(name: str, width=0.05, height=0.55, bend=0.08, lean=0.04):
    verts = [
        (-width * 0.55, 0, 0),
        (width * 0.55, 0, 0),
        (-width * 0.75, lean * 0.3, height * 0.28),
        (width * 0.75, lean * 0.3, height * 0.28),
        (-width * 0.45, lean * 0.7 + bend * 0.4, height * 0.62),
        (width * 0.45, lean * 0.7 + bend * 0.4, height * 0.62),
        (0.0, lean + bend, height),
    ]
    faces = [(0, 1, 3, 2), (2, 3, 5, 4), (4, 5, 6)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return bpy.data.objects.new(name, mesh)


def build_grass_collection():
    col = bpy.data.collections.new("GrassBlades")
    bpy.context.scene.collection.children.link(col)
    specs = [
        ("Blade_A", 0.045, 0.48, 0.06, 0.03),
        ("Blade_B", 0.055, 0.62, 0.1, 0.045),
        ("Blade_C", 0.038, 0.42, 0.04, 0.02),
        ("Blade_D", 0.06, 0.58, 0.08, 0.05),
    ]
    for i, (name, w, h, b, lean) in enumerate(specs):
        obj = make_blade(name, w, h, b, lean)
        obj.location = (0, 0, -50)  # originals out of frame; Reset Children ignores this
        col.objects.link(obj)
    return col


def create_ground(size=10.0, cuts=48):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=cuts, y_subdivisions=cuts, size=size)
    ground = bpy.context.active_object
    ground.name = "Ground"
    mesh = ground.data

    attr = mesh.color_attributes.new(name=MASK_NAME, type="FLOAT_COLOR", domain="POINT")
    for i, v in enumerate(mesh.vertices):
        x, y = v.co.x, v.co.y
        path = abs(y - 1.0 * math.sin(x * 0.55) - 0.25 * math.sin(x * 1.6))
        dirt = 1.0 - min(1.0, max(0.0, (path - 0.5) / 0.4))
        clearings = 0.0
        for cx, cy, r in ((-2.8, 2.2, 1.25), (3.4, -2.4, 1.4), (0.2, 3.1, 1.0)):
            d = math.hypot(x - cx, y - cy)
            clearings = max(clearings, 1.0 - min(1.0, d / r))
        edge = max(abs(x), abs(y)) / (size * 0.5)
        edge_fade = 1.0 if edge < 0.84 else max(0.0, 1.0 - (edge - 0.84) / 0.16)
        h = math.sin(x * 3.1 + y * 2.7) * math.cos(x * 1.3 - y * 4.1)
        grass = (1.0 - max(dirt, clearings * 0.85) + 0.07 * h) * edge_fade
        grass = max(0.0, min(1.0, grass))
        attr.data[i].color = (grass, grass, grass, 1.0)
    return ground


def make_anime_material():
    mat = bpy.data.materials.new("AnimeGrass")
    mat.use_nodes = True
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = True

    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (980, 0))

    attr_mask = node(nt, "ShaderNodeAttribute", (-720, 180))
    attr_mask.attribute_name = MASK_NAME

    texcoord = node(nt, "ShaderNodeTexCoord", (-920, 20))
    mapping = node(nt, "ShaderNodeMapping", (-720, 20))
    mapping.inputs["Scale"].default_value = (2.2, 2.2, 2.2)
    link(nt, texcoord.outputs["Object"], mapping.inputs["Vector"])
    noise = node(nt, "ShaderNodeTexNoise", (-520, 20))
    noise.inputs["Scale"].default_value = 5.5
    noise.inputs["Detail"].default_value = 8.0
    link(nt, mapping.outputs["Vector"], noise.inputs["Vector"])
    ramp = node(nt, "ShaderNodeValToRGB", (-320, 20))
    ramp.color_ramp.elements[0].position = 0.32
    ramp.color_ramp.elements[1].position = 0.68
    link(nt, noise.outputs["Fac"], ramp.inputs["Fac"])

    mix_grass = node(nt, "ShaderNodeMix", (-100, 160), data_type="RGBA")
    mix_grass.inputs["A"].default_value = (0.48, 0.74, 0.24, 1)
    mix_grass.inputs["B"].default_value = (0.26, 0.52, 0.13, 1)
    link(nt, ramp.outputs["Color"], mix_grass.inputs["Factor"])

    mix_dirt = node(nt, "ShaderNodeMix", (-100, -40), data_type="RGBA")
    mix_dirt.inputs["A"].default_value = (0.58, 0.44, 0.3, 1)
    mix_dirt.inputs["B"].default_value = (0.4, 0.3, 0.2, 1)
    link(nt, ramp.outputs["Color"], mix_dirt.inputs["Factor"])

    mix_terrain = node(nt, "ShaderNodeMix", (140, 80), data_type="RGBA")
    link(nt, attr_mask.outputs["Color"], mix_terrain.inputs["Factor"])
    link(nt, mix_dirt.outputs["Result"], mix_terrain.inputs["A"])
    link(nt, mix_grass.outputs["Result"], mix_terrain.inputs["B"])

    attr_wind = node(nt, "ShaderNodeAttribute", (-100, -240))
    attr_wind.attribute_name = WIND_ATTR
    wind_amt = node(nt, "ShaderNodeMath", (140, -240), operation="MULTIPLY")
    wind_amt.inputs[1].default_value = 0.3
    # Fac may be empty — also try Color
    link(nt, attr_wind.outputs["Fac"], wind_amt.inputs[0])
    mix_wind = node(nt, "ShaderNodeMix", (340, 40), data_type="RGBA")
    mix_wind.inputs["B"].default_value = (0.16, 0.3, 0.09, 1)
    link(nt, wind_amt.outputs["Value"], mix_wind.inputs["Factor"])
    link(nt, mix_terrain.outputs["Result"], mix_wind.inputs["A"])

    diffuse = node(nt, "ShaderNodeBsdfDiffuse", (140, -420))
    diffuse.inputs["Color"].default_value = (1, 1, 1, 1)
    sh2rgb = node(nt, "ShaderNodeShaderToRGB", (340, -420))
    link(nt, diffuse.outputs["BSDF"], sh2rgb.inputs["Shader"])
    cel = node(nt, "ShaderNodeValToRGB", (540, -420))
    cel.color_ramp.interpolation = "CONSTANT"
    cel.color_ramp.elements[0].color = (0.5, 0.42, 0.72, 1)
    cel.color_ramp.elements[0].position = 0.0
    cel.color_ramp.elements[1].position = 0.4
    cel.color_ramp.elements[1].color = (1, 1, 1, 1)
    link(nt, sh2rgb.outputs["Color"], cel.inputs["Fac"])

    mul = node(nt, "ShaderNodeMix", (760, 0), data_type="RGBA", blend_type="MULTIPLY")
    mul.inputs["Factor"].default_value = 1.0
    link(nt, mix_wind.outputs["Result"], mul.inputs["A"])
    link(nt, cel.outputs["Color"], mul.inputs["B"])

    emission = node(nt, "ShaderNodeEmission", (760, -180))
    emission.inputs["Strength"].default_value = 1.0
    link(nt, mul.outputs["Result"], emission.inputs["Color"])
    link(nt, emission.outputs["Emission"], out.inputs["Surface"])
    return mat


def build_grass_nodes(grass_col, mat):
    nt = bpy.data.node_groups.new("AnimeGrass", "GeometryNodeTree")
    add_socket(nt, "Geometry", "INPUT", "NodeSocketGeometry")
    add_socket(nt, "Density", "INPUT", "NodeSocketFloat", 28.0, 0.5, 120.0)
    add_socket(nt, "Scale", "INPUT", "NodeSocketFloat", 1.1, 0.1, 3.0)
    add_socket(nt, "Wind Speed", "INPUT", "NodeSocketFloat", 0.55, 0.0, 3.0)
    add_socket(nt, "Wind Strength", "INPUT", "NodeSocketFloat", 0.4, 0.0, 1.5)
    add_socket(nt, "Seed", "INPUT", "NodeSocketInt", 3, 0, 9999)
    add_socket(nt, "Geometry", "OUTPUT", "NodeSocketGeometry")

    nin = node(nt, "NodeGroupInput", (-1700, 40))
    nout = node(nt, "NodeGroupOutput", (1500, 40))

    named = node(nt, "GeometryNodeInputNamedAttribute", (-1500, -260), data_type="FLOAT_COLOR")
    named.inputs["Name"].default_value = MASK_NAME
    sep = node(nt, "FunctionNodeSeparateColor", (-1300, -260))
    link(nt, named.outputs["Attribute"], sep.inputs["Color"])
    mask = sep.outputs["Red"]

    dens = node(nt, "ShaderNodeMath", (-1300, 120), operation="MULTIPLY")
    link(nt, nin.outputs["Density"], dens.inputs[0])
    link(nt, mask, dens.inputs[1])

    dist = node(nt, "GeometryNodeDistributePointsOnFaces", (-1100, 140))
    dist.distribute_method = "RANDOM"
    link(nt, nin.outputs["Geometry"], dist.inputs["Mesh"])
    link(nt, dens.outputs["Value"], dist.inputs["Density"])
    link(nt, nin.outputs["Seed"], dist.inputs["Seed"])

    # Wind
    scene_time = node(nt, "GeometryNodeInputSceneTime", (-1500, -480))
    pos = node(nt, "GeometryNodeInputPosition", (-1500, -600))
    wspeed = node(nt, "ShaderNodeMath", (-1300, -520), operation="MULTIPLY")
    link(nt, scene_time.outputs["Seconds"], wspeed.inputs[0])
    link(nt, nin.outputs["Wind Speed"], wspeed.inputs[1])

    wave = node(nt, "ShaderNodeTexNoise", (-1100, -420))
    wave.noise_dimensions = "4D"
    wave.inputs["Scale"].default_value = 0.4
    wave.inputs["Detail"].default_value = 2.0
    link(nt, pos.outputs["Position"], wave.inputs["Vector"])
    link(nt, wspeed.outputs["Value"], wave.inputs["W"])

    flutter = node(nt, "ShaderNodeTexNoise", (-1100, -620))
    flutter.noise_dimensions = "4D"
    flutter.inputs["Scale"].default_value = 1.6
    flutter.inputs["Detail"].default_value = 3.0
    link(nt, pos.outputs["Position"], flutter.inputs["Vector"])
    w2 = node(nt, "ShaderNodeMath", (-1300, -700), operation="MULTIPLY")
    w2.inputs[1].default_value = 2.5
    link(nt, wspeed.outputs["Value"], w2.inputs[0])
    link(nt, w2.outputs["Value"], flutter.inputs["W"])

    fl_s = node(nt, "ShaderNodeMath", (-900, -600), operation="MULTIPLY")
    fl_s.inputs[1].default_value = 0.3
    link(nt, flutter.outputs["Fac"], fl_s.inputs[0])
    mix_w = node(nt, "ShaderNodeMath", (-900, -460), operation="ADD")
    link(nt, wave.outputs["Fac"], mix_w.inputs[0])
    link(nt, fl_s.outputs["Value"], mix_w.inputs[1])
    wind = node(nt, "ShaderNodeMath", (-720, -460), operation="MULTIPLY")
    link(nt, mix_w.outputs["Value"], wind.inputs[0])
    link(nt, nin.outputs["Wind Strength"], wind.inputs[1])

    store = node(nt, "GeometryNodeStoreNamedAttribute", (-720, 80), data_type="FLOAT", domain="POINT")
    store.inputs["Name"].default_value = WIND_ATTR
    link(nt, dist.outputs["Points"], store.inputs["Geometry"])
    link(nt, wind.outputs["Value"], store.inputs["Value"])

    colinfo = node(nt, "GeometryNodeCollectionInfo", (-720, -120), transform_space="ORIGINAL")
    colinfo.inputs["Collection"].default_value = grass_col
    colinfo.inputs["Separate Children"].default_value = True
    colinfo.inputs["Reset Children"].default_value = True

    align = node(nt, "FunctionNodeAlignEulerToVector", (-500, 200), axis="Z")
    link(nt, dist.outputs["Normal"], align.inputs["Vector"])

    idn = node(nt, "GeometryNodeInputID", (-720, -280))
    rand_yaw = node(nt, "FunctionNodeRandomValue", (-500, -40), data_type="FLOAT")
    rand_yaw.inputs["Min"].default_value = -math.pi
    rand_yaw.inputs["Max"].default_value = math.pi
    link(nt, idn.outputs["ID"], rand_yaw.inputs["ID"])
    link(nt, nin.outputs["Seed"], rand_yaw.inputs["Seed"])
    yaw = node(nt, "ShaderNodeCombineXYZ", (-320, -40))
    link(nt, rand_yaw.outputs["Value"], yaw.inputs["Z"])

    # Sample mask at points for soft scale
    sample = node(nt, "GeometryNodeSampleNearestSurface", (-500, -280), data_type="FLOAT")
    link(nt, nin.outputs["Geometry"], sample.inputs["Mesh"])
    link(nt, mask, sample.inputs["Value"])
    link(nt, pos.outputs["Position"], sample.inputs["Sample Position"])

    rand_s = node(nt, "FunctionNodeRandomValue", (-500, -480), data_type="FLOAT")
    rand_s.inputs["Min"].default_value = 0.7
    rand_s.inputs["Max"].default_value = 1.3
    link(nt, idn.outputs["ID"], rand_s.inputs["ID"])
    seed2 = node(nt, "ShaderNodeMath", (-720, -540), operation="ADD")
    seed2.inputs[1].default_value = 19
    link(nt, nin.outputs["Seed"], seed2.inputs[0])
    link(nt, seed2.outputs["Value"], rand_s.inputs["Seed"])

    s1 = node(nt, "ShaderNodeMath", (-320, -400), operation="MULTIPLY")
    link(nt, rand_s.outputs["Value"], s1.inputs[0])
    link(nt, nin.outputs["Scale"], s1.inputs[1])
    s2 = node(nt, "ShaderNodeMath", (-160, -400), operation="MULTIPLY")
    link(nt, s1.outputs["Value"], s2.inputs[0])
    link(nt, sample.outputs["Value"], s2.inputs[1])

    svec = node(nt, "ShaderNodeCombineXYZ", (0, -400))
    link(nt, s2.outputs["Value"], svec.inputs[0])
    link(nt, s2.outputs["Value"], svec.inputs[1])
    link(nt, s2.outputs["Value"], svec.inputs[2])

    rand_i = node(nt, "FunctionNodeRandomValue", (-320, -180), data_type="INT")
    for sock in rand_i.inputs:
        if sock.name == "Min" and sock.type == "INT":
            sock.default_value = 0
        if sock.name == "Max" and sock.type == "INT":
            sock.default_value = 3
    link(nt, idn.outputs["ID"], rand_i.inputs["ID"])
    link(nt, nin.outputs["Seed"], rand_i.inputs["Seed"])

    iop = node(nt, "GeometryNodeInstanceOnPoints", (-40, 100))
    link(nt, store.outputs["Geometry"], iop.inputs["Points"])
    link(nt, colinfo.outputs["Instances"], iop.inputs["Instance"])
    iop.inputs["Pick Instance"].default_value = True
    link(nt, rand_i.outputs["Value"], iop.inputs["Instance Index"])
    link(nt, align.outputs["Rotation"], iop.inputs["Rotation"])
    link(nt, svec.outputs["Vector"], iop.inputs["Scale"])

    # Yaw
    rot_yaw = node(nt, "GeometryNodeRotateInstances", (180, 100))
    link(nt, iop.outputs["Instances"], rot_yaw.inputs["Instances"])
    link(nt, yaw.outputs["Vector"], rot_yaw.inputs["Rotation"])

    # Wind tilt
    wind_ang = node(nt, "ShaderNodeMath", (-40, -200), operation="MULTIPLY")
    wind_ang.inputs[1].default_value = 0.5
    link(nt, wind.outputs["Value"], wind_ang.inputs[0])
    wind_e = node(nt, "ShaderNodeCombineXYZ", (140, -200))
    link(nt, wind_ang.outputs["Value"], wind_e.inputs["X"])
    wz = node(nt, "ShaderNodeMath", (-40, -300), operation="MULTIPLY")
    wz.inputs[1].default_value = 0.2
    link(nt, wind.outputs["Value"], wz.inputs[0])
    link(nt, wz.outputs["Value"], wind_e.inputs["Z"])
    rot_wind = node(nt, "GeometryNodeRotateInstances", (380, 60))
    link(nt, rot_yaw.outputs["Instances"], rot_wind.inputs["Instances"])
    link(nt, wind_e.outputs["Vector"], rot_wind.inputs["Rotation"])

    realize = node(nt, "GeometryNodeRealizeInstances", (600, 60))
    link(nt, rot_wind.outputs["Instances"], realize.inputs["Geometry"])

    set_mat = node(nt, "GeometryNodeSetMaterial", (800, 60))
    set_mat.inputs["Material"].default_value = mat
    link(nt, realize.outputs["Geometry"], set_mat.inputs["Geometry"])

    ground_mat = node(nt, "GeometryNodeSetMaterial", (800, -120))
    ground_mat.inputs["Material"].default_value = mat
    link(nt, nin.outputs["Geometry"], ground_mat.inputs["Geometry"])

    join = node(nt, "GeometryNodeJoinGeometry", (1020, 0))
    link(nt, ground_mat.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, set_mat.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, join.outputs["Geometry"], nout.inputs["Geometry"])
    return nt


def build_detail_nodes():
    nt = bpy.data.node_groups.new("GrassDetail", "GeometryNodeTree")
    add_socket(nt, "Geometry", "INPUT", "NodeSocketGeometry")
    add_socket(nt, "Height", "INPUT", "NodeSocketFloat", 0.28, 0.0, 2.0)
    add_socket(nt, "Scale", "INPUT", "NodeSocketFloat", 1.1, 0.1, 8.0)
    add_socket(nt, "Geometry", "OUTPUT", "NodeSocketGeometry")

    nin = node(nt, "NodeGroupInput", (-700, 0))
    nout = node(nt, "NodeGroupOutput", (500, 0))

    named = node(nt, "GeometryNodeInputNamedAttribute", (-500, -180), data_type="FLOAT_COLOR")
    named.inputs["Name"].default_value = MASK_NAME
    sep = node(nt, "FunctionNodeSeparateColor", (-300, -180))
    link(nt, named.outputs["Attribute"], sep.inputs["Color"])

    pos = node(nt, "GeometryNodeInputPosition", (-500, 120))
    noise = node(nt, "ShaderNodeTexNoise", (-300, 120))
    noise.inputs["Detail"].default_value = 8.0
    noise.inputs["Roughness"].default_value = 0.5
    link(nt, pos.outputs["Position"], noise.inputs["Vector"])
    link(nt, nin.outputs["Scale"], noise.inputs["Scale"])

    mapped = node(nt, "ShaderNodeMapRange", (-100, 120))
    mapped.inputs["From Min"].default_value = 0.3
    mapped.inputs["From Max"].default_value = 0.75
    link(nt, noise.outputs["Fac"], mapped.inputs["Value"])

    blur = node(nt, "GeometryNodeBlurAttribute", (80, 40), data_type="FLOAT")
    blur.inputs["Iterations"].default_value = 2
    link(nt, mapped.outputs["Result"], blur.inputs["Value"])

    h = node(nt, "ShaderNodeMath", (260, 80), operation="MULTIPLY")
    link(nt, blur.outputs["Value"], h.inputs[0])
    link(nt, nin.outputs["Height"], h.inputs[1])
    h2 = node(nt, "ShaderNodeMath", (400, 40), operation="MULTIPLY")
    link(nt, h.outputs["Value"], h2.inputs[0])
    link(nt, sep.outputs["Red"], h2.inputs[1])
    comb = node(nt, "ShaderNodeCombineXYZ", (400, -80))
    link(nt, h2.outputs["Value"], comb.inputs["Z"])
    setpos = node(nt, "GeometryNodeSetPosition", (200, -160))
    link(nt, nin.outputs["Geometry"], setpos.inputs["Geometry"])
    link(nt, comb.outputs["Vector"], setpos.inputs["Offset"])
    link(nt, setpos.outputs["Geometry"], nout.inputs["Geometry"])
    return nt


def setup_scene():
    world = bpy.data.worlds.new("AnimeWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputWorld", (260, 0))
    bg = node(nt, "ShaderNodeBackground", (60, 0))
    bg.inputs["Color"].default_value = (0.62, 0.8, 0.98, 1)
    bg.inputs["Strength"].default_value = 0.9
    link(nt, bg.outputs["Background"], out.inputs["Surface"])

    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam)
    cam_data.lens = 32
    bpy.context.scene.camera = cam

    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = Euler((math.radians(48), math.radians(10), math.radians(40)), "XYZ")
    sun.data.energy = 3.0
    sun.data.color = (1.0, 0.96, 0.88)

    fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", "AREA"))
    bpy.context.collection.objects.link(fill)
    fill.location = (-5, -2, 3)
    fill.rotation_euler = Euler((math.radians(65), 0, math.radians(-50)), "XYZ")
    fill.data.energy = 35
    fill.data.size = 7
    fill.data.color = (0.75, 0.85, 1.0)
    return cam


def configure_render(scene):
    engines = {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    if hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 32
    scene.frame_start = 1
    scene.frame_end = 48
    scene.render.fps = 24


def animate_camera(cam):
    # Lower, closer anime meadow framing
    for frame, yaw in ((1, 22), (48, 42)):
        rad = math.radians(yaw)
        r = 6.2
        cam.location = (r * math.sin(rad), -r * math.cos(rad), 1.55)
        cam.rotation_euler = Euler((math.radians(78), 0, rad), "XYZ")
        cam.keyframe_insert("location", frame=frame)
        cam.keyframe_insert("rotation_euler", frame=frame)
    if cam.animation_data and cam.animation_data.action:
        for fcu in cam.animation_data.action.fcurves:
            for kp in fcu.keyframe_points:
                kp.interpolation = "LINEAR"


def render_still(scene, path: Path, frame: int):
    scene.frame_set(frame)
    scene.render.filepath = str(path)
    log(f"RENDER {path.name} @ {frame}")
    bpy.ops.render.render(write_still=True)


def build():
    log("Clearing scene…")
    clear_scene()
    log("Building grass blades…")
    grass_col = build_grass_collection()
    log("Creating ground + mask…")
    ground = create_ground()
    mat = make_anime_material()
    ground.data.materials.append(mat)

    log("Building AnimeGrass nodes…")
    nt = build_grass_nodes(grass_col, mat)
    gmod = ground.modifiers.new("AnimeGrass", "NODES")
    gmod.node_group = nt

    log("Building detail mesh…")
    detail = ground.copy()
    detail.data = ground.data.copy()
    detail.name = "GrassDetail"
    bpy.context.collection.objects.link(detail)
    detail.modifiers.clear()
    dnt = build_detail_nodes()
    dmod = detail.modifiers.new("GrassDetail", "NODES")
    dmod.node_group = dnt
    detail.hide_render = True
    detail.hide_viewport = True

    log("Adding normal transfer…")
    tmod = ground.modifiers.new("NormalBake", "DATA_TRANSFER")
    tmod.object = detail
    tmod.use_loop_data = True
    tmod.data_types_loops = {"CUSTOM_NORMAL"}
    tmod.loop_mapping = "NEAREST_POLYNOR"
    try:
        bpy.context.view_layer.objects.active = ground
        bpy.ops.object.shade_smooth()
    except Exception:
        pass
    if hasattr(ground.data, "use_auto_smooth"):
        ground.data.use_auto_smooth = True
    if hasattr(ground, "visible_shadow"):
        ground.visible_shadow = False

    cam = setup_scene()
    configure_render(bpy.context.scene)
    animate_camera(cam)

    set_mod_input(ground, "AnimeGrass", "Density", 55.0)
    set_mod_input(ground, "AnimeGrass", "Scale", 1.35)
    set_mod_input(ground, "AnimeGrass", "Wind Speed", 0.7)
    set_mod_input(ground, "AnimeGrass", "Wind Strength", 0.55)

    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene

    log("Saving blend before render…")
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    # Sanity: evaluated geometry should be much denser than the grid alone
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = ground.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh()
    log(f"Evaluated verts: {len(eval_mesh.vertices)} (grid-only would be ~{49*49})")
    eval_obj.to_mesh_clear()

    only_stills = "--stills-only" in sys.argv

    render_still(scene, RENDER_DIR / "anime_grass_hero", 24)
    render_still(scene, RENDER_DIR / "anime_grass_wind_a", 8)
    render_still(scene, RENDER_DIR / "anime_grass_wind_b", 40)

    if not only_stills:
        anim = RENDER_DIR / "anim"
        anim.mkdir(exist_ok=True)
        scene.render.resolution_x = 960
        scene.render.resolution_y = 540
        for f in range(1, 49, 2):
            render_still(scene, anim / f"frame_{f:04d}", f)
        scene.render.resolution_x = 1600
        scene.render.resolution_y = 900

    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    log(f"SAVED {BLEND_PATH}")


if __name__ == "__main__":
    try:
        build()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
