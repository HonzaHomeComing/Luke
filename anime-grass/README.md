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
The cel shading **only shows in Eevee Rendered view**:

1. Render engine: **Eevee** (Render Properties)
2. Viewport shading: **Rendered** (top-right sphere, or `Z` → Rendered)
3. Color Management → View Transform: **Standard**

**Solid** / wireframe mode will look flat — that’s normal.

Move/scale the `TexSync` empty to slide the painted shadow pattern.

## Rebuild
```bash
blender --background --factory-startup --python anime-grass/build_anime_grass.py -- --stills-only
```
