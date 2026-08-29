# VOIDSEED

A procedural Geometry Nodes organism for Blender 4.2+.

One node tree builds:

- a living noise-displaced icosphere shell
- a **dual-mesh geodesic web** (Mesh → Dual → Curves → tube mesh)
- **crystal spines** instanced on Poisson-disk points, aligned to normals
- emissive spore motes
- a molten core

Exposed modifier knobs: `Seed`, `Growth`, `Chaos`, `Spine Density`, `Spine Length`, `Web Thickness`, `Pulse`.

## Open it

```bash
blender voidseed/voidseed.blend
```

Select `VOIDSEED` → Modifiers → tweak inputs. Scrub the timeline — Growth / Chaos / Pulse are keyed, and the camera orbits.

## Rebuild from scratch (optional)

Needs Blender 4.2+ on PATH (or pass the binary explicitly):

```bash
blender --background --factory-startup --python voidseed/build_voidseed.py
```

This regenerates `voidseed.blend`, stills in `voidseed/renders/`, and an anim frame sequence.

## What’s cool about the graph

| Trick | Nodes |
|---|---|
| Breathing surface | `Noise Texture` (4D) + `Scene Time` → `Set Position` along normals |
| Hex lattice | `Dual Mesh` → `Mesh to Curve` → `Curve to Mesh` |
| Spikes | `Distribute Points on Faces` (Poisson) → `Instance on Points` (cones) + `Align Euler to Vector` |
| Growth | single `Growth` float scales density, length, and overall size |
