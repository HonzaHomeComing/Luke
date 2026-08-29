"""
Anime Grass v2 — closer to Trung Duy Nguyen's anime grass look:
painterly clumps, hand-painted cel shadows via normal bake,
color variation, dirt path sync, flowers, wind.

  blender --background --factory-startup --python anime-grass/build_anime_grass.py
  blender --background --factory-startup --python anime-grass/build_anime_grass.py -- --stills-only
"""

from __future__ import annotations

import math
import random
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Euler, Vector

ROOT = Path(__file__).resolve().parent
BLEND_PATH = ROOT / "anime_grass.blend"
RENDER_DIR = ROOT / "renders"
MASK_NAME = "Grass"
WIND_ATTR = "wind"
DISP_IMG = "GrassDisp"


def log(msg: str) -> None:
    print(msg, flush=True)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for coll in (
        bpy.data.node_groups,
        bpy.data.materials,
        bpy.data.meshes,
        bpy.data.images,
        bpy.data.lights,
        bpy.data.cameras,
    ):
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


# ---------------------------------------------------------------------------
# Procedural "cloud + cutout" displacement image (tutorial style)
# ---------------------------------------------------------------------------

def make_displacement_image(size=512) -> bpy.types.Image:
    if DISP_IMG in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[DISP_IMG])
    img = bpy.data.images.new(DISP_IMG, width=size, height=size, alpha=False)
    pixels = [0.0] * (size * size * 4)
    rng = random.Random(7)

    # Value noise grid
    grid_n = 48
    grid = [[rng.random() for _ in range(grid_n + 1)] for _ in range(grid_n + 1)]

    def sample(u, v):
        u = u % 1.0
        v = v % 1.0
        if u < 0:
            u += 1.0
        if v < 0:
            v += 1.0
        x = u * (grid_n - 1e-6)
        y = v * (grid_n - 1e-6)
        x0 = int(x) % grid_n
        y0 = int(y) % grid_n
        x1 = (x0 + 1) % grid_n
        y1 = (y0 + 1) % grid_n
        fx, fy = x - int(x), y - int(y)
        fx = fx * fx * (3 - 2 * fx)
        fy = fy * fy * (3 - 2 * fy)
        a = grid[y0][x0] * (1 - fx) + grid[y0][x1] * fx
        b = grid[y1][x0] * (1 - fx) + grid[y1][x1] * fx
        return a * (1 - fy) + b * fy

    for y in range(size):
        for x in range(size):
            u, v = x / (size - 1), y / (size - 1)
            n = (
                0.55 * sample(u, v)
                + 0.30 * sample(u * 2.1 + 3.1, v * 2.1)
                + 0.15 * sample(u * 4.3, v * 4.3 + 1.7)
            )
            # Soft posterize — keep blob shapes but avoid harsh pixel blocks
            if n < 0.34:
                val = 0.18 + n * 0.2
            elif n < 0.55:
                t = (n - 0.34) / 0.21
                val = 0.28 + t * 0.32
            elif n < 0.72:
                t = (n - 0.55) / 0.17
                val = 0.60 + t * 0.22
            else:
                val = 0.82 + (n - 0.72) * 0.4
            val = max(0.0, min(1.0, val))
            i = (y * size + x) * 4
            pixels[i:i + 4] = [val, val, val, 1.0]
    img.pixels = pixels
    img.pack()
    return img


def make_grass_card_image(size=256) -> bpy.types.Image:
    """Soft painted grass tuft (RGB + alpha) for billboard cards."""
    name = "GrassCard"
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])
    img = bpy.data.images.new(name, width=size, height=size, alpha=True)
    pixels = [0.0] * (size * size * 4)
    rng = random.Random(11)

    # Several soft vertical strokes tapering upward
    strokes = []
    for _ in range(18):
        cx = rng.uniform(0.2, 0.8)
        width = rng.uniform(0.04, 0.11)
        lean = rng.uniform(-0.12, 0.12)
        top = rng.uniform(0.72, 0.98)
        bot = rng.uniform(0.0, 0.08)
        hue = rng.uniform(0.0, 1.0)
        strokes.append((cx, width, lean, top, bot, hue))

    for y in range(size):
        v = y / (size - 1)
        for x in range(size):
            u = x / (size - 1)
            a = 0.0
            r = g = b = 0.0
            for cx, width, lean, top, bot, hue in strokes:
                if v < bot or v > top:
                    continue
                t = (v - bot) / max(1e-5, top - bot)
                # taper width toward tip
                w = width * (1.15 - 0.85 * t)
                x_center = cx + lean * t
                d = abs(u - x_center) / w
                if d > 1.0:
                    continue
                # soft edge
                cov = (1.0 - d * d) ** 2
                # tip fade
                cov *= min(1.0, t * 4.0) * min(1.0, (1.0 - t) * 8.0 + 0.15)
                # color along blade: darker base → brighter tip
                g0 = 0.22 + 0.18 * hue
                g1 = 0.55 + 0.35 * hue
                rr = 0.12 + 0.2 * t
                gg = g0 * (1 - t) + g1 * t
                bb = 0.08 + 0.05 * t
                a = min(1.0, a + cov)
                r += rr * cov
                g += gg * cov
                b += bb * cov
            if a > 1e-4:
                r /= a
                g /= a
                b /= a
            # soft overall silhouette mask (rounded clump)
            dx, dy = (u - 0.5) / 0.42, (v - 0.45) / 0.55
            clump = max(0.0, 1.0 - (dx * dx + dy * dy))
            a *= clump ** 0.7
            i = (y * size + x) * 4
            pixels[i:i + 4] = [r, g, b, a]
    img.pixels = pixels
    img.alpha_mode = "STRAIGHT"
    img.pack()
    return img


