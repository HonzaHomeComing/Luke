# Anime Grass

Geometry Nodes meadow using the tutorial-style **normal map** workflow
(hand-painted cel shadows via object-space normals + Shader-to-RGB).

## Assets
- `textures/grass_normal.png` — the normal map you provided (drop-in replacement OK)

You do **not** need the full `.blend` from the tutorial — the normal map is the key art.

## Open
```bash
blender anime-grass/anime_grass.blend
```

## View it correctly
If the meadow looks flat / solid green with no painted shadows, you are in
**Solid** viewport mode. The cel look is an Emission + Shader-to-RGB setup —
it **only** appears in **Eevee Rendered** view. Solid mode always looks flat.

1. Press `Z` → **Rendered** (or click the top-right shaded sphere)
2. If Blender asks to allow scripts, click **Allow** (auto-switches to Rendered)
3. Render engine: **Eevee** · Color Management → View Transform: **Standard**

Move/scale the `TexSync` empty to slide the painted shadow pattern.

## Rebuild
```bash
blender --background --factory-startup --python anime-grass/build_anime_grass.py -- --stills-only
```
