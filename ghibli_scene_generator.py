#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ghibli Scene Generator -- double-clickable launcher.

What this does
--------------
1. Writes a secondary `generate_scene.py` next to this file. That file contains
   ALL of the Blender (`bpy`) logic that procedurally builds a Studio Ghibli
   style anime nature scene -- rolling grass with wind, a fluffy anime tree,
   clean toon (cel) materials, warm sun and an anime-blue sky.
2. Locates the system's Blender executable (works across Windows / macOS /
   Linux) and launches it, e.g. `blender --python generate_scene.py`.

Nothing is downloaded and no external models are used -- every mesh, node group
and material is generated from scratch in code.

Usage
-----
* Just double-click this file (or run `python ghibli_scene_generator.py`).
  Blender opens with the finished scene so you can hit play and watch the wind.
* Headless render (no GUI): `python ghibli_scene_generator.py --background`
  This renders a still to `ghibli_scene_render.png` next to this script (or to
  the path in the `GHIBLI_RENDER_OUT` environment variable).

If Blender cannot be found, set the `BLENDER` environment variable to the full
path of the Blender executable, or install Blender from https://www.blender.org.
"""

from __future__ import annotations

import glob
import os
import platform
import shutil
import subprocess
import sys


# ---------------------------------------------------------------------------
# The bpy program that Blender will run.  Stored as a plain (non-f) raw string
# so we can drop it on disk verbatim.  It only uses "#" comments and single or
# double quotes -- never triple quotes -- so it never clashes with this wrapper.
# ---------------------------------------------------------------------------
SCENE_CODE = r'''# -*- coding: utf-8 -*-
# generate_scene.py -- procedurally build a Studio Ghibli style anime nature
# scene entirely from code.  Auto-written by ghibli_scene_generator.py.
#
# Run by Blender via:  blender --python generate_scene.py
# (add --background to render a still headlessly)

import os
import math
import bpy
import bmesh
from mathutils import Vector

# ----------------------------- tunable constants ---------------------------
GROUND_SIZE = 24.0        # side length (metres) of the grassy ground plane
GRASS_DENSITY = 40.0      # blades per square metre (raise for a denser lawn)
BLADE_HEIGHT = 0.5        # height of a single grass blade
NOISE_SCALE = 2.0         # wind Noise Texture scale (per the brief, ~2.0)
WIND_STRENGTH = 0.9       # how far the blades sway (radians)
WIND_SPEED = 0.12         # how fast the wind field advances per frame
WIND_FIELD = 0.07         # spatial coherence: smaller = broader rolling waves
CANOPY_BALLS = 6          # number of ico-spheres that form the fluffy canopy


# ============================================================================
# 0. Clean slate -- remove whatever the default startup scene contains.
# ============================================================================
def clean_slate():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    # Drop orphaned data so re-runs stay tidy.
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.node_groups,
                 bpy.data.textures, bpy.data.lights, bpy.data.cameras):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)


# ============================================================================
# 1. Toon (cel) material helper.
#    Diffuse BSDF -> Shader to RGB -> ColorRamp (Constant) -> Emission.
#    The Diffuse node captures real lighting (including received shadows); the
#    Shader-to-RGB + constant ramp quantises it into flat anime tones.
# ============================================================================
def make_toon_material(name, shadow_col, light_col, boundary=0.42):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    diffuse = nt.nodes.new('ShaderNodeBsdfDiffuse')
    diffuse.location = (-620, 0)
    # Pure white albedo so the ramp reacts to light intensity, not albedo.
    diffuse.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)

    to_rgb = nt.nodes.new('ShaderNodeShaderToRGB')     # needs Eevee
    to_rgb.location = (-380, 0)

    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.location = (-120, 0)
    ramp.color_ramp.interpolation = 'CONSTANT'         # hard cel banding
    elements = ramp.color_ramp.elements
    elements[0].position = 0.0
    elements[0].color = shadow_col
    elements[1].position = boundary
    elements[1].color = light_col

    emission = nt.nodes.new('ShaderNodeEmission')
    emission.location = (150, 0)

    output = nt.nodes.new('ShaderNodeOutputMaterial')
    output.location = (380, 0)

    links = nt.links
    links.new(diffuse.outputs['BSDF'], to_rgb.inputs['Shader'])
    links.new(to_rgb.outputs['Color'], ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'], emission.inputs['Color'])
    links.new(emission.outputs['Emission'], output.inputs['Surface'])
    return mat


def no_shadow(obj):
    # Turn off shadow casting for this object (keeps the flat anime look).
    try:
        obj.visible_shadow = False
    except Exception:
        pass


# ============================================================================
# 2. A single procedural grass blade: a tapered, subdivided plane that stands
#    up along +Z with its origin at the base so it can sway from the ground.
# ============================================================================
def make_grass_blade(material):
    mesh = bpy.data.meshes.new('GrassBlade')
    obj = bpy.data.objects.new('GrassBlade', mesh)
    bpy.context.collection.objects.link(obj)

    bm = bmesh.new()
    segments = 5
    base_half = 0.022
    left, right = [], []
    for i in range(segments + 1):
        t = i / segments
        z = BLADE_HEIGHT * t
        half = base_half * (1.0 - 0.85 * t)     # taper toward a soft tip
        bend = 0.10 * (t * t)                    # gentle forward curve in +Y
        left.append(bm.verts.new((-half, bend, z)))
        right.append(bm.verts.new((half, bend, z)))
    for i in range(segments):
        bm.faces.new((left[i], right[i], right[i + 1], left[i + 1]))
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()

    for poly in mesh.polygons:
        poly.use_smooth = True
    mesh.materials.append(material)

    # Keep the source blade out of the render; it only feeds the instancer.
    obj.hide_render = True
    obj.hide_set(True)
    no_shadow(obj)
    return obj


# ============================================================================
# 3. Ground plane + Geometry Nodes: scatter the blade densely and drive a
#    rolling wind wave from a Noise Texture linked to Scene Time (#frame).
# ============================================================================
def build_grass_field(blade_obj, ground_material):
    bpy.ops.mesh.primitive_plane_add(size=GROUND_SIZE, location=(0, 0, 0))
    ground = bpy.context.active_object
    ground.name = 'Ground'
    ground.data.materials.append(ground_material)
    no_shadow(ground)

    modifier = ground.modifiers.new('GrassScatter', 'NODES')
    ng = bpy.data.node_groups.new('GrassScatterNodes', 'GeometryNodeTree')
    modifier.node_group = ng

    # Group interface (Blender 4.x uses node_group.interface).
    ng.interface.new_socket('Geometry', in_out='INPUT',
                            socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT',
                            socket_type='NodeSocketGeometry')

    nodes = ng.nodes
    links = ng.links

    group_in = nodes.new('NodeGroupInput')
    group_in.location = (-1000, 0)
    group_out = nodes.new('NodeGroupOutput')
    group_out.location = (900, 0)

    # -- scatter points across the ground faces --------------------------------
    distribute = nodes.new('GeometryNodeDistributePointsOnFaces')
    distribute.location = (-760, 160)
    distribute.inputs['Density'].default_value = GRASS_DENSITY
    distribute.inputs['Seed'].default_value = 7

    # -- the blade, pulled in as an instance -----------------------------------
    obj_info = nodes.new('GeometryNodeObjectInfo')
    obj_info.location = (-760, -260)
    obj_info.transform_space = 'RELATIVE'
    obj_info.inputs['Object'].default_value = blade_obj
    if 'As Instance' in obj_info.inputs:
        obj_info.inputs['As Instance'].default_value = True

    # -- per-blade random size -------------------------------------------------
    rand_scale = nodes.new('FunctionNodeRandomValue')
    rand_scale.location = (-760, -60)
    rand_scale.data_type = 'FLOAT'
    rand_scale.inputs[2].default_value = 0.75   # Min (float)
    rand_scale.inputs[3].default_value = 1.30   # Max (float)

    # -- per-blade random yaw so the lawn is not uniform -----------------------
    rand_yaw = nodes.new('FunctionNodeRandomValue')
    rand_yaw.location = (-760, -460)
    rand_yaw.data_type = 'FLOAT_VECTOR'
    rand_yaw.inputs[0].default_value = (0.0, 0.0, -3.14159)  # Min (vector)
    rand_yaw.inputs[1].default_value = (0.0, 0.0, 3.14159)   # Max (vector)

    instance = nodes.new('GeometryNodeInstanceOnPoints')
    instance.location = (-420, 100)
    links.new(group_in.outputs['Geometry'], distribute.inputs['Mesh'])
    links.new(distribute.outputs['Points'], instance.inputs['Points'])
    links.new(obj_info.outputs['Geometry'], instance.inputs['Instance'])
    links.new(rand_yaw.outputs[0], instance.inputs['Rotation'])
    links.new(rand_scale.outputs[1], instance.inputs['Scale'])

    # -- WIND: Noise Texture (scale ~2.0) linked to Scene Time (#frame) --------
    position = nodes.new('GeometryNodeInputPosition')
    position.location = (-420, -360)

    # Soften the sampling field so the noise reads as a smooth rolling wave
    # while the Noise Texture's own Scale stays at the requested ~2.0.
    field_scale = nodes.new('ShaderNodeVectorMath')
    field_scale.location = (-240, -360)
    field_scale.operation = 'SCALE'
    field_scale.inputs['Scale'].default_value = WIND_FIELD

    scene_time = nodes.new('GeometryNodeInputSceneTime')
    scene_time.location = (-420, -560)

    time_mul = nodes.new('ShaderNodeMath')            # #frame -> wind phase
    time_mul.location = (-240, -560)
    time_mul.operation = 'MULTIPLY'
    time_mul.inputs[1].default_value = WIND_SPEED

    noise = nodes.new('ShaderNodeTexNoise')
    noise.location = (-40, -420)
    noise.noise_dimensions = '4D'                     # 4th dim = animated time
    noise.inputs['Scale'].default_value = NOISE_SCALE
    noise.inputs['Detail'].default_value = 2.0

    links.new(position.outputs['Position'], field_scale.inputs[0])
    links.new(field_scale.outputs['Vector'], noise.inputs['Vector'])
    links.new(scene_time.outputs['Frame'], time_mul.inputs[0])
    links.new(time_mul.outputs['Value'], noise.inputs['W'])

    # Map noise 0..1 into a sway angle.  Biasing below 0.5 makes the blades
    # lean into a prevailing wind direction while the noise adds the waves.
    centre = nodes.new('ShaderNodeMath')
    centre.location = (180, -420)
    centre.operation = 'SUBTRACT'
    centre.inputs[1].default_value = 0.35

    amp = nodes.new('ShaderNodeMath')
    amp.location = (360, -420)
    amp.operation = 'MULTIPLY'
    amp.inputs[1].default_value = WIND_STRENGTH * 1.8

    # Build a tilt euler (sway mostly around X, a little around Y).
    sway_y = nodes.new('ShaderNodeMath')
    sway_y.location = (360, -600)
    sway_y.operation = 'MULTIPLY'
    sway_y.inputs[1].default_value = 0.5

    combine = nodes.new('ShaderNodeCombineXYZ')
    combine.location = (540, -480)

    links.new(noise.outputs['Fac'], centre.inputs[0])
    links.new(centre.outputs['Value'], amp.inputs[0])
    links.new(amp.outputs['Value'], combine.inputs['X'])
    links.new(amp.outputs['Value'], sway_y.inputs[0])
    links.new(sway_y.outputs['Value'], combine.inputs['Y'])

    rotate = nodes.new('GeometryNodeRotateInstances')
    rotate.location = (540, 100)
    links.new(instance.outputs['Instances'], rotate.inputs['Instances'])
    links.new(combine.outputs['Vector'], rotate.inputs['Rotation'])

    # Keep the ground mesh visible together with the swaying grass.
    join = nodes.new('GeometryNodeJoinGeometry')
    join.location = (720, 40)
    links.new(group_in.outputs['Geometry'], join.inputs['Geometry'])
    links.new(rotate.outputs['Instances'], join.inputs['Geometry'])
    links.new(join.outputs['Geometry'], group_out.inputs['Geometry'])

    return ground


# ============================================================================
# 4. The anime tree.
# ============================================================================
def make_trunk(material):
    bpy.ops.mesh.primitive_cylinder_add(radius=0.35, depth=4.0, vertices=12,
                                        location=(0, 0, 2.0))
    trunk = bpy.context.active_object
    trunk.name = 'Trunk'
    for poly in trunk.data.polygons:
        poly.use_smooth = True

    # Subdivision Surface for a soft, rounded trunk.
    subsurf = trunk.modifiers.new('Subsurf', 'SUBSURF')
    subsurf.levels = 2
    subsurf.render_levels = 2

    # Displace with a Clouds texture for organic, painterly irregularity.
    tex = bpy.data.textures.new('TrunkClouds', type='CLOUDS')
    tex.noise_scale = 0.4
    displace = trunk.modifiers.new('Displace', 'DISPLACE')
    displace.texture = tex
    displace.texture_coords = 'LOCAL'
    displace.strength = 0.25

    trunk.data.materials.append(material)
    return trunk


def make_foliage(material):
    # 3a. Fluffy canopy from several overlapping ico-spheres.
    centre = Vector((0.0, 0.0, 4.4))
    offsets = [
        (0.0, 0.0, 0.35), (0.95, 0.15, 0.0), (-0.85, -0.2, 0.05),
        (0.2, 0.9, -0.1), (-0.25, -0.85, -0.05), (0.15, -0.1, 0.85),
        (-0.6, 0.55, 0.4),
    ]
    balls = []
    for i in range(min(CANOPY_BALLS, len(offsets))):
        ox, oy, oz = offsets[i]
        bpy.ops.mesh.primitive_ico_sphere_add(
            subdivisions=2, radius=1.15,
            location=(centre.x + ox, centre.y + oy, centre.z + oz))
        ball = bpy.context.active_object
        ball.scale = (1.0, 1.0, 0.9)
        balls.append(ball)

    # 3b. Join them into one "Foliage" object.
    bpy.ops.object.select_all(action='DESELECT')
    for ball in balls:
        ball.select_set(True)
    bpy.context.view_layer.objects.active = balls[0]
    bpy.ops.object.join()
    foliage = bpy.context.view_layer.objects.active
    foliage.name = 'Foliage'
    for poly in foliage.data.polygons:      # smooth shading blends the lumps
        poly.use_smooth = True

    # 3c. Anime shading: copy Custom Normals from one big smooth sphere so the
    #     canopy lights like a single soft cloud instead of many spheres.
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=2.5,
                                        location=centre)
    normal_target = bpy.context.active_object
    normal_target.name = 'CanopyNormalTarget'
    for poly in normal_target.data.polygons:
        poly.use_smooth = True
    normal_target.hide_render = True         # invisible helper
    normal_target.display_type = 'WIRE'

    # Some Blender versions need auto-smooth on to honour custom normals.
    try:
        foliage.data.use_auto_smooth = True
    except Exception:
        pass

    dt = foliage.modifiers.new('AnimeNormals', 'DATA_TRANSFER')
    dt.object = normal_target
    dt.use_loop_data = True
    dt.data_types_loops = {'CUSTOM_NORMAL'}
    dt.loop_mapping = 'POLYINTERP_NEAREST'

    foliage.data.materials.append(material)
    return foliage, normal_target


# ============================================================================
# 5. Lighting + world.
# ============================================================================
def setup_lighting_and_world(scene):
    # Warm 45-degree sun.
    sun_data = bpy.data.lights.new('Sun', 'SUN')
    sun_data.energy = 3.0
    sun_data.color = (1.0, 0.93, 0.72)      # slight warm yellow tint
    try:
        sun_data.angle = math.radians(2.0)  # softer contact shadows
    except Exception:
        pass
    sun = bpy.data.objects.new('Sun', sun_data)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(45.0), 0.0, math.radians(35.0))

    # Clear anime sky-blue world.
    world = scene.world or bpy.data.worlds.new('World')
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get('Background')
    if bg is None:
        bg = world.node_tree.nodes.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (0.42, 0.68, 1.0, 1.0)
    bg.inputs['Strength'].default_value = 1.05


def setup_camera(scene):
    cam_data = bpy.data.cameras.new('Camera')
    cam_data.lens = 42.0
    cam = bpy.data.objects.new('Camera', cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = (10.5, -12.0, 5.4)
    # Aim the camera at the middle of the tree.
    target = Vector((0.0, 0.0, 3.0))
    direction = target - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam


# ============================================================================
# 6. Render settings -- Eevee (required for Shader to RGB).
# ============================================================================
def setup_render(scene):
    for engine in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
        try:
            scene.render.engine = engine
            break
        except Exception:
            continue
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.film_transparent = False
    try:
        scene.eevee.taa_render_samples = 24
        scene.eevee.taa_samples = 12
    except Exception:
        pass
    scene.frame_start = 1
    scene.frame_end = 120
    scene.frame_set(1)


# ============================================================================
# Build everything.
# ============================================================================
def main():
    scene = bpy.context.scene
    clean_slate()

    # Materials -------------------------------------------------------------
    grass_mat = make_toon_material(
        'ToonGrass', shadow_col=(0.01, 0.22, 0.20, 1.0),
        light_col=(0.11, 0.75, 0.34, 1.0))              # teal -> emerald
    ground_mat = make_toon_material(
        'ToonGround', shadow_col=(0.02, 0.15, 0.14, 1.0),
        light_col=(0.06, 0.40, 0.22, 1.0))
    foliage_mat = make_toon_material(
        'ToonFoliage', shadow_col=(0.08, 0.28, 0.12, 1.0),
        light_col=(0.72, 0.86, 0.26, 1.0),              # forest -> warm lime
        boundary=0.52)                                  # clear cel terminator
    trunk_mat = make_toon_material(
        'ToonTrunk', shadow_col=(0.16, 0.09, 0.05, 1.0),
        light_col=(0.55, 0.35, 0.20, 1.0), boundary=0.5)

    # Grass -----------------------------------------------------------------
    blade = make_grass_blade(grass_mat)
    build_grass_field(blade, ground_mat)

    # Tree ------------------------------------------------------------------
    make_trunk(trunk_mat)
    make_foliage(foliage_mat)

    # Stage -----------------------------------------------------------------
    setup_lighting_and_world(scene)
    setup_camera(scene)
    setup_render(scene)

    print('[generate_scene] Ghibli scene built: '
          + str(len(bpy.data.objects)) + ' objects, engine='
          + scene.render.engine)

    # Headless: render a mid-wind still so the pipeline is verifiable.
    if bpy.app.background:
        out = os.environ.get('GHIBLI_RENDER_OUT')
        if not out:
            try:
                base = os.path.dirname(os.path.abspath(__file__))
            except NameError:
                base = os.getcwd()
            out = os.path.join(base, 'ghibli_scene_render.png')
        scene.frame_set(40)                 # a frame where the wind has moved
        scene.render.filepath = out
        print('[generate_scene] Rendering still to ' + out)
        bpy.ops.render.render(write_still=True)
        print('[generate_scene] Render complete.')


if __name__ == '__main__':
    main()
'''


# ---------------------------------------------------------------------------
# Launcher logic
# ---------------------------------------------------------------------------
def script_dir() -> str:
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.getcwd()


def write_child_script(directory: str) -> str:
    path = os.path.join(directory, "generate_scene.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(SCENE_CODE)
    print("Wrote scene builder -> " + path)
    return path


def find_blender() -> str | None:
    """Locate a Blender executable across operating systems."""
    # 1. Explicit override via environment variable.
    for var in ("BLENDER", "BLENDER_PATH", "BLENDER_EXECUTABLE"):
        candidate = os.environ.get(var)
        if candidate and os.path.isfile(candidate):
            return candidate

    # 2. Anything already on PATH.
    on_path = shutil.which("blender") or shutil.which("blender.exe")
    if on_path:
        return on_path

    system = platform.system()
    candidates: list[str] = []

    if system == "Windows":
        program_dirs = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ]
        for base in program_dirs:
            candidates += glob.glob(
                os.path.join(base, "Blender Foundation", "Blender*", "blender.exe"))
        candidates += glob.glob(
            r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe")

    elif system == "Darwin":
        candidates += [
            "/Applications/Blender.app/Contents/MacOS/Blender",
            os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"),
        ]
        candidates += glob.glob(
            "/Applications/Blender*/Blender.app/Contents/MacOS/Blender")

    else:  # Linux / other Unix
        candidates += [
            "/usr/bin/blender", "/usr/local/bin/blender",
            "/opt/blender/blender", "/snap/bin/blender",
        ]
        candidates += glob.glob("/opt/blender*/blender")
        candidates += glob.glob(os.path.expanduser("~/blender*/blender"))
        # Flatpak install is handled specially below.
        if shutil.which("flatpak"):
            candidates.append("FLATPAK")

    for candidate in candidates:
        if candidate == "FLATPAK":
            return "FLATPAK"
        if os.path.isfile(candidate):
            return candidate
    return None


def build_command(blender: str, child_path: str, background: bool) -> list[str]:
    if blender == "FLATPAK":
        cmd = ["flatpak", "run", "org.blender.Blender"]
    else:
        cmd = [blender]
    if background:
        cmd.append("--background")
    cmd += ["--python", child_path]
    return cmd


def pause_if_windows() -> None:
    if platform.system() == "Windows":
        try:
            input("Press Enter to close...")
        except EOFError:
            pass


def main() -> int:
    directory = script_dir()
    child_path = write_child_script(directory)

    background = ("--background" in sys.argv or "-b" in sys.argv
                 or bool(os.environ.get("GHIBLI_HEADLESS")))

    blender = find_blender()
    if not blender:
        print("\nCould not find Blender on this system.")
        print("Fix: install Blender from https://www.blender.org/download/")
        print("     or set the BLENDER environment variable to its full path,")
        print("     e.g.  BLENDER=/path/to/blender python ghibli_scene_generator.py")
        pause_if_windows()
        return 1

    label = "flatpak org.blender.Blender" if blender == "FLATPAK" else blender
    print("Using Blender: " + label)

    command = build_command(blender, child_path, background)
    print("Launching: " + " ".join(command))
    try:
        result = subprocess.run(command)
    except FileNotFoundError:
        print("Failed to start Blender (executable not runnable): " + label)
        pause_if_windows()
        return 1
    except KeyboardInterrupt:
        return 130

    if result.returncode != 0:
        print("Blender exited with code " + str(result.returncode))
        pause_if_windows()
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