def make_flower_card_image(size=128) -> bpy.types.Image:
    name = "FlowerCard"
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])
    img = bpy.data.images.new(name, width=size, height=size, alpha=True)
    pixels = [0.0] * (size * size * 4)
    petals = 5
    for y in range(size):
        v = y / (size - 1)
        for x in range(size):
            u = x / (size - 1)
            dx, dy = u - 0.5, v - 0.45
            ang = math.atan2(dy, dx)
            rad = math.hypot(dx, dy)
            # petal lobes
            lobe = 0.55 + 0.45 * math.cos(ang * petals)
            edge = 0.28 * lobe
            a = 0.0
            r = g = b = 0.0
            if rad < edge:
                t = rad / max(1e-5, edge)
                a = (1.0 - t) ** 0.6
                r, g, b = 0.95, 0.55, 0.72
            # center
            if rad < 0.07:
                a = 1.0
                r, g, b = 1.0, 0.85, 0.35
            i = (y * size + x) * 4
            pixels[i:i + 4] = [r, g, b, a]
    img.pixels = pixels
    img.alpha_mode = "STRAIGHT"
    img.pack()
    return img


# ---------------------------------------------------------------------------
# Soft alpha-card clump (reads like painted grass, not hard spikes)
# ---------------------------------------------------------------------------

def make_clump_mesh(name: str, seed: int = 0) -> bpy.types.Object:
    """2–3 crossed cards — ~12 tris — shader does the painterly look."""
    rng = random.Random(seed)
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    uvs: list[tuple[float, float]] = []

    cards = 3
    for c in range(cards):
        yaw = c * (math.pi / cards) + rng.uniform(-0.15, 0.15)
        w = rng.uniform(0.28, 0.42)
        h = rng.uniform(0.28, 0.52)
        lean = rng.uniform(0.0, 0.05)
        cy, sy = math.cos(yaw), math.sin(yaw)
        # quad facing yaw
        local = [(-w, lean, 0), (w, lean, 0), (w, lean, h), (-w, lean, h)]
        base = len(verts)
        for lx, ly, lz in local:
            verts.append((lx * cy - ly * sy, lx * sy + ly * cy, lz))
        faces.append((base, base + 1, base + 2, base + 3))
        uvs.extend([(0, 0), (1, 0), (1, 1), (0, 1)])

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    # assign uvs per loop
    for li, loop in enumerate(mesh.loops):
        uv.data[li].uv = uvs[loop.vertex_index] if False else (0, 0)
    # Better: set by face corners sequentially
    for fi, poly in enumerate(mesh.polygons):
        for i, li in enumerate(poly.loop_indices):
            # each face has 4 corners matching uvs block
            uv.data[li].uv = [(0, 0), (1, 0), (1, 1), (0, 1)][i]

    obj = bpy.data.objects.new(name, mesh)
    scene_col = bpy.context.scene.collection
    scene_col.objects.link(obj)

    # Flat normals from plane
    plane = bpy.data.meshes.new(name + "_NPlane")
    plane.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    plane_obj = bpy.data.objects.new(name + "_NPlane", plane)
    scene_col.objects.link(plane_obj)
    dt = obj.modifiers.new("FlatNormal", "DATA_TRANSFER")
    dt.object = plane_obj
    dt.use_loop_data = True
    dt.data_types_loops = {"CUSTOM_NORMAL"}
    dt.loop_mapping = "NEAREST_POLYNOR"
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier="FlatNormal")
    bpy.data.objects.remove(plane_obj, do_unlink=True)
    bpy.data.meshes.remove(plane)
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


def make_flower_mesh(name: str) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    s = 0.16
    verts = [(-s, 0, 0), (s, 0, 0), (s, 0, s * 2), (-s, 0, s * 2)]
    faces = [(0, 1, 2, 3)]
    mesh.from_pydata(verts, [], faces)
    uv = mesh.uv_layers.new(name="UVMap")
    for i, li in enumerate(mesh.polygons[0].loop_indices):
        uv.data[li].uv = [(0, 0), (1, 0), (1, 1), (0, 1)][i]
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def build_collections():
    grass_col = bpy.data.collections.new("GrassClumps")
    flower_col = bpy.data.collections.new("Flowers")
    scene_col = bpy.context.scene.collection
    scene_col.children.link(grass_col)
    scene_col.children.link(flower_col)

    for i, seed in enumerate((1, 2, 3, 4)):
        clump = make_clump_mesh(f"Clump_{i}", seed=seed)
        scene_col.objects.unlink(clump)
        grass_col.objects.link(clump)
        clump.location = (0, 0, -40)

    flower = make_flower_mesh("Flower")
    scene_col.objects.unlink(flower)
    flower_col.objects.link(flower)
    flower.location = (0, 0, -40)
    return grass_col, flower_col


# ---------------------------------------------------------------------------
# Ground + mask
# ---------------------------------------------------------------------------

