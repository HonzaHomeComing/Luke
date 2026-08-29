"""
Anime Grass — 2026 Trung Duy Nguyen workflow (Blender 5.x)

- Scatter on Surface (essentials asset)
- Double-sided blade + Data Transfer flat normals from a plane
- Diffuse → Shader to RGB cel
- World-space normal map via Empty (object coords) + noise blur
- Mix world + tangent normals (Linear Light)
- Texture mask (instances stay light — no Realize)
- Simple wind injected into Scatter's Instance on Points rotation
- Shadows off

  /path/to/blender-5.2+ --background --factory-startup \\
      --python anime-grass/build_anime_grass.py -- --stills-only
"""

from __future__ import annotations

import math
import struct
import sys
import traceback
import zlib
from pathlib import Path

import bpy
from mathutils import Euler, Vector

ROOT = Path(__file__).resolve().parent
BLEND_PATH = ROOT / "anime_grass.blend"
RENDER_DIR = ROOT / "renders"
NORMAL_PATH = ROOT / "textures" / "grass_normal.png"
MASK_PATH = ROOT / "textures" / "grass_mask.png"
ESSENTIALS = Path(bpy.path.abspath("//"))  # placeholder; resolved at runtime

MASK_NAME = "Grass"
WIND_ATTR = "wind"


def log(msg: str) -> None:
    print(msg, flush=True)


def essentials_path() -> Path:
    ver = f"{bpy.app.version[0]}.{bpy.app.version[1]}"
    # Blender binary sibling datafiles
    for base in (
        Path(bpy.app.binary_path).resolve().parent / ver / "datafiles" / "assets" / "nodes",
        Path(f"/tmp/blender-{ver}.1-linux-x64") / ver / "datafiles" / "assets" / "nodes",
        Path("/tmp/blender-5.2.1-linux-x64/5.2/datafiles/assets/nodes"),
    ):
        p = base / "geometry_nodes_essentials.blend"
        if p.exists():
            return p
    raise FileNotFoundError("geometry_nodes_essentials.blend not found")


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
            try:
                coll.remove(block)
            except Exception:
                pass
    master = bpy.context.scene.collection
    for block in list(bpy.data.collections):
        if block == master:
            continue
        try:
            bpy.data.collections.remove(block)
        except Exception:
            pass


def scene_col():
    return bpy.context.scene.collection


def link(nt, a, b):
    nt.links.new(a, b)


def node(nt, bl_idname, loc=(0, 0), **kwargs):
    n = nt.nodes.new(bl_idname)
    n.location = loc
    for k, v in kwargs.items():
        if hasattr(n, k):
            setattr(n, k, v)
    return n


