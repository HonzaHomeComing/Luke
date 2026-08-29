# Anime Grass (Geometry Nodes)

A Blender 4.2 Geometry Nodes meadow inspired by anime-style grass workflows
(like [this tutorial](https://youtu.be/M4kMri55rdE)):

1. **Vertex-mask growth** — color attribute `Grass` paints where blades spawn (and dirt paths stay bare)
2. **GN scatter** — distribute points → instance low-poly blades → random yaw/scale → realize
3. **Cel shader** — Shader-to-RGB value ramp + terrain color mix (grass vs dirt)
4. **Normal transfer** — displaced detail mesh + Data Transfer (custom normals) for painted-looking shading
5. **Wind** — 4D noise waves tilt instances and darken a `wind` attribute in the shader

## Open

```bash
blender anime-grass/anime_grass.blend
```

Select `Ground` → Modifiers → **AnimeGrass**:

| Input | What it does |
|---|---|
| Density | How much grass |
| Scale | Blade size |
| Wind Speed / Strength | Sway |
| Seed | Variation |

Paint the `Grass` color attribute in Vertex Paint to reshape meadows/paths — white grows grass, black is dirt.

## Rebuild

```bash
blender --background --factory-startup --python anime-grass/build_anime_grass.py
# stills only:
blender --background --factory-startup --python anime-grass/build_anime_grass.py -- --stills-only
```