def create_ground(size=8.0, cuts=64) -> bpy.types.Object:
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=cuts, y_subdivisions=cuts, size=size)
    ground = bpy.context.active_object
    ground.name = "Ground"
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    mesh = ground.data

    attr = mesh.color_attributes.new(name=MASK_NAME, type="FLOAT_COLOR", domain="POINT")
    for i, v in enumerate(mesh.vertices):
        x, y = v.co.x, v.co.y
        # Winding dirt path (like the thumbnail)
        path = abs(y - 0.85 * math.sin(x * 0.7) - 0.25 * math.sin(x * 1.9 + 0.4))
        dirt = 1.0 - min(1.0, max(0.0, (path - 0.42) / 0.35))
        # Soft edge of patch
        edge = max(abs(x), abs(y)) / (size * 0.5)
        edge_fade = 1.0 if edge < 0.88 else max(0.0, 1.0 - (edge - 0.88) / 0.12)
        h = math.sin(x * 2.4 + y * 1.8) * 0.05
        grass = (1.0 - dirt + h) * edge_fade
        grass = max(0.0, min(1.0, grass))
        attr.data[i].color = (grass, grass, grass, 1.0)

    # UV unwrap for completeness
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66))
    bpy.ops.object.mode_set(mode="OBJECT")
    return ground


# ---------------------------------------------------------------------------
# Anime material — the heart of the look
# ---------------------------------------------------------------------------

def make_anime_material(
    disp_img: bpy.types.Image,
    card_img: bpy.types.Image,
    empty: bpy.types.Object,
) -> bpy.types.Material:
    mat = bpy.data.materials.new("AnimeGrass")
    mat.use_nodes = True
    mat.blend_method = "OPAQUE"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "NONE"
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = False

    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (1300, 40))

    # Field-scale painted detail (Empty object space)
    texcoord = node(nt, "ShaderNodeTexCoord", (-1100, 80))
    texcoord.object = empty
    mapping = node(nt, "ShaderNodeMapping", (-900, 80))
    mapping.inputs["Scale"].default_value = (0.25, 0.25, 0.25)
    link(nt, texcoord.outputs["Object"], mapping.inputs["Vector"])

    disp_tex = node(nt, "ShaderNodeTexImage", (-680, 80))
    disp_tex.image = disp_img
    disp_tex.interpolation = "Linear"
    link(nt, mapping.outputs["Vector"], disp_tex.inputs["Vector"])

    # Card albedo + alpha (UV)
    uv = node(nt, "ShaderNodeUVMap", (-1100, -280))
    card = node(nt, "ShaderNodeTexImage", (-880, -280))
    card.image = card_img
    card.interpolation = "Linear"
    link(nt, uv.outputs["UV"], card.inputs["Vector"])

    # --- PRIMARY look: painted shadow tones from field texture (like the video) ---
    # Dark green "hand paint shadow" vs bright lime, driven by disp blobs
    paint_ramp = node(nt, "ShaderNodeValToRGB", (-420, 300))
    paint_ramp.color_ramp.interpolation = "LINEAR"
    paint_ramp.color_ramp.elements[0].position = 0.15
    paint_ramp.color_ramp.elements[0].color = (0.10, 0.28, 0.09, 1)  # deep shadow green
    paint_ramp.color_ramp.elements[1].position = 0.85
    paint_ramp.color_ramp.elements[1].color = (0.78, 0.94, 0.32, 1)  # sun lime
    mid = paint_ramp.color_ramp.elements.new(0.45)
    mid.color = (0.28, 0.55, 0.14, 1)
    link(nt, disp_tex.outputs["Color"], paint_ramp.inputs["Fac"])

    # Soften card: use mostly painted field color, card only for alpha silhouette
    mix_card = node(nt, "ShaderNodeMix", (-180, 160), data_type="RGBA")
    mix_card.inputs["Factor"].default_value = 0.22
    link(nt, paint_ramp.outputs["Color"], mix_card.inputs["A"])
    link(nt, card.outputs["Color"], mix_card.inputs["B"])

    mix_d = node(nt, "ShaderNodeMix", (-420, -40), data_type="RGBA")
    mix_d.inputs["A"].default_value = (0.76, 0.62, 0.40, 1)
    mix_d.inputs["B"].default_value = (0.52, 0.40, 0.26, 1)
    link(nt, disp_tex.outputs["Color"], mix_d.inputs["Factor"])

    attr_mask = node(nt, "ShaderNodeAttribute", (-680, -120))
    attr_mask.attribute_name = MASK_NAME

    mix_terrain = node(nt, "ShaderNodeMix", (40, 80), data_type="RGBA")
    link(nt, attr_mask.outputs["Color"], mix_terrain.inputs["Factor"])
    link(nt, mix_d.outputs["Result"], mix_terrain.inputs["A"])
    link(nt, mix_card.outputs["Result"], mix_terrain.inputs["B"])

    attr_wind = node(nt, "ShaderNodeAttribute", (-200, -220))
    attr_wind.attribute_name = WIND_ATTR
    wind_mul = node(nt, "ShaderNodeMath", (40, -220), operation="MULTIPLY")
    wind_mul.inputs[1].default_value = 0.35
    link(nt, attr_wind.outputs["Fac"], wind_mul.inputs[0])
    mix_wind = node(nt, "ShaderNodeMix", (260, 20), data_type="RGBA")
    mix_wind.inputs["B"].default_value = (0.12, 0.30, 0.10, 1)
    link(nt, wind_mul.outputs["Value"], mix_wind.inputs["Factor"])
    link(nt, mix_terrain.outputs["Result"], mix_wind.inputs["A"])

    # Secondary lighting cel (subtle) on top of painted tones
    bump = node(nt, "ShaderNodeBump", (-200, -400))
    bump.inputs["Strength"].default_value = 0.55
    bump.inputs["Distance"].default_value = 0.8
    link(nt, disp_tex.outputs["Color"], bump.inputs["Height"])

    diffuse = node(nt, "ShaderNodeBsdfDiffuse", (40, -400))
    diffuse.inputs["Color"].default_value = (1, 1, 1, 1)
    link(nt, bump.outputs["Normal"], diffuse.inputs["Normal"])
    sh2rgb = node(nt, "ShaderNodeShaderToRGB", (260, -400))
    link(nt, diffuse.outputs["BSDF"], sh2rgb.inputs["Shader"])

    cel = node(nt, "ShaderNodeValToRGB", (480, -400))
    cel.color_ramp.interpolation = "CONSTANT"
    cel.color_ramp.elements[0].position = 0.0
    cel.color_ramp.elements[0].color = (0.55, 0.50, 0.72, 1)  # soft cool shadow multiply
    cel.color_ramp.elements[1].position = 0.45
    cel.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1)
    link(nt, sh2rgb.outputs["Color"], cel.inputs["Fac"])

    mix_shade = node(nt, "ShaderNodeMix", (760, 0), data_type="RGBA", blend_type="MULTIPLY")
    mix_shade.inputs["Factor"].default_value = 1.0
    link(nt, mix_wind.outputs["Result"], mix_shade.inputs["A"])
    link(nt, cel.outputs["Color"], mix_shade.inputs["B"])

    emission = node(nt, "ShaderNodeEmission", (980, 40))
    emission.inputs["Strength"].default_value = 1.0
    link(nt, mix_shade.outputs["Result"], emission.inputs["Color"])

    sep_m = node(nt, "ShaderNodeSeparateColor", (480, -200))
    link(nt, attr_mask.outputs["Color"], sep_m.inputs["Color"])
    mix_a = node(nt, "ShaderNodeMix", (760, -120), data_type="FLOAT")
    mix_a.inputs["A"].default_value = 1.0
    link(nt, card.outputs["Alpha"], mix_a.inputs["B"])
    link(nt, sep_m.outputs["Red"], mix_a.inputs["Factor"])

    link(nt, emission.outputs["Emission"], out.inputs["Surface"])
    return mat