def write_png_gray(path: Path, w: int, h: int, pixels: list[float]) -> None:
    """Minimal grayscale PNG writer (no Pillow). pixels 0..1 row-major top-left."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter none
        row = y  # already top-to-bottom for our painter
        for x in range(w):
            v = int(max(0, min(1, pixels[row * w + x])) * 255)
            raw.extend((v, v, v))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit RGB
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def make_path_mask(path: Path, size: int = 1024) -> Path:
    """S-curve dirt path (black) through grass (white) — matches our meadow."""
    pix = [1.0] * (size * size)
    for y in range(size):
        t = y / (size - 1)
        cx = 0.5 + 0.22 * math.sin(t * math.pi * 2.0)
        half = 0.07 + 0.02 * math.sin(t * math.pi * 3)
        for x in range(size):
            u = x / (size - 1)
            d = abs(u - cx)
            # soft edge
            if d < half:
                pix[y * size + x] = 0.0
            elif d < half + 0.03:
                pix[y * size + x] = (d - half) / 0.03
    write_png_gray(path, size, size, pix)
    return path


def load_image(path: Path, name: str, non_color: bool = True) -> bpy.types.Image:
    img = bpy.data.images.load(str(path))
    img.name = name
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    if img.packed_file is None:
        img.pack()
    return img


# ---------------------------------------------------------------------------
# Single double-sided blade with flat transferred normals (2026 tutorial)
# ---------------------------------------------------------------------------

def make_grass_blade() -> bpy.types.Object:
    # Simple tapered blade (YZ plane-ish)
    h, w = 0.55, 0.045
    verts = [
        (-w, 0, 0),
        (w, 0, 0),
        (-w * 0.85, 0.04, h * 0.45),
        (w * 0.85, 0.04, h * 0.45),
        (-w * 0.35, 0.08, h * 0.8),
        (w * 0.35, 0.08, h * 0.8),
        (0.0, 0.11, h),
    ]
    faces = [(0, 1, 3, 2), (2, 3, 5, 4), (4, 5, 6)]
    mesh = bpy.data.meshes.new("GrassBladeMesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("GrassBlade", mesh)
    bpy.context.scene.collection.objects.link(obj)

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    # Double face
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.duplicate()
    bpy.ops.mesh.flip_normals()
    bpy.ops.transform.shrink_fatten(value=0.005)
    bpy.ops.object.mode_set(mode="OBJECT")

    # Flat painterly normals from a plane
    bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, 0))
    plane = bpy.context.active_object
    plane.name = "NormalSource"
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    dt = obj.modifiers.new("FlatN", "DATA_TRANSFER")
    dt.object = plane
    dt.use_loop_data = True
    dt.data_types_loops = {"CUSTOM_NORMAL"}
    dt.loop_mapping = "NEAREST_POLYNOR"
    bpy.ops.object.modifier_apply(modifier="FlatN")
    bpy.data.objects.remove(plane, do_unlink=True)

    bpy.ops.object.shade_smooth()
    if hasattr(mesh, "use_auto_smooth"):
        mesh.use_auto_smooth = True
        mesh.auto_smooth_angle = math.radians(180)
    try:
        bpy.ops.mesh.customdata_custom_splitnormals_add()
    except Exception:
        pass

    # Origin at root, apply scale
    obj.scale = (0.85, 0.85, 0.85)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.select_set(False)
    return obj


def make_flower() -> bpy.types.Object:
    mesh = bpy.data.meshes.new("FlowerMesh")
    verts = [(0, 0, 0.02)]
    faces = []
    for i in range(5):
        a0 = i * math.tau / 5
        a1 = (i + 0.5) * math.tau / 5
        a2 = (i + 1) * math.tau / 5
        for a, r, z in ((a0, 0.035, 0.02), (a1, 0.09, 0.045), (a2, 0.035, 0.02)):
            verts.append((math.cos(a) * r, math.sin(a) * r, z))
        b = 1 + i * 3
        faces.append((0, b, b + 1, b + 2))
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Flower", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def create_ground(size=8.0, cuts=96):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=cuts, y_subdivisions=cuts, size=size)
    ground = bpy.context.active_object
    ground.name = "Ground"
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    # Mild hill
    mesh = ground.data
    for v in mesh.vertices:
        x, y = v.co.x, v.co.y
        v.co.z = 0.15 * math.sin(x * 0.55) * math.cos(y * 0.45) + 0.08 * math.sin((x + y) * 0.35)
    mesh.update()

    # Top-view UV (Project from view bounds equivalent)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.cube_project(cube_size=size)
    bpy.ops.object.mode_set(mode="OBJECT")
    # Remap UV to 0..1 from XY bounds
    uv = mesh.uv_layers.new(name="UVMap") if not mesh.uv_layers else mesh.uv_layers.active
    for loop in mesh.loops:
        co = mesh.vertices[loop.vertex_index].co
        uv.data[loop.index].uv = ((co.x / size) + 0.5, (co.y / size) + 0.5)

    # Color attribute for optional painting (also used to seed mask bake conceptually)
    attr = mesh.color_attributes.new(name=MASK_NAME, type="FLOAT_COLOR", domain="POINT")
    for i, v in enumerate(mesh.vertices):
        x, y = v.co.x, v.co.y
        t = (y / size) + 0.5
        cx = 0.0 + 1.6 * math.sin(t * math.pi * 2.0)
        half = 0.55
        d = abs(x - cx)
        g = 0.0 if d < half else min(1.0, (d - half) / 0.35)
        attr.data[i].color = (g, g, g, 1.0)
    return ground


# ---------------------------------------------------------------------------
# Material — 2026: Diffuse→S2RGB + world normal + blur + tangent mix
# ---------------------------------------------------------------------------

def make_shared_material(normal_img, mask_img, empty) -> bpy.types.Material:
    mat = bpy.data.materials.new("AnimeGrass2026")
    mat.use_nodes = True
    mat.blend_method = "OPAQUE"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "NONE"
    if hasattr(mat, "use_transparent_shadow"):
        mat.use_transparent_shadow = False

    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (1400, 40))

    # --- Object-space projection via Empty (TexSync) ---
    texcoord = node(nt, "ShaderNodeTexCoord", (-1200, 80))
    texcoord.object = empty
    mapping = node(nt, "ShaderNodeMapping", (-1000, 80))
    mapping.inputs["Scale"].default_value = (0.12, 0.12, 0.12)
    link(nt, texcoord.outputs["Object"], mapping.inputs["Vector"])

    ntex = node(nt, "ShaderNodeTexImage", (-780, 120))
    ntex.image = normal_img
    ntex.interpolation = "Cubic"
    link(nt, mapping.outputs["Vector"], ntex.inputs["Vector"])

    # Blur trick: high-frequency noise + Linear Light mix
    noise = node(nt, "ShaderNodeTexNoise", (-780, -120))
    noise.inputs["Scale"].default_value = 20000.0
    noise.inputs["Detail"].default_value = 0.0
    blur = node(nt, "ShaderNodeMix", (-560, 40), data_type="RGBA", blend_type="LINEAR_LIGHT")
    blur.inputs["Factor"].default_value = 0.02
    link(nt, ntex.outputs["Color"], blur.inputs["A"])
    link(nt, noise.outputs["Color"], blur.inputs["B"])

    nmap_world = node(nt, "ShaderNodeNormalMap", (-340, 80))
    nmap_world.space = "WORLD"
    nmap_world.inputs["Strength"].default_value = 1.6
    link(nt, blur.outputs["Result"], nmap_world.inputs["Color"])

    nmap_tan = node(nt, "ShaderNodeNormalMap", (-340, -160))
    nmap_tan.space = "TANGENT"
    nmap_tan.inputs["Strength"].default_value = 1.0
    # flat / slight — use blurred map at low strength for ground shape hint
    link(nt, blur.outputs["Result"], nmap_tan.inputs["Color"])
    nmap_tan.inputs["Strength"].default_value = 0.35

    # Combine normals as colors via Linear Light (tutorial trick)
    ncomb = node(nt, "ShaderNodeMix", (-100, 0), data_type="RGBA", blend_type="LINEAR_LIGHT")
    ncomb.inputs["Factor"].default_value = 0.55
    link(nt, nmap_world.outputs["Normal"], ncomb.inputs["A"])
    link(nt, nmap_tan.outputs["Normal"], ncomb.inputs["B"])

    # Rebuild a normal-ish vector from mixed RGB: use as Normal via Normal Map again
    # Simpler: plug world normal into Diffuse; mix factor controls detail
    # Use Vector Mix instead if available
    try:
        vmix = node(nt, "ShaderNodeMix", (-100, -200), data_type="VECTOR", blend_type="LINEAR_LIGHT")
        vmix.inputs["Factor"].default_value = 0.25
        link(nt, nmap_world.outputs["Normal"], vmix.inputs["A"])
        link(nt, nmap_tan.outputs["Normal"], vmix.inputs["B"])
        normal_out = vmix.outputs["Result"]
    except Exception:
        normal_out = nmap_world.outputs["Normal"]

    # Grass cel colors
    diffuse_g = node(nt, "ShaderNodeBsdfDiffuse", (120, 120))
    diffuse_g.inputs["Color"].default_value = (1, 1, 1, 1)
    link(nt, normal_out, diffuse_g.inputs["Normal"])
    s2r_g = node(nt, "ShaderNodeShaderToRGB", (320, 120))
    link(nt, diffuse_g.outputs["BSDF"], s2r_g.inputs["Shader"])
    ramp_g = node(nt, "ShaderNodeValToRGB", (520, 120))
    ramp_g.color_ramp.interpolation = "CONSTANT"
    ramp_g.color_ramp.elements[0].position = 0.0
    ramp_g.color_ramp.elements[0].color = (0.22, 0.48, 0.14, 1)
    ramp_g.color_ramp.elements[1].position = 0.52
    ramp_g.color_ramp.elements[1].color = (0.70, 0.90, 0.32, 1)
    mid = ramp_g.color_ramp.elements.new(0.38)
    mid.color = (0.40, 0.70, 0.22, 1)
    link(nt, s2r_g.outputs["Color"], ramp_g.inputs["Fac"])

    # Ground cel colors (softer normal strength feel via darker dirt bands)
    diffuse_d = node(nt, "ShaderNodeBsdfDiffuse", (120, -160))
    diffuse_d.inputs["Color"].default_value = (1, 1, 1, 1)
    link(nt, nmap_world.outputs["Normal"], diffuse_d.inputs["Normal"])
    s2r_d = node(nt, "ShaderNodeShaderToRGB", (320, -160))
    link(nt, diffuse_d.outputs["BSDF"], s2r_d.inputs["Shader"])
    ramp_d = node(nt, "ShaderNodeValToRGB", (520, -160))
    ramp_d.color_ramp.interpolation = "CONSTANT"
    ramp_d.color_ramp.elements[0].position = 0.0
    ramp_d.color_ramp.elements[0].color = (0.42, 0.30, 0.18, 1)
    ramp_d.color_ramp.elements[1].position = 0.55
    ramp_d.color_ramp.elements[1].color = (0.82, 0.66, 0.44, 1)
    link(nt, s2r_d.outputs["Color"], ramp_d.inputs["Fac"])

    # Texture mask via same Empty (object-space sync — lattice idea from tutorial)
    mask_map = node(nt, "ShaderNodeMapping", (-1000, 320))
    mask_map.inputs["Location"].default_value = (0.5, 0.5, 0.0)
    mask_map.inputs["Scale"].default_value = (0.125, 0.125, 0.125)
    link(nt, texcoord.outputs["Object"], mask_map.inputs["Vector"])
    mtex = node(nt, "ShaderNodeTexImage", (-780, 320))
    mtex.image = mask_img
    mtex.interpolation = "Closest"
    link(nt, mask_map.outputs["Vector"], mtex.inputs["Vector"])

    mix = node(nt, "ShaderNodeMix", (760, 20), data_type="RGBA")
    link(nt, mtex.outputs["Color"], mix.inputs["Factor"])
    link(nt, ramp_d.outputs["Color"], mix.inputs["A"])
    link(nt, ramp_g.outputs["Color"], mix.inputs["B"])

    emit = node(nt, "ShaderNodeEmission", (1000, 20))
    emit.inputs["Strength"].default_value = 1.0
    link(nt, mix.outputs["Result"], emit.inputs["Color"])
    link(nt, emit.outputs["Emission"], out.inputs["Surface"])

    # Silence unused
    _ = ncomb
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
# Scatter on Surface + wind
# ---------------------------------------------------------------------------

def load_scatter_group() -> bpy.types.NodeTree:
    path = essentials_path()
    with bpy.data.libraries.load(str(path), link=False) as (data_from, data_to):
        data_to.node_groups = ["Scatter on Surface"]
    src = bpy.data.node_groups.get("Scatter on Surface")
    ng = src.copy()
    ng.name = "AnimeScatterGrass"
    return ng


def inject_wind(ng: bpy.types.NodeTree) -> None:
    """Rotate instances with layered noise driven by frame — tutorial-style wind."""
    iop = next(n for n in ng.nodes if n.bl_idname == "GeometryNodeInstanceOnPoints")
    # Find existing rotation link
    rot_in = iop.inputs["Rotation"]
    from_sock = None
    for l in list(rot_in.links):
        from_sock = l.from_socket
        ng.links.remove(l)

    # #frame → noise → euler
    scene_time = node(ng, "GeometryNodeInputSceneTime", (iop.location.x - 700, iop.location.y - 280))
    div = node(ng, "ShaderNodeMath", (iop.location.x - 520, iop.location.y - 280), operation="DIVIDE")
    div.inputs[1].default_value = 24.0
    link(ng, scene_time.outputs["Frame"], div.inputs[0])

    pos = node(ng, "GeometryNodeInputPosition", (iop.location.x - 700, iop.location.y - 420))
    noise1 = node(ng, "ShaderNodeTexNoise", (iop.location.x - 520, iop.location.y - 420))
    noise1.inputs["Scale"].default_value = 0.35
    noise1.inputs["Detail"].default_value = 2.0
    link(ng, pos.outputs["Position"], noise1.inputs["Vector"])

    # animate by adding time to vector
    addv = node(ng, "ShaderNodeVectorMath", (iop.location.x - 520, iop.location.y - 560), operation="ADD")
    link(ng, pos.outputs["Position"], addv.inputs[0])
    comb = node(ng, "ShaderNodeCombineXYZ", (iop.location.x - 700, iop.location.y - 560))
    link(ng, div.outputs["Value"], comb.inputs["X"])
    link(ng, comb.outputs["Vector"], addv.inputs[1])
    link(ng, addv.outputs["Vector"], noise1.inputs["Vector"])

    mapr = node(ng, "ShaderNodeMapRange", (iop.location.x - 340, iop.location.y - 420))
    mapr.inputs["From Min"].default_value = 0.3
    mapr.inputs["From Max"].default_value = 0.7
    mapr.inputs["To Min"].default_value = -0.25
    mapr.inputs["To Max"].default_value = 0.35
    link(ng, noise1.outputs["Fac"], mapr.inputs["Value"])

    # Wind as X/Y euler tilt
    eul = node(ng, "FunctionNodeEulerToRotation", (iop.location.x - 160, iop.location.y - 280))
    comb_e = node(ng, "ShaderNodeCombineXYZ", (iop.location.x - 340, iop.location.y - 280))
    link(ng, mapr.outputs["Result"], comb_e.inputs["X"])
    mul_y = node(ng, "ShaderNodeMath", (iop.location.x - 340, iop.location.y - 360), operation="MULTIPLY")
    mul_y.inputs[1].default_value = 0.6
    link(ng, mapr.outputs["Result"], mul_y.inputs[0])
    link(ng, mul_y.outputs["Value"], comb_e.inputs["Y"])
    link(ng, comb_e.outputs["Vector"], eul.inputs["Euler"])

    rot_rot = node(ng, "FunctionNodeRotateRotation", (iop.location.x - 40, iop.location.y - 120))
    if from_sock is not None:
        link(ng, from_sock, rot_rot.inputs["Rotation"])
    link(ng, eul.outputs["Rotation"], rot_rot.inputs["Rotate By"])
    link(ng, rot_rot.outputs["Rotation"], rot_in)


def set_mod(mod, name, value):
    """Blender 5.x: set via getattr(modifier.properties.inputs, Socket_X).value"""
    ng = mod.node_group
    for item in ng.interface.items_tree:
        if getattr(item, "name", None) == name and getattr(item, "in_out", "") == "INPUT":
            sock = getattr(mod.properties.inputs, item.identifier)
            if hasattr(sock, "value"):
                sock.value = value
                return True
            return False
    return False


def setup_scatter(ground, blade, flower_col, mask_img):
    ng = load_scatter_group()
    inject_wind(ng)
    mod = ground.modifiers.new("ScatterGrass", "NODES")
    mod.node_group = ng

    set_mod(mod, "Input Type", "Data-Block")
    set_mod(mod, "Instance Type", "Object")
    set_mod(mod, "Object", blade)
    set_mod(mod, "Density Method", "Density")
    set_mod(mod, "Distribution Method", "Random")
    set_mod(mod, "Density", 380.0)
    set_mod(mod, "Scale", (1.0, 1.0, 1.0))
    set_mod(mod, "Randomize", True)
    set_mod(mod, "Randomize Rotation", (0.05, 0.05, math.tau))
    # Socket_41 is the float uniform scale randomize
    try:
        getattr(mod.properties.inputs, "Socket_41").value = 0.45
    except Exception:
        pass
    set_mod(mod, "Align Rotation", True)
    set_mod(mod, "Realize Instances", False)
    set_mod(mod, "Keep Surface", True)
    # Mask via Distribution Mask attribute "Grass" — image masking needs correct UVs;
    # use attribute for growth, texture only in shader.
    set_mod(mod, "Masking", False)
    set_mod(mod, "Distribution Mask", 1.0)
    # Try binding attribute
    try:
        sock = getattr(mod.properties.inputs, "Socket_2")
        if hasattr(sock, "attribute_name"):
            sock.attribute_name = MASK_NAME
            sock.type = "ATTRIBUTE" if hasattr(sock, "type") else None
    except Exception as e:
        log(f"attr mask skip: {e}")

    ng2 = load_scatter_group()
    ng2.name = "AnimeScatterFlowers"
    inject_wind(ng2)
    mod2 = ground.modifiers.new("ScatterFlowers", "NODES")
    mod2.node_group = ng2
    set_mod(mod2, "Input Type", "Data-Block")
    set_mod(mod2, "Instance Type", "Collection")
    set_mod(mod2, "Collection", flower_col)
    set_mod(mod2, "Pick Instance", True)
    set_mod(mod2, "Density Method", "Density")
    set_mod(mod2, "Density", 6.0)
    set_mod(mod2, "Scale", (1.3, 1.3, 1.3))
    set_mod(mod2, "Randomize", True)
    set_mod(mod2, "Randomize Rotation", (0.0, 0.0, math.tau))
    set_mod(mod2, "Realize Instances", False)
    set_mod(mod2, "Keep Surface", True)
    set_mod(mod2, "Masking", False)
    return mod, mod2


def setup_scene():
    world = bpy.data.worlds.new("AnimeWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputWorld", (260, 0))
    bg = node(nt, "ShaderNodeBackground", (60, 0))
    bg.inputs["Color"].default_value = (0.78, 0.88, 0.95, 1)
    bg.inputs["Strength"].default_value = 0.35
    link(nt, bg.outputs["Background"], out.inputs["Surface"])

    empty = bpy.data.objects.new("TexSync", None)
    empty.empty_display_type = "CUBE"
    empty.empty_display_size = 1.0
    empty.scale = (8.0, 8.0, 8.0)
    bpy.context.scene.collection.objects.link(empty)

    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam_data.lens = 50
    cam.location = (7.2, -7.2, 6.2)
    cam.rotation_euler = Euler((math.radians(55), 0, math.radians(45)), "XYZ")
    bpy.context.scene.camera = cam

    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = Euler((math.radians(42), math.radians(8), math.radians(135)), "XYZ")
    sun.data.energy = 5.0
    sun.data.angle = math.radians(10.0)
    if hasattr(sun.data, "use_shadow"):
        sun.data.use_shadow = False

    fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", "AREA"))
    bpy.context.scene.collection.objects.link(fill)
    fill.location = (-5, -2, 3.5)
    fill.data.energy = 3.0
    fill.data.size = 8
    if hasattr(fill.data, "use_shadow"):
        fill.data.use_shadow = False
    return cam, empty


def configure_render(scene):
    engines = {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1600
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    if hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 64
    if hasattr(scene.eevee, "use_shadows"):
        scene.eevee.use_shadows = False
    scene.frame_start = 1
    scene.frame_end = 48
    scene.render.fps = 24
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.type = "RENDERED"


def render_still(scene, path: Path, frame: int):
    scene.frame_set(frame)
    scene.render.filepath = str(path)
    log(f"RENDER {path.name} @ {frame}")
    bpy.ops.render.render(write_still=True)


def build():
    if bpy.app.version < (5, 0, 0):
        raise RuntimeError("This 2026 grass build needs Blender 5.0+ (Scatter on Surface).")

    log("Clearing…")
    clear_scene()
    make_path_mask(MASK_PATH)
    log(f"Loading normal: {NORMAL_PATH}")
    normal_img = load_image(NORMAL_PATH, "GrassNormal", True)
    mask_img = load_image(MASK_PATH, "GrassMask", True)

    cam, empty = setup_scene()
    blade = make_grass_blade()
    flower = make_flower()
    flower_col = bpy.data.collections.new("Flowers")
    bpy.context.scene.collection.children.link(flower_col)
    bpy.context.scene.collection.objects.unlink(flower)
    flower_col.objects.link(flower)
    flower.location = (0, 0, -40)
    blade.location = (0, 0, -40)

    ground = create_ground()
    mat = make_shared_material(normal_img, mask_img, empty)
    flower_mat = make_flower_material()
    ground.data.materials.append(mat)
    blade.data.materials.append(mat)
    flower.data.materials.append(flower_mat)

    if hasattr(ground, "visible_shadow"):
        ground.visible_shadow = False
    if hasattr(blade, "visible_shadow"):
        blade.visible_shadow = False

    log("Scatter on Surface…")
    setup_scatter(ground, blade, flower_col, mask_img)
    configure_render(bpy.context.scene)

    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

    only_stills = "--stills-only" in sys.argv
    scene = bpy.context.scene
    render_still(scene, RENDER_DIR / "anime_grass_hero", 24)
    render_still(scene, RENDER_DIR / "anime_grass_wind_a", 8)
    render_still(scene, RENDER_DIR / "anime_grass_wind_b", 40)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    log(f"SAVED {BLEND_PATH}")


if __name__ == "__main__":
    try:
        build()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
