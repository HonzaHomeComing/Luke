"""
Anime Tree — reliable build (Trung-style cards + custom normals + cel)

Uses Python-placed leaf cards on a sphere (no fragile Distribute API),
Data Transfer painterly normals, Diffuse→Shader-to-RGB cel.

  blender-5.2+ --background --factory-startup \\
      --python anime-tree/build_anime_tree.py -- --stills-only
"""

from __future__ import annotations

import math
import random
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

ROOT = Path(__file__).resolve().parent
BLEND_PATH = ROOT / "anime_tree.blend"
RENDER_DIR = ROOT / "renders"


def log(msg: str) -> None:
    print(msg, flush=True)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for coll in (bpy.data.node_groups, bpy.data.materials, bpy.data.meshes, bpy.data.lights, bpy.data.cameras):
        for block in list(coll):
            try:
                coll.remove(block)
            except Exception:
                pass
    master = bpy.context.scene.collection
    for block in list(bpy.data.collections):
        if block != master:
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


def make_leaf_mesh() -> bpy.types.Mesh:
    # Soft diamond leaf
    verts = [
        (0, -0.18, 0),
        (0.12, -0.02, 0),
        (0.0, 0.22, 0),
        (-0.12, -0.02, 0),
        (0.06, 0.08, 0.01),
        (-0.06, 0.08, 0.01),
    ]
    faces = [(0, 1, 4, 5), (1, 2, 4), (5, 4, 2), (0, 5, 3), (3, 5, 2)]
    mesh = bpy.data.meshes.new("LeafMesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def fibonacci_sphere(n: int, radius: float):
    pts = []
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        y = 1 - (i / max(1, n - 1)) * 2
        r = math.sqrt(max(0, 1 - y * y))
        theta = golden * i
        x = math.cos(theta) * r
        z = math.sin(theta) * r
        pts.append(Vector((x, z, y)) * radius)  # swap to Y-up-ish bush
    return pts


def build_foliage(n_leaves=520) -> bpy.types.Object:
    rng = random.Random(7)
    leaf_mesh = make_leaf_mesh()
    # Template object
    tmpl = bpy.data.objects.new("LeafTmpl", leaf_mesh)
    bpy.context.scene.collection.objects.link(tmpl)

    center = Vector((0, 0, 2.55))
    radius = 1.25
    # Slightly squash
    scales = (1.15, 1.05, 0.95)

    bpy.ops.object.select_all(action="DESELECT")
    created = []
    for i, p in enumerate(fibonacci_sphere(n_leaves, 1.0)):
        loc = center + Vector((p.x * scales[0], p.y * scales[1], p.z * scales[2])) * radius
        # jitter
        loc += Vector((rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05)))
        obj = tmpl.copy()
        obj.data = leaf_mesh  # share mesh for memory; we'll join later so duplicate mesh
        obj.data = leaf_mesh.copy()
        bpy.context.scene.collection.objects.link(obj)
        obj.location = loc
        # Face roughly outward + random twist
        outward = (loc - center).normalized()
        obj.rotation_mode = "QUATERNION"
        obj.rotation_euler = outward.to_track_quat("Z", "Y").to_euler()
        obj.rotation_euler.rotate_axis("Z", rng.uniform(-math.pi, math.pi))
        s = rng.uniform(0.75, 1.45)
        obj.scale = (s, s, s)
        created.append(obj)

    # Join
    bpy.ops.object.select_all(action="DESELECT")
    for o in created:
        o.select_set(True)
    bpy.context.view_layer.objects.active = created[0]
    bpy.ops.object.join()
    bush = bpy.context.active_object
    bush.name = "FoliageBush"
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    bpy.data.objects.remove(tmpl, do_unlink=True)

    # Inflate slightly along normals
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.transform.shrink_fatten(value=0.04)
    bpy.ops.object.mode_set(mode="OBJECT")

    # Smooth donor sphere for painterly normals
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.45, location=center, segments=32, ring_count=16)
    donor = bpy.context.active_object
    donor.name = "NormalDonor"
    donor.scale = scales
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.shade_smooth()

    bush.select_set(True)
    bpy.context.view_layer.objects.active = bush
    dt = bush.modifiers.new("PaintNormals", "DATA_TRANSFER")
    dt.object = donor
    dt.use_loop_data = True
    dt.data_types_loops = {"CUSTOM_NORMAL"}
    dt.loop_mapping = "NEAREST_POLYNOR"
    bpy.ops.object.modifier_apply(modifier="PaintNormals")
    bpy.ops.object.shade_smooth()
    try:
        bpy.ops.mesh.customdata_custom_splitnormals_add()
    except Exception:
        pass

    donor.hide_set(True)
    donor.hide_render = True
    return bush


def make_trunk() -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(radius=0.14, depth=2.4, location=(0, 0, 1.1), vertices=8)
    trunk = bpy.context.active_object
    trunk.name = "Trunk"
    for v in trunk.data.vertices:
        if v.co.z > 0:
            v.co.x *= 0.55
            v.co.y *= 0.55
    trunk.data.update()
    return trunk


