"""
VOIDSEED — Geometry Nodes generative sculpture for Blender 4.2+

  blender --background --python voidseed/build_voidseed.py
"""

from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Euler

ROOT = Path(__file__).resolve().parent
BLEND_PATH = ROOT / "voidseed.blend"
RENDER_DIR = ROOT / "renders"


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.node_groups, bpy.data.lights, bpy.data.cameras):
        for block in list(coll):
            coll.remove(block)


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


def make_emission(name, color, strength):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (280, 0))
    emit = node(nt, "ShaderNodeEmission", (80, 0))
    emit.inputs["Color"].default_value = (*color, 1)
    emit.inputs["Strength"].default_value = strength
    link(nt, emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def make_spine_material():
    mat = bpy.data.materials.new("Void_Spines")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (420, 0))
    bsdf = node(nt, "ShaderNodeBsdfPrincipled", (100, 60))
    bsdf.inputs["Base Color"].default_value = (0.55, 0.95, 0.88, 1)
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.16
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.8
        bsdf.inputs["Coat Roughness"].default_value = 0.04
    emit = node(nt, "ShaderNodeEmission", (100, -200))
    emit.inputs["Color"].default_value = (0.25, 1.0, 0.8, 1)
    emit.inputs["Strength"].default_value = 2.2
    mix = node(nt, "ShaderNodeMixShader", (280, 0))
    fresnel = node(nt, "ShaderNodeFresnel", (100, -40))
    fresnel.inputs["IOR"].default_value = 1.55
    link(nt, fresnel.outputs["Fac"], mix.inputs["Fac"])
    link(nt, bsdf.outputs["BSDF"], mix.inputs[1])
    link(nt, emit.outputs["Emission"], mix.inputs[2])
    link(nt, mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def make_web_material():
    return make_emission("Void_Web", (1.0, 0.22, 0.02), 6.5)


def make_shell_material():
    mat = bpy.data.materials.new("Void_Shell")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (300, 0))
    bsdf = node(nt, "ShaderNodeBsdfPrincipled", (80, 0))
    bsdf.inputs["Base Color"].default_value = (0.02, 0.05, 0.07, 1)
    bsdf.inputs["Metallic"].default_value = 0.85
    bsdf.inputs["Roughness"].default_value = 0.35
    link(nt, bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def build_tree(mats: dict) -> bpy.types.GeometryNodeTree:
    nt = bpy.data.node_groups.new("VOIDSEED", "GeometryNodeTree")

    add_socket(nt, "Geometry", "INPUT", "NodeSocketGeometry")
    add_socket(nt, "Seed", "INPUT", "NodeSocketInt", 7, 0, 9999)
    add_socket(nt, "Growth", "INPUT", "NodeSocketFloat", 0.9, 0.05, 1.6)
    add_socket(nt, "Chaos", "INPUT", "NodeSocketFloat", 0.55, 0.0, 2.5)
    add_socket(nt, "Spine Density", "INPUT", "NodeSocketFloat", 34.0, 1.0, 150.0)
    add_socket(nt, "Spine Length", "INPUT", "NodeSocketFloat", 0.65, 0.05, 2.5)
    add_socket(nt, "Web Thickness", "INPUT", "NodeSocketFloat", 0.015, 0.002, 0.08)
    add_socket(nt, "Pulse", "INPUT", "NodeSocketFloat", 0.0, -5.0, 30.0)
    add_socket(nt, "Geometry", "OUTPUT", "NodeSocketGeometry")

    nin = node(nt, "NodeGroupInput", (-1900, 0))
    nout = node(nt, "NodeGroupOutput", (2100, 40))

    # --- time / seed drive ---
    scene_time = node(nt, "GeometryNodeInputSceneTime", (-1900, -260))
    time_pulse = node(nt, "ShaderNodeMath", (-1700, -220), operation="ADD")
    link(nt, scene_time.outputs["Seconds"], time_pulse.inputs[0])
    link(nt, nin.outputs["Pulse"], time_pulse.inputs[1])

    seed_scale = node(nt, "ShaderNodeMath", (-1700, -360), operation="MULTIPLY")
    seed_scale.inputs[1].default_value = 0.173
    link(nt, nin.outputs["Seed"], seed_scale.inputs[0])

    w = node(nt, "ShaderNodeMath", (-1520, -260), operation="ADD")
    link(nt, time_pulse.outputs["Value"], w.inputs[0])
    link(nt, seed_scale.outputs["Value"], w.inputs[1])

    # --- living shell ---
    ico = node(nt, "GeometryNodeMeshIcoSphere", (-1700, 420))
    ico.inputs["Subdivisions"].default_value = 3
    ico.inputs["Radius"].default_value = 1.0

    gvec = node(nt, "ShaderNodeCombineXYZ", (-1520, 560))
    link(nt, nin.outputs["Growth"], gvec.inputs[0])
    link(nt, nin.outputs["Growth"], gvec.inputs[1])
    link(nt, nin.outputs["Growth"], gvec.inputs[2])

    shell_xf = node(nt, "GeometryNodeTransform", (-1520, 420))
    link(nt, ico.outputs["Mesh"], shell_xf.inputs["Geometry"])
    link(nt, gvec.outputs["Vector"], shell_xf.inputs["Scale"])

    pos = node(nt, "GeometryNodeInputPosition", (-1520, 200))
    noise = node(nt, "ShaderNodeTexNoise", (-1320, 200))
    noise.noise_dimensions = "4D"
    noise.inputs["Scale"].default_value = 2.3
    noise.inputs["Detail"].default_value = 11.0
    noise.inputs["Roughness"].default_value = 0.62
    link(nt, pos.outputs["Position"], noise.inputs["Vector"])
    link(nt, w.outputs["Value"], noise.inputs["W"])

    nfac = node(nt, "ShaderNodeMath", (-1120, 240), operation="MULTIPLY")
    link(nt, noise.outputs["Fac"], nfac.inputs[0])
    link(nt, nin.outputs["Chaos"], nfac.inputs[1])
    namp = node(nt, "ShaderNodeMath", (-960, 240), operation="MULTIPLY")
    namp.inputs[1].default_value = 0.2
    link(nt, nfac.outputs["Value"], namp.inputs[0])

    normal = node(nt, "GeometryNodeInputNormal", (-1120, 60))
    offset = node(nt, "ShaderNodeVectorMath", (-960, 80), operation="SCALE")
    link(nt, normal.outputs["Normal"], offset.inputs[0])
    link(nt, namp.outputs["Value"], offset.inputs["Scale"])

    shell = node(nt, "GeometryNodeSetPosition", (-780, 400))
    link(nt, shell_xf.outputs["Geometry"], shell.inputs["Geometry"])
    link(nt, offset.outputs["Vector"], shell.inputs["Offset"])

    shell_mat = node(nt, "GeometryNodeSetMaterial", (-580, 400))
    shell_mat.inputs["Material"].default_value = mats["shell"]
    link(nt, shell.outputs["Geometry"], shell_mat.inputs["Geometry"])

    # --- molten core ---
    core_ico = node(nt, "GeometryNodeMeshIcoSphere", (-1700, 720))
    core_ico.inputs["Subdivisions"].default_value = 2
    core_ico.inputs["Radius"].default_value = 0.4
    core_g = node(nt, "ShaderNodeMath", (-1700, 860), operation="MULTIPLY")
    core_g.inputs[1].default_value = 0.58
    link(nt, nin.outputs["Growth"], core_g.inputs[0])
    core_vec = node(nt, "ShaderNodeCombineXYZ", (-1520, 860))
    link(nt, core_g.outputs["Value"], core_vec.inputs[0])
    link(nt, core_g.outputs["Value"], core_vec.inputs[1])
    link(nt, core_g.outputs["Value"], core_vec.inputs[2])
    core_xf = node(nt, "GeometryNodeTransform", (-1520, 720))
    link(nt, core_ico.outputs["Mesh"], core_xf.inputs["Geometry"])
    link(nt, core_vec.outputs["Vector"], core_xf.inputs["Scale"])
    core_mat = node(nt, "GeometryNodeSetMaterial", (-1320, 720))
    core_mat.inputs["Material"].default_value = mats["core"]
    link(nt, core_xf.outputs["Geometry"], core_mat.inputs["Geometry"])

    # --- geodesic energy web (dual mesh → curves) ---
    dual = node(nt, "GeometryNodeDualMesh", (-580, 200))
    link(nt, shell.outputs["Geometry"], dual.inputs["Mesh"])
    m2c = node(nt, "GeometryNodeMeshToCurve", (-380, 200))
    link(nt, dual.outputs["Dual Mesh"], m2c.inputs["Mesh"])
    resample = node(nt, "GeometryNodeResampleCurve", (-180, 200), mode="LENGTH")
    resample.inputs["Length"].default_value = 0.055
    link(nt, m2c.outputs["Curve"], resample.inputs["Curve"])

    cpos = node(nt, "GeometryNodeInputPosition", (-380, 20))
    cnoise = node(nt, "ShaderNodeTexNoise", (-180, 20))
    cnoise.noise_dimensions = "4D"
    cnoise.inputs["Scale"].default_value = 4.0
    cnoise.inputs["Detail"].default_value = 6.0
    link(nt, cpos.outputs["Position"], cnoise.inputs["Vector"])
    link(nt, w.outputs["Value"], cnoise.inputs["W"])
    c1 = node(nt, "ShaderNodeMath", (0, 40), operation="MULTIPLY")
    link(nt, cnoise.outputs["Fac"], c1.inputs[0])
    link(nt, nin.outputs["Chaos"], c1.inputs[1])
    c2 = node(nt, "ShaderNodeMath", (160, 40), operation="MULTIPLY")
    c2.inputs[1].default_value = 0.065
    link(nt, c1.outputs["Value"], c2.inputs[0])
    coff = node(nt, "ShaderNodeCombineXYZ", (160, -80))
    link(nt, c2.outputs["Value"], coff.inputs[0])
    link(nt, c2.outputs["Value"], coff.inputs[1])
    link(nt, c2.outputs["Value"], coff.inputs[2])
    set_c = node(nt, "GeometryNodeSetPosition", (0, 200))
    link(nt, resample.outputs["Curve"], set_c.inputs["Geometry"])
    link(nt, coff.outputs["Vector"], set_c.inputs["Offset"])

    profile = node(nt, "GeometryNodeCurvePrimitiveCircle", (0, 360))
    profile.inputs["Resolution"].default_value = 8
    link(nt, nin.outputs["Web Thickness"], profile.inputs["Radius"])
    c2m = node(nt, "GeometryNodeCurveToMesh", (320, 200))
    link(nt, set_c.outputs["Geometry"], c2m.inputs["Curve"])
    link(nt, profile.outputs["Curve"], c2m.inputs["Profile Curve"])
    web_mat = node(nt, "GeometryNodeSetMaterial", (520, 200))
    web_mat.inputs["Material"].default_value = mats["web"]
    link(nt, c2m.outputs["Mesh"], web_mat.inputs["Geometry"])

    # --- crystal spines ---
    dens = node(nt, "ShaderNodeMath", (-780, -80), operation="MULTIPLY")
    link(nt, nin.outputs["Spine Density"], dens.inputs[0])
    link(nt, nin.outputs["Growth"], dens.inputs[1])

    dist = node(nt, "GeometryNodeDistributePointsOnFaces", (-560, -40))
    dist.distribute_method = "POISSON"
    if dist.inputs["Distance Min"].enabled:
        dist.inputs["Distance Min"].default_value = 0.048
    link(nt, shell.outputs["Geometry"], dist.inputs["Mesh"])
    # Poisson uses Density Max
    dens_socket = "Density Max" if dist.inputs["Density Max"].enabled else "Density"
    link(nt, dens.outputs["Value"], dist.inputs[dens_socket])
    link(nt, nin.outputs["Seed"], dist.inputs["Seed"])

    cone = node(nt, "GeometryNodeMeshCone", (-560, -280))
    cone.inputs["Vertices"].default_value = 6
    cone.inputs["Radius Top"].default_value = 0.0
    cone.inputs["Radius Bottom"].default_value = 0.04
    cone.inputs["Depth"].default_value = 1.0

    align = node(nt, "FunctionNodeAlignEulerToVector", (-300, -40), axis="Z")
    link(nt, dist.outputs["Normal"], align.inputs["Vector"])

    idn = node(nt, "GeometryNodeInputID", (-560, -420))
    rscale = node(nt, "FunctionNodeRandomValue", (-300, -280), data_type="FLOAT")
    rscale.inputs["Min"].default_value = 0.5
    rscale.inputs["Max"].default_value = 1.45
    link(nt, idn.outputs["ID"], rscale.inputs["ID"])
    link(nt, nin.outputs["Seed"], rscale.inputs["Seed"])

    len1 = node(nt, "ShaderNodeMath", (-100, -280), operation="MULTIPLY")
    link(nt, rscale.outputs["Value"], len1.inputs[0])
    link(nt, nin.outputs["Spine Length"], len1.inputs[1])
    len2 = node(nt, "ShaderNodeMath", (60, -280), operation="MULTIPLY")
    link(nt, len1.outputs["Value"], len2.inputs[0])
    link(nt, nin.outputs["Growth"], len2.inputs[1])

    xy = node(nt, "ShaderNodeMath", (60, -400), operation="MULTIPLY")
    xy.inputs[1].default_value = 0.32
    link(nt, len2.outputs["Value"], xy.inputs[0])
    svec = node(nt, "ShaderNodeCombineXYZ", (220, -320))
    link(nt, xy.outputs["Value"], svec.inputs[0])
    link(nt, xy.outputs["Value"], svec.inputs[1])
    link(nt, len2.outputs["Value"], svec.inputs[2])

    iop = node(nt, "GeometryNodeInstanceOnPoints", (420, -40))
    link(nt, dist.outputs["Points"], iop.inputs["Points"])
    link(nt, cone.outputs["Mesh"], iop.inputs["Instance"])
    link(nt, align.outputs["Rotation"], iop.inputs["Rotation"])
    link(nt, svec.outputs["Vector"], iop.inputs["Scale"])

    realize = node(nt, "GeometryNodeRealizeInstances", (640, -40))
    link(nt, iop.outputs["Instances"], realize.inputs["Geometry"])
    spine_mat = node(nt, "GeometryNodeSetMaterial", (840, -40))
    spine_mat.inputs["Material"].default_value = mats["spines"]
    link(nt, realize.outputs["Geometry"], spine_mat.inputs["Geometry"])

    # --- spore motes ---
    dens2 = node(nt, "ShaderNodeMath", (-780, -560), operation="MULTIPLY")
    dens2.inputs[1].default_value = 0.32
    link(nt, dens.outputs["Value"], dens2.inputs[0])
    seed2 = node(nt, "ShaderNodeMath", (-780, -660), operation="ADD")
    seed2.inputs[1].default_value = 113
    link(nt, nin.outputs["Seed"], seed2.inputs[0])

    dist2 = node(nt, "GeometryNodeDistributePointsOnFaces", (-560, -600))
    dist2.distribute_method = "POISSON"
    if dist2.inputs["Distance Min"].enabled:
        dist2.inputs["Distance Min"].default_value = 0.11
    link(nt, shell.outputs["Geometry"], dist2.inputs["Mesh"])
    dens_socket2 = "Density Max" if dist2.inputs["Density Max"].enabled else "Density"
    link(nt, dens2.outputs["Value"], dist2.inputs[dens_socket2])
    link(nt, seed2.outputs["Value"], dist2.inputs["Seed"])

    mote = node(nt, "GeometryNodeMeshIcoSphere", (-560, -780))
    mote.inputs["Subdivisions"].default_value = 1
    mote.inputs["Radius"].default_value = 0.03

    id2 = node(nt, "GeometryNodeInputID", (-560, -880))
    rs2 = node(nt, "FunctionNodeRandomValue", (-300, -700), data_type="FLOAT")
    rs2.inputs["Min"].default_value = 0.35
    rs2.inputs["Max"].default_value = 1.7
    link(nt, id2.outputs["ID"], rs2.inputs["ID"])
    link(nt, seed2.outputs["Value"], rs2.inputs["Seed"])

    iop2 = node(nt, "GeometryNodeInstanceOnPoints", (200, -600))
    link(nt, dist2.outputs["Points"], iop2.inputs["Points"])
    link(nt, mote.outputs["Mesh"], iop2.inputs["Instance"])
    link(nt, rs2.outputs["Value"], iop2.inputs["Scale"])
    realize2 = node(nt, "GeometryNodeRealizeInstances", (420, -600))
    link(nt, iop2.outputs["Instances"], realize2.inputs["Geometry"])
    spore_mat = node(nt, "GeometryNodeSetMaterial", (640, -600))
    spore_mat.inputs["Material"].default_value = mats["spores"]
    link(nt, realize2.outputs["Geometry"], spore_mat.inputs["Geometry"])

    # --- join everything ---
    join = node(nt, "GeometryNodeJoinGeometry", (1200, 80))
    link(nt, core_mat.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, shell_mat.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, web_mat.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, spine_mat.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, spore_mat.outputs["Geometry"], join.inputs["Geometry"])
    link(nt, join.outputs["Geometry"], nout.inputs["Geometry"])
    return nt


def set_mod_input(obj, mod_name, socket_name, value, frame=None):
    mod = obj.modifiers[mod_name]
    ng = mod.node_group
    for item in ng.interface.items_tree:
        if getattr(item, "name", None) == socket_name and getattr(item, "in_out", "") == "INPUT":
            mod[item.identifier] = value
            if frame is not None:
                obj.keyframe_insert(data_path=f'modifiers["{mod_name}"]["{item.identifier}"]', frame=frame)
            return True
    return False


def setup_scene():
    world = bpy.data.worlds.new("VoidWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputWorld", (260, 0))
    bg = node(nt, "ShaderNodeBackground", (60, 0))
    bg.inputs["Color"].default_value = (0.008, 0.012, 0.018, 1)
    bg.inputs["Strength"].default_value = 1.0
    link(nt, bg.outputs["Background"], out.inputs["Surface"])

    cam_data = bpy.data.cameras.new("VoidCam")
    cam = bpy.data.objects.new("VoidCam", cam_data)
    bpy.context.collection.objects.link(cam)
    cam_data.lens = 50
    bpy.context.scene.camera = cam

    key = bpy.data.objects.new("Key", bpy.data.lights.new("Key", "AREA"))
    bpy.context.collection.objects.link(key)
    key.location = (3.6, -1.4, 4.2)
    key.rotation_euler = Euler((math.radians(-40), math.radians(15), math.radians(35)), "XYZ")
    key.data.energy = 140
    key.data.size = 3.2
    key.data.color = (0.7, 0.88, 1.0)

    rim = bpy.data.objects.new("Rim", bpy.data.lights.new("Rim", "AREA"))
    bpy.context.collection.objects.link(rim)
    rim.location = (-3.2, 2.4, 1.4)
    rim.rotation_euler = Euler((math.radians(85), 0, math.radians(-50)), "XYZ")
    rim.data.energy = 280
    rim.data.size = 1.4
    rim.data.color = (1.0, 0.42, 0.18)

    fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", "POINT"))
    bpy.context.collection.objects.link(fill)
    fill.location = (0.4, -2.8, -1.0)
    fill.data.energy = 55
    fill.data.color = (0.25, 1.0, 0.75)
    return cam


def configure_engine(scene):
    engines = {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else (
        "BLENDER_EEVEE" if "BLENDER_EEVEE" in engines else "CYCLES"
    )
    scene.render.engine = engine
    scene.render.image_settings.file_format = "PNG"
    if engine.startswith("BLENDER_EEVEE"):
        eevee = scene.eevee
        if hasattr(eevee, "taa_render_samples"):
            eevee.taa_render_samples = 64
        if hasattr(eevee, "use_bloom"):
            eevee.use_bloom = True
            eevee.bloom_intensity = 0.1
            eevee.bloom_threshold = 0.55
    else:
        scene.cycles.samples = 48
        scene.cycles.use_denoising = True
    return engine


def animate(obj, cam):
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 72
    scene.render.fps = 24

    set_mod_input(obj, "VOIDSEED", "Growth", 0.12, 1)
    set_mod_input(obj, "VOIDSEED", "Growth", 1.08, 50)
    set_mod_input(obj, "VOIDSEED", "Growth", 0.92, 72)
    set_mod_input(obj, "VOIDSEED", "Pulse", 0.0, 1)
    set_mod_input(obj, "VOIDSEED", "Pulse", 3.2, 72)
    set_mod_input(obj, "VOIDSEED", "Chaos", 0.2, 1)
    set_mod_input(obj, "VOIDSEED", "Chaos", 0.95, 72)

    for frame, yaw in ((1, 38), (72, 158)):
        rad = math.radians(yaw)
        r = 6.2
        cam.location = (r * math.sin(rad), -r * math.cos(rad), 2.4)
        cam.rotation_euler = Euler((math.radians(68), 0, rad), "XYZ")
        cam.keyframe_insert("location", frame=frame)
        cam.keyframe_insert("rotation_euler", frame=frame)

    if cam.animation_data and cam.animation_data.action:
        for fcu in cam.animation_data.action.fcurves:
            for kp in fcu.keyframe_points:
                kp.interpolation = "LINEAR"


def render_still(scene, path: Path, frame: int, size=1600):
    scene.frame_set(frame)
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.filepath = str(path)
    print(f"RENDER {path.name} @ frame {frame}")
    bpy.ops.render.render(write_still=True)


def build():
    clear_scene()
    mats = {
        "spines": make_spine_material(),
        "web": make_web_material(),
        "shell": make_shell_material(),
        "core": make_emission("Void_Core", (1.0, 0.45, 0.08), 8.0),
        "spores": make_emission("Void_Spores", (0.75, 1.0, 0.25), 3.5),
    }

    mesh = bpy.data.meshes.new("VoidseedMesh")
    mesh.from_pydata([(0, 0, 0)], [], [])
    obj = bpy.data.objects.new("VOIDSEED", mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj

    nt = build_tree(mats)
    mod = obj.modifiers.new("VOIDSEED", "NODES")
    mod.node_group = nt

    # Materials must live on the object for Set Material to render reliably
    existing = {m.name for m in obj.data.materials if m}
    for key in ("shell", "web", "spines", "core", "spores"):
        if mats[key].name not in existing:
            obj.data.materials.append(mats[key])
            existing.add(mats[key].name)

    cam = setup_scene()
    configure_engine(bpy.context.scene)
    animate(obj, cam)

    # Default attractive pose
    set_mod_input(obj, "VOIDSEED", "Seed", 7)
    set_mod_input(obj, "VOIDSEED", "Spine Density", 36.0)
    set_mod_input(obj, "VOIDSEED", "Spine Length", 0.7)
    set_mod_input(obj, "VOIDSEED", "Web Thickness", 0.02)

    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene

    render_still(scene, RENDER_DIR / "voidseed_hero", 48)
    render_still(scene, RENDER_DIR / "voidseed_growth_early", 8)
    render_still(scene, RENDER_DIR / "voidseed_growth_late", 72)

    anim_dir = RENDER_DIR / "anim"
    anim_dir.mkdir(parents=True, exist_ok=True)
    print("RENDER anim frames")
    for f in range(1, 73, 2):
        render_still(scene, anim_dir / f"frame_{f:04d}", f, size=720)

    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    print(f"SAVED {BLEND_PATH}")


if __name__ == "__main__":
    try:
        build()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