def make_flower_material(flower_img: bpy.types.Image) -> bpy.types.Material:
    mat = bpy.data.materials.new("AnimeFlower")
    mat.use_nodes = True
    mat.blend_method = "OPAQUE"
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = False
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (500, 0))
    uv = node(nt, "ShaderNodeUVMap", (-200, 40))
    tex = node(nt, "ShaderNodeTexImage", (0, 40))
    tex.image = flower_img
    link(nt, uv.outputs["UV"], tex.inputs["Vector"])
    emit = node(nt, "ShaderNodeEmission", (220, 60))
    link(nt, tex.outputs["Color"], emit.inputs["Color"])
    emit.inputs["Strength"].default_value = 1.0
    transparent = node(nt, "ShaderNodeBsdfTransparent", (220, -80))
    mix = node(nt, "ShaderNodeMixShader", (360, 0))
    link(nt, tex.outputs["Alpha"], mix.inputs["Fac"])
    link(nt, transparent.outputs["BSDF"], mix.inputs[1])
    link(nt, emit.outputs["Emission"], mix.inputs[2])
    link(nt, mix.outputs["Shader"], out.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# Geometry Nodes
# ---------------------------------------------------------------------------

def build_grass_nodes(grass_col, flower_col, grass_mat, flower_mat):
    nt = bpy.data.node_groups.new("AnimeGrass", "GeometryNodeTree")
    add_socket(nt, "Geometry", "INPUT", "NodeSocketGeometry")
    add_socket(nt, "Density", "INPUT", "NodeSocketFloat", 70.0, 1.0, 250.0)
    add_socket(nt, "Scale", "INPUT", "NodeSocketFloat", 1.0, 0.2, 3.0)
    add_socket(nt, "Flower Density", "INPUT", "NodeSocketFloat", 2.5, 0.0, 20.0)
    add_socket(nt, "Wind Speed", "INPUT", "NodeSocketFloat", 0.45, 0.0, 3.0)
    add_socket(nt, "Wind Strength", "INPUT", "NodeSocketFloat", 0.35, 0.0, 1.5)
    add_socket(nt, "Seed", "INPUT", "NodeSocketInt", 5, 0, 9999)
    add_socket(nt, "Geometry", "OUTPUT", "NodeSocketGeometry")

    nin = node(nt, "NodeGroupInput", (-1900, 40))
    nout = node(nt, "NodeGroupOutput", (1700, 40))

    named = node(nt, "GeometryNodeInputNamedAttribute", (-1700, -240), data_type="FLOAT_COLOR")
    named.inputs["Name"].default_value = MASK_NAME
    sep = node(nt, "FunctionNodeSeparateColor", (-1500, -240))
    link(nt, named.outputs["Attribute"], sep.inputs["Color"])
    mask = sep.outputs["Red"]

    dens = node(nt, "ShaderNodeMath", (-1500, 140), operation="MULTIPLY")
    link(nt, nin.outputs["Density"], dens.inputs[0])
    link(nt, mask, dens.inputs[1])

    dist = node(nt, "GeometryNodeDistributePointsOnFaces", (-1280, 160))
    dist.distribute_method = "RANDOM"
    link(nt, nin.outputs["Geometry"], dist.inputs["Mesh"])
    link(nt, dens.outputs["Value"], dist.inputs["Density"])
    link(nt, nin.outputs["Seed"], dist.inputs["Seed"])

    # Wind field
    scene_time = node(nt, "GeometryNodeInputSceneTime", (-1700, -480))
    pos = node(nt, "GeometryNodeInputPosition", (-1700, -600))
    wspeed = node(nt, "ShaderNodeMath", (-1500, -520), operation="MULTIPLY")
    link(nt, scene_time.outputs["Seconds"], wspeed.inputs[0])
    link(nt, nin.outputs["Wind Speed"], wspeed.inputs[1])

    wave = node(nt, "ShaderNodeTexNoise", (-1280, -420))
    wave.noise_dimensions = "4D"
    wave.inputs["Scale"].default_value = 0.28
    wave.inputs["Detail"].default_value = 1.0
    link(nt, pos.outputs["Position"], wave.inputs["Vector"])
    link(nt, wspeed.outputs["Value"], wave.inputs["W"])

    flutter = node(nt, "ShaderNodeTexNoise", (-1280, -620))
    flutter.noise_dimensions = "4D"
    flutter.inputs["Scale"].default_value = 1.4
    link(nt, pos.outputs["Position"], flutter.inputs["Vector"])
    w2 = node(nt, "ShaderNodeMath", (-1500, -700), operation="MULTIPLY")
    w2.inputs[1].default_value = 2.2
    link(nt, wspeed.outputs["Value"], w2.inputs[0])
    link(nt, w2.outputs["Value"], flutter.inputs["W"])

    fl = node(nt, "ShaderNodeMath", (-1080, -580), operation="MULTIPLY")
    fl.inputs[1].default_value = 0.25
    link(nt, flutter.outputs["Fac"], fl.inputs[0])
    mixw = node(nt, "ShaderNodeMath", (-1080, -440), operation="ADD")
    link(nt, wave.outputs["Fac"], mixw.inputs[0])
    link(nt, fl.outputs["Value"], mixw.inputs[1])
    # remap 0-1 centered
    centered = node(nt, "ShaderNodeMath", (-900, -440), operation="SUBTRACT")
    centered.inputs[1].default_value = 0.5
    link(nt, mixw.outputs["Value"], centered.inputs[0])
    wind = node(nt, "ShaderNodeMath", (-720, -440), operation="MULTIPLY")
    link(nt, centered.outputs["Value"], wind.inputs[0])
    link(nt, nin.outputs["Wind Strength"], wind.inputs[1])

    # Store absolute wind for shader (0-1)
    wind_abs = node(nt, "ShaderNodeMath", (-720, -560), operation="ABSOLUTE")
    link(nt, wind.outputs["Value"], wind_abs.inputs[0])
    store = node(nt, "GeometryNodeStoreNamedAttribute", (-720, 80), data_type="FLOAT", domain="POINT")
    store.inputs["Name"].default_value = WIND_ATTR
    link(nt, dist.outputs["Points"], store.inputs["Geometry"])
    link(nt, wind_abs.outputs["Value"], store.inputs["Value"])

    colinfo = node(nt, "GeometryNodeCollectionInfo", (-720, -120), transform_space="ORIGINAL")
    colinfo.inputs["Collection"].default_value = grass_col
    colinfo.inputs["Separate Children"].default_value = True
    colinfo.inputs["Reset Children"].default_value = True

    align = node(nt, "FunctionNodeAlignEulerToVector", (-500, 220), axis="Z")
    link(nt, dist.outputs["Normal"], align.inputs["Vector"])

    idn = node(nt, "GeometryNodeInputID", (-720, -280))
    rand_yaw = node(nt, "FunctionNodeRandomValue", (-500, -40), data_type="FLOAT")
    rand_yaw.inputs["Min"].default_value = 0.0
    rand_yaw.inputs["Max"].default_value = math.tau
    link(nt, idn.outputs["ID"], rand_yaw.inputs["ID"])
    link(nt, nin.outputs["Seed"], rand_yaw.inputs["Seed"])
    yaw = node(nt, "ShaderNodeCombineXYZ", (-300, -40))
    link(nt, rand_yaw.outputs["Value"], yaw.inputs["Z"])

    sample = node(nt, "GeometryNodeSampleNearestSurface", (-500, -260), data_type="FLOAT")
    link(nt, nin.outputs["Geometry"], sample.inputs["Mesh"])
    link(nt, mask, sample.inputs["Value"])
    link(nt, pos.outputs["Position"], sample.inputs["Sample Position"])

    rand_s = node(nt, "FunctionNodeRandomValue", (-500, -480), data_type="FLOAT")
    rand_s.inputs["Min"].default_value = 0.55
    rand_s.inputs["Max"].default_value = 1.55
    link(nt, idn.outputs["ID"], rand_s.inputs["ID"])
    seed2 = node(nt, "ShaderNodeMath", (-720, -540), operation="ADD")
    seed2.inputs[1].default_value = 21
    link(nt, nin.outputs["Seed"], seed2.inputs[0])
    link(nt, seed2.outputs["Value"], rand_s.inputs["Seed"])

    s1 = node(nt, "ShaderNodeMath", (-300, -400), operation="MULTIPLY")
    link(nt, rand_s.outputs["Value"], s1.inputs[0])
    link(nt, nin.outputs["Scale"], s1.inputs[1])
    s2 = node(nt, "ShaderNodeMath", (-140, -400), operation="MULTIPLY")
    link(nt, s1.outputs["Value"], s2.inputs[0])
    link(nt, sample.outputs["Value"], s2.inputs[1])
    svec = node(nt, "ShaderNodeCombineXYZ", (40, -400))
    link(nt, s2.outputs["Value"], svec.inputs[0])
    link(nt, s2.outputs["Value"], svec.inputs[1])
    link(nt, s2.outputs["Value"], svec.inputs[2])

    rand_i = node(nt, "FunctionNodeRandomValue", (-300, -180), data_type="INT")
    for sock in rand_i.inputs:
        if sock.name == "Min" and sock.type == "INT":
            sock.default_value = 0
        if sock.name == "Max" and sock.type == "INT":
            sock.default_value = 3
    link(nt, idn.outputs["ID"], rand_i.inputs["ID"])
    link(nt, nin.outputs["Seed"], rand_i.inputs["Seed"])

    iop = node(nt, "GeometryNodeInstanceOnPoints", (40, 120))
    link(nt, store.outputs["Geometry"], iop.inputs["Points"])
    link(nt, colinfo.outputs["Instances"], iop.inputs["Instance"])
    iop.inputs["Pick Instance"].default_value = True
    link(nt, rand_i.outputs["Value"], iop.inputs["Instance Index"])
    link(nt, align.outputs["Rotation"], iop.inputs["Rotation"])
    link(nt, svec.outputs["Vector"], iop.inputs["Scale"])

    rot_yaw = node(nt, "GeometryNodeRotateInstances", (260, 120))
    link(nt, iop.outputs["Instances"], rot_yaw.inputs["Instances"])
    link(nt, yaw.outputs["Vector"], rot_yaw.inputs["Rotation"])

    wind_e = node(nt, "ShaderNodeCombineXYZ", (260, -200))
    link(nt, wind.outputs["Value"], wind_e.inputs["X"])
    wz = node(nt, "ShaderNodeMath", (80, -280), operation="MULTIPLY")
    wz.inputs[1].default_value = 0.35
    link(nt, wind.outputs["Value"], wz.inputs[0])
    link(nt, wz.outputs["Value"], wind_e.inputs["Z"])
    rot_wind = node(nt, "GeometryNodeRotateInstances", (480, 80))
    link(nt, rot_yaw.outputs["Instances"], rot_wind.inputs["Instances"])
    link(nt, wind_e.outputs["Vector"], rot_wind.inputs["Rotation"])

    realize = node(nt, "GeometryNodeRealizeInstances", (700, 80))
    link(nt, rot_wind.outputs["Instances"], realize.inputs["Geometry"])
    set_mat = node(nt, "GeometryNodeSetMaterial", (900, 80))
    set_mat.inputs["Material"].default_value = grass_mat
    link(nt, realize.outputs["Geometry"], set_mat.inputs["Geometry"])

    # Flowers (sparse)
    fdens = node(nt, "ShaderNodeMath", (-1500, -800), operation="MULTIPLY")
    link(nt, nin.outputs["Flower Density"], fdens.inputs[0])
    link(nt, mask, fdens.inputs[1])
    fdist = node(nt, "GeometryNodeDistributePointsOnFaces", (-1280, -800))
    fdist.distribute_method = "RANDOM"
    link(nt, nin.outputs["Geometry"], fdist.inputs["Mesh"])
    link(nt, fdens.outputs["Value"], fdist.inputs["Density"])
    fseed = node(nt, "ShaderNodeMath", (-1500, -900), operation="ADD")
    fseed.inputs[1].default_value = 77
    link(nt, nin.outputs["Seed"], fseed.inputs[0])
    link(nt, fseed.outputs["Value"], fdist.inputs["Seed"])

    fcol = node(nt, "GeometryNodeCollectionInfo", (-1000, -800), transform_space="ORIGINAL")
    fcol.inputs["Collection"].default_value = flower_col
    fcol.inputs["Separate Children"].default_value = True
    fcol.inputs["Reset Children"].default_value = True
    falign = node(nt, "FunctionNodeAlignEulerToVector", (-800, -720), axis="Z")
    link(nt, fdist.outputs["Normal"], falign.inputs["Vector"])
    fiop = node(nt, "GeometryNodeInstanceOnPoints", (-600, -800))
    link(nt, fdist.outputs["Points"], fiop.inputs["Points"])
    link(nt, fcol.outputs["Instances"], fiop.inputs["Instance"])
    link(nt, falign.outputs["Rotation"], fiop.inputs["Rotation"])
    # random flower scale
    fid = node(nt, "GeometryNodeInputID", (-1000, -920))
    frs = node(nt, "FunctionNodeRandomValue", (-800, -920), data_type="FLOAT")
    frs.inputs["Min"].default_value = 0.7
    frs.inputs["Max"].default_value = 1.4
    link(nt, fid.outputs["ID"], frs.inputs["ID"])
    link(nt, fseed.outputs["Value"], frs.inputs["Seed"])
    link(nt, frs.outputs["Value"], fiop.inputs["Scale"])
    freal = node(nt, "GeometryNodeRealizeInstances", (-400, -800))
    link(nt, fiop.outputs["Instances"], freal.inputs["Geometry"])
    fmat = node(nt, "GeometryNodeSetMaterial", (-200, -800))
    fmat.inputs["Material"].default_value = flower_mat
    link(nt, freal.outputs["Geometry"], fmat.inputs["Geometry"])

    ground_mat = node(nt, "GeometryNodeSetMaterial", (900, -80))
    ground_mat.inputs["Material"].default_value = grass_mat
    link(nt, nin.outputs["Geometry"], ground_mat.inputs["Geometry"])

    join = node(nt, "GeometryNodeJoinGeometry", (1200, 20))
    link(nt, ground_mat.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, set_mat.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, fmat.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, join.outputs["Geometry"], nout.inputs["Geometry"])
    return nt


def build_detail_nodes(disp_img: bpy.types.Image):
    """Strong displacement for field-scale shadow baking."""
    nt = bpy.data.node_groups.new("GrassDetail", "GeometryNodeTree")
    add_socket(nt, "Geometry", "INPUT", "NodeSocketGeometry")
    add_socket(nt, "Height", "INPUT", "NodeSocketFloat", 0.85, 0.0, 3.0)
    add_socket(nt, "Geometry", "OUTPUT", "NodeSocketGeometry")
    nin = node(nt, "NodeGroupInput", (-700, 0))
    nout = node(nt, "NodeGroupOutput", (600, 0))

    named = node(nt, "GeometryNodeInputNamedAttribute", (-500, -200), data_type="FLOAT_COLOR")
    named.inputs["Name"].default_value = MASK_NAME
    sep = node(nt, "FunctionNodeSeparateColor", (-300, -200))
    link(nt, named.outputs["Attribute"], sep.inputs["Color"])

    pos = node(nt, "GeometryNodeInputPosition", (-500, 120))
    # Use image texture in GN
    img = node(nt, "GeometryNodeImageTexture", (-300, 120))
    img.inputs["Image"].default_value = disp_img
    # map position XY to 0-1-ish
    scale = node(nt, "ShaderNodeVectorMath", (-500, 0), operation="SCALE")
    scale.inputs["Scale"].default_value = 0.12
    link(nt, pos.outputs["Position"], scale.inputs[0])
    link(nt, scale.outputs["Vector"], img.inputs["Vector"])

    # Separate color
    sep2 = node(nt, "FunctionNodeSeparateColor", (-100, 120))
    link(nt, img.outputs["Color"], sep2.inputs["Color"])

    blur = node(nt, "GeometryNodeBlurAttribute", (80, 80), data_type="FLOAT")
    blur.inputs["Iterations"].default_value = 4
    link(nt, sep2.outputs["Red"], blur.inputs["Value"])

    h = node(nt, "ShaderNodeMath", (280, 80), operation="MULTIPLY")
    link(nt, blur.outputs["Value"], h.inputs[0])
    link(nt, nin.outputs["Height"], h.inputs[1])
    h2 = node(nt, "ShaderNodeMath", (440, 40), operation="MULTIPLY")
    link(nt, h.outputs["Value"], h2.inputs[0])
    link(nt, sep.outputs["Red"], h2.inputs[1])
    comb = node(nt, "ShaderNodeCombineXYZ", (440, -100))
    link(nt, h2.outputs["Value"], comb.inputs["Z"])
    setpos = node(nt, "GeometryNodeSetPosition", (200, -200))
    link(nt, nin.outputs["Geometry"], setpos.inputs["Geometry"])
    link(nt, comb.outputs["Vector"], setpos.inputs["Offset"])
    # Subdivide detail for smoother normals
    sub = node(nt, "GeometryNodeSubdivideMesh", (0, -200))
    sub.inputs["Level"].default_value = 1
    link(nt, nin.outputs["Geometry"], sub.inputs["Mesh"])
    # rebuild: subdivide first
    for l in list(nt.links):
        if l.to_node == setpos and l.to_socket.name == "Geometry":
            nt.links.remove(l)
    link(nt, sub.outputs["Mesh"], setpos.inputs["Geometry"])
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
    # Soft off-white / sky like thumbnail
    bg.inputs["Color"].default_value = (0.78, 0.88, 0.95, 1)
    bg.inputs["Strength"].default_value = 0.55
    link(nt, bg.outputs["Background"], out.inputs["Surface"])

    empty = bpy.data.objects.new("TexSync", None)
    empty.empty_display_type = "CUBE"
    empty.empty_display_size = 2.5
    empty.scale = (2.5, 2.5, 2.5)
    bpy.context.collection.objects.link(empty)

    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam)
    cam_data.lens = 50
    # Isometric-ish diamond framing like the thumbnail
    # Slightly lower angle so grass reads as volume, not a flat hedge top
    cam.location = (6.4, -7.6, 5.2)
    cam.rotation_euler = Euler((math.radians(58), 0, math.radians(42)), "XYZ")
    bpy.context.scene.camera = cam

    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    bpy.context.collection.objects.link(sun)
    # Strong angled light for clear cel bands
    sun.rotation_euler = Euler((math.radians(35), math.radians(8), math.radians(120)), "XYZ")
    sun.data.energy = 6.0
    sun.data.angle = math.radians(1.5)
    sun.data.color = (1.0, 0.98, 0.92)

    fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", "AREA"))
    bpy.context.collection.objects.link(fill)
    fill.location = (-4, -3, 4)
    fill.rotation_euler = Euler((math.radians(60), 0, math.radians(-40)), "XYZ")
    fill.data.energy = 15
    fill.data.size = 8
    fill.data.color = (0.75, 0.82, 1.0)
    return cam, empty


