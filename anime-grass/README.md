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
Cel shading only shows in **Eevee Rendered** view (`Z` → Rendered). Solid looks flat.
Engine: **Eevee** · View Transform: **Standard**. Click **Allow** if asked about scripts.

## Shadows look wrong?
Anime grass does **not** use real Eevee shadow maps (those make black acne on thin blades).
Cel shadows come from the **normal map clumps** via Diffuse → Shader-to-RGB.

- Keep **Render Properties → Shadows** off (this file ships that way)
- Sun/Fill should have **Shadow** unchecked
- Move/scale **`TexSync`** to slide/resize the painted clump shadows
- Viewport must be **Rendered** (`Z` → Rendered)

## Rebuild
```bash
blender --background --factory-startup --python anime-grass/build_anime_grass.py -- --stills-only
```