def make_foliage_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("AnimeFoliage")
    mat.use_nodes = True
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "NONE"
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (700, 0))
    diffuse = node(nt, "ShaderNodeBsdfDiffuse", (0, 0))
    diffuse.inputs["Color"].default_value = (1, 1, 1, 1)
    s2r = node(nt, "ShaderNodeShaderToRGB", (200, 0))
    link(nt, diffuse.outputs["BSDF"], s2r.inputs["Shader"])
    ramp = node(nt, "ShaderNodeValToRGB", (400, 0))
    ramp.color_ramp.interpolation = "CONSTANT"
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.16, 0.38, 0.14, 1)
    ramp.color_ramp.elements[1].position = 0.45
    ramp.color_ramp.elements[1].color = (0.52, 0.78, 0.26, 1)
    hi = ramp.color_ramp.elements.new(0.7)
    hi.color = (0.88, 0.96, 0.48, 1)
    link(nt, s2r.outputs["Color"], ramp.inputs["Fac"])
    emit = node(nt, "ShaderNodeEmission", (560, 0))
    link(nt, ramp.outputs["Color"], emit.inputs["Color"])
    link(nt, emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def make_trunk_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("AnimeTrunk")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial", (500, 0))
    diffuse = node(nt, "ShaderNodeBsdfDiffuse", (0, 0))
    s2r = node(nt, "ShaderNodeShaderToRGB", (160, 0))
    link(nt, diffuse.outputs["BSDF"], s2r.inputs["Shader"])
    ramp = node(nt, "ShaderNodeValToRGB", (320, 0))
    ramp.color_ramp.interpolation = "CONSTANT"
    ramp.color_ramp.elements[0].color = (0.25, 0.14, 0.08, 1)
    ramp.color_ramp.elements[1].position = 0.55
    ramp.color_ramp.elements[1].color = (0.58, 0.38, 0.22, 1)
    link(nt, s2r.outputs["Color"], ramp.inputs["Fac"])
    emit = node(nt, "ShaderNodeEmission", (420, 0))
    link(nt, ramp.outputs["Color"], emit.inputs["Color"])
    link(nt, emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def setup_scene():
    world = bpy.data.worlds.new("TreeWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputWorld", (200, 0))
    bg = node(nt, "ShaderNodeBackground", (0, 0))
    bg.inputs["Color"].default_value = (0.72, 0.84, 0.90, 1)
    bg.inputs["Strength"].default_value = 0.35
    link(nt, bg.outputs["Background"], out.inputs["Surface"])

    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (5.2, -5.2, 3.8)
    cam.rotation_euler = Euler((math.radians(62), 0, math.radians(45)), "XYZ")
    bpy.context.scene.camera = cam

    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = Euler((math.radians(38), math.radians(12), math.radians(125)), "XYZ")
    sun.data.energy = 5.0
    sun.data.angle = math.radians(6)
    if hasattr(sun.data, "use_shadow"):
        sun.data.use_shadow = False

    bpy.ops.mesh.primitive_circle_add(vertices=64, radius=3.2, fill_type="NGON", location=(0, 0, 0))
    ground = bpy.context.active_object
    ground.name = "Ground"
    gmat = bpy.data.materials.new("GroundMat")
    gmat.use_nodes = True
    gnt = gmat.node_tree
    gnt.nodes.clear()
    gout = node(gnt, "ShaderNodeOutputMaterial", (300, 0))
    # Ground also cel-ish
    d = node(gnt, "ShaderNodeBsdfDiffuse", (0, 0))
    s2 = node(gnt, "ShaderNodeShaderToRGB", (120, 0))
    link(gnt, d.outputs["BSDF"], s2.inputs["Shader"])
    r = node(gnt, "ShaderNodeValToRGB", (240, 0))
    r.color_ramp.elements[0].color = (0.35, 0.52, 0.28, 1)
    r.color_ramp.elements[1].position = 0.6
    r.color_ramp.elements[1].color = (0.55, 0.72, 0.40, 1)
    link(gnt, s2.outputs["Color"], r.inputs["Fac"])
    gem = node(gnt, "ShaderNodeEmission", (360, 0))
    link(gnt, r.outputs["Color"], gem.inputs["Color"])
    link(gnt, gem.outputs["Emission"], gout.inputs["Surface"])
    ground.data.materials.append(gmat)
    return cam


def configure_render(scene):
    engines = {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 1400
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    if hasattr(scene.eevee, "use_shadows"):
        scene.eevee.use_shadows = False
    if hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 64


def build():
    log("Clearing…")
    clear_scene()
    setup_scene()
    log("Foliage…")
    bush = build_foliage(480)
    trunk = make_trunk()
    fmat = make_foliage_material()
    tmat = make_trunk_material()
    bush.data.materials.clear()
    bush.data.materials.append(fmat)
    trunk.data.materials.append(tmat)
    for o in (bush, trunk):
        if hasattr(o, "visible_shadow"):
            o.visible_shadow = False

    configure_render(bpy.context.scene)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    scene = bpy.context.scene
    scene.render.filepath = str(RENDER_DIR / "anime_tree_hero")
    log("RENDER anime_tree_hero")
    bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))
    log(f"SAVED {BLEND_PATH}")


if __name__ == "__main__":
    try:
        build()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
