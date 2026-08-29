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

Select `Ground` → modifier **AnimeGrass**. Move/scale the `TexSync` empty to slide the painted shadow pattern.

## Rebuild
```bash
blender --background --factory-startup --python anime-grass/build_anime_grass.py -- --stills-only
```
