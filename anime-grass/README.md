# Anime Grass (2026 workflow)

Rebuild of Trung Duy Nguyen’s **Anime Grass Tutorial | 2026 Update**
([video](https://youtu.be/3F5qaLC8TRY)) for **Blender 5.2+**.

## What’s in here
- `Scatter on Surface` (Blender essentials asset) for grass + flowers
- Double-sided blade with **Data Transfer** flat normals (painterly)
- Diffuse → Shader to RGB cel + **world-space** normal map via `TexSync` empty
- Noise blur + world/tangent normal mix (tutorial tricks)
- Texture mask for grass/dirt in the shader (instances stay light)
- Simple wind injected into Scatter’s instance rotation
- Shadows off (required for this look)

## Open
```bash
# Blender 5.2+ (you’re on 5.2.1 — perfect)
blender anime-grass/anime_grass.blend
```
`Z` → **Rendered**. Move/scale **`TexSync`** to slide the painted clumps.

## Rebuild
```bash
/path/to/blender-5.2+ --background --factory-startup \
  --python anime-grass/build_anime_grass.py -- --stills-only
```

Needs Blender’s `geometry_nodes_essentials.blend` (ships with 5.x).
