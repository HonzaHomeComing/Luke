# Anime Tree

Trung Duy Nguyen–style anime foliage
([video](https://youtu.be/52sTppv7Y-E)): leaf cards, painterly **Data Transfer**
normals from a sphere, Diffuse → Shader to RGB cel canopy + trunk.

## Open
```bash
blender anime-tree/anime_tree.blend
```
`Z` → **Rendered** (Eevee). Shadows stay off for the cel look.

## Rebuild
```bash
/path/to/blender-5.2+ --background --factory-startup \
  --python anime-tree/build_anime_tree.py -- --stills-only
```