def configure_render(scene):
    engines = {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1600
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    if hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 64
    if hasattr(scene.eevee, "use_shadows"):
        scene.eevee.use_shadows = True
    scene.frame_start = 1
    scene.frame_end = 48
    scene.render.fps = 24


def enable_custom_normals(obj):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    try:
        bpy.ops.object.shade_smooth()
    except Exception:
        pass
    if hasattr(obj.data, "use_auto_smooth"):
        obj.data.use_auto_smooth = True
        obj.data.auto_smooth_angle = math.radians(180)
    # Blender 4.1+ Smooth by Angle modifier as auto-smooth replacement
    if "Smooth by Angle" not in obj.modifiers and hasattr(bpy.types, "NodesModifier"):
        try:
            # Try adding via operator
            bpy.ops.object.modifier_add_node_group(
                asset_library_type="ESSENTIALS",
                asset_library_identifier="",
                relative_asset_identifier="geometry_nodes/smooth_by_angle.blend/NodeTree/Smooth by Angle",
            )
        except Exception:
            pass
    try:
        bpy.ops.mesh.customdata_custom_splitnormals_add()
    except Exception:
        pass
    obj.select_set(False)


def animate_wind_only(obj):
    # Subtle wind strength breathing
    set_mod_input(obj, "AnimeGrass", "Wind Strength", 0.25, 1)
    set_mod_input(obj, "AnimeGrass", "Wind Strength", 0.45, 24)
    set_mod_input(obj, "AnimeGrass", "Wind Strength", 0.3, 48)


def render_still(scene, path: Path, frame: int):
    scene.frame_set(frame)
    scene.render.filepath = str(path)
    log(f"RENDER {path.name} @ {frame}")
    bpy.ops.render.render(write_still=True)


def build():
    log("Clearing…")
    clear_scene()
    log("Displacement map…")
    disp_img = make_displacement_image(512)
    log("Card textures…")
    card_img = make_grass_card_image(256)
    flower_img = make_flower_card_image(128)
    log("Clump assets…")
    grass_col, flower_col = build_collections()
    log("Ground…")
    ground = create_ground()
    cam, empty = setup_scene()
    grass_mat = make_anime_material(disp_img, card_img, empty)
    flower_mat = make_flower_material(flower_img)
    ground.data.materials.append(grass_mat)
    ground.data.materials.append(flower_mat)

    log("Grass GN…")
    nt = build_grass_nodes(grass_col, flower_col, grass_mat, flower_mat)
    gmod = ground.modifiers.new("AnimeGrass", "NODES")
    gmod.node_group = nt

    log("Detail mesh…")
    detail = ground.copy()
    detail.data = ground.data.copy()
    detail.name = "GrassDetail"
    bpy.context.collection.objects.link(detail)
    detail.modifiers.clear()
    dnt = build_detail_nodes(disp_img)
    dmod = detail.modifiers.new("GrassDetail", "NODES")
    dmod.node_group = dnt
    set_mod_input(detail, "GrassDetail", "Height", 1.1)
    detail.hide_render = True
    detail.hide_viewport = True

    log("Normal bake transfer…")
    enable_custom_normals(ground)
    tmod = ground.modifiers.new("NormalBake", "DATA_TRANSFER")
    tmod.object = detail
    tmod.use_loop_data = True
    tmod.data_types_loops = {"CUSTOM_NORMAL"}
    tmod.loop_mapping = "NEAREST_POLYNOR"
    tmod.use_object_transform = True

    if hasattr(ground, "visible_shadow"):
        ground.visible_shadow = False

    configure_render(bpy.context.scene)
    animate_wind_only(ground)

    set_mod_input(ground, "AnimeGrass", "Density", 120.0)
    set_mod_input(ground, "AnimeGrass", "Scale", 1.15)
    set_mod_input(ground, "AnimeGrass", "Flower Density", 2.2)
    set_mod_input(ground, "AnimeGrass", "Wind Speed", 0.5)
    set_mod_input(ground, "AnimeGrass", "Wind Strength", 0.35)

    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    deps = bpy.context.evaluated_depsgraph_get()
    ev = ground.evaluated_get(deps)
    m = ev.to_mesh()
    log(f"Evaluated verts: {len(m.vertices)}")
    ev.to_mesh_clear()

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
        scene.render.resolution_x = 1600
        scene.render.resolution_y = 1600

    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    log(f"SAVED {BLEND_PATH}")


if __name__ == "__main__":
    try:
        build()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
