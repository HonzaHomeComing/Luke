import { useMemo, useRef, useState } from 'react'
import type { Mesh } from 'three'
import { Scene } from './components/Scene'
import type { MaterialKind, Mode, ShapeKind } from './components/DemoObject'
import { exportMeshAsGlb } from './lib/exportGlb'
import { imageFileToHeightmap, makeDemoHeightmap } from './lib/heightmap'

const MODES: { id: Mode; label: string; title: string; blurb: string }[] = [
  {
    id: 'shapes',
    label: 'Procedural shapes',
    title: 'Generate geometry in code',
    blurb: 'Swap primitives and parametric forms — the same approach behind Blender scripts and asset generators.',
  },
  {
    id: 'relief',
    label: 'PNG → 3D relief',
    title: 'Turn an image into mesh',
    blurb: 'Upload a PNG and build a heightfield. Same idea as your image → Blender model pipeline, in the browser.',
  },
  {
    id: 'materials',
    label: 'Materials',
    title: 'PBR & stylized looks',
    blurb: 'Metal, clay, glass, toon — material graphs and export-ready shading for web, games, or product shots.',
  },
  {
    id: 'motion',
    label: 'Motion',
    title: 'Animate & present',
    blurb: 'Turntables, idle motion, and camera-friendly presentation for portfolios and configurators.',
  },
]

const SHAPES: ShapeKind[] = ['icosahedron', 'torus', 'box', 'sphere']
const MATERIALS: MaterialKind[] = ['metal', 'clay', 'glass', 'toon']

export default function App() {
  const meshRef = useRef<Mesh | null>(null)
  const [mode, setMode] = useState<Mode>('shapes')
  const [shape, setShape] = useState<ShapeKind>('icosahedron')
  const [material, setMaterial] = useState<MaterialKind>('metal')
  const [reliefStrength, setReliefStrength] = useState(0.85)
  const [autoRotate, setAutoRotate] = useState(true)
  const [status, setStatus] = useState('Drag to orbit · scroll to zoom')
  const [heightmap, setHeightmap] = useState(() => makeDemoHeightmap())

  const active = useMemo(() => MODES.find((m) => m.id === mode)!, [mode])

  async function onUpload(file: File | undefined) {
    if (!file) return
    try {
      setStatus('Building relief mesh…')
      const map = await imageFileToHeightmap(file)
      setHeightmap(map)
      setMode('relief')
      setStatus(`Relief ready from ${file.name}`)
    } catch {
      setStatus('Could not read that image')
    }
  }

  async function onExport() {
    const mesh = meshRef.current
    if (!mesh) {
      setStatus('Nothing to export yet')
      return
    }
    try {
      setStatus('Exporting GLB…')
      await exportMeshAsGlb(mesh, `forge-${mode}`)
      setStatus('GLB downloaded')
    } catch {
      setStatus('Export failed')
    }
  }

  return (
    <div className="app">
      <div className="canvas-wrap">
        <Scene
          mode={mode}
          shape={shape}
          material={material}
          reliefStrength={reliefStrength}
          heightmap={heightmap}
          autoRotate={autoRotate}
          meshRef={meshRef}
        />
      </div>
      <div className="grain" aria-hidden />

      <div className="hud">
        <div>
          <div className="top">
            <h1 className="brand">
              FOR<span>GE</span>
            </h1>
            <div className="badge">Cursor capability lab</div>
          </div>
          <div className="hero-copy">
            <h2>A tiny sandbox of what we can build in 3D</h2>
            <p>
              Interactive shapes, image-to-mesh relief, materials, motion, and GLB
              export — click a mode and poke around.
            </p>
          </div>
        </div>

        <div className="spacer" />

        <div className="dock">
          <div className="modes" role="tablist" aria-label="Capabilities">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                role="tab"
                aria-selected={mode === m.id}
                className={`mode-btn${mode === m.id ? ' active' : ''}`}
                onClick={() => {
                  setMode(m.id)
                  setStatus(m.label)
                }}
              >
                {m.label}
              </button>
            ))}
          </div>
          <div className="actions">
            <button
              type="button"
              className="action ghost"
              onClick={() => setAutoRotate((v) => !v)}
            >
              {autoRotate ? 'Pause spin' : 'Resume spin'}
            </button>
            <button type="button" className="action primary" onClick={onExport}>
              Export GLB
            </button>
          </div>
        </div>
      </div>

      <aside className="panel" aria-live="polite">
        <h3>{active.title}</h3>
        <p>{active.blurb}</p>

        {(mode === 'shapes' || mode === 'motion') && (
          <div className="row">
            <label htmlFor="shape">Shape</label>
            <select
              id="shape"
              value={shape}
              onChange={(e) => setShape(e.target.value as ShapeKind)}
            >
              {SHAPES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        )}

        {mode === 'materials' && (
          <div className="row">
            <label htmlFor="material">Material</label>
            <select
              id="material"
              value={material}
              onChange={(e) => setMaterial(e.target.value as MaterialKind)}
            >
              {MATERIALS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        )}

        {mode === 'relief' && (
          <>
            <div className="row">
              <label htmlFor="strength">Relief strength</label>
              <input
                id="strength"
                type="range"
                min={0.15}
                max={1.6}
                step={0.05}
                value={reliefStrength}
                onChange={(e) => setReliefStrength(Number(e.target.value))}
              />
            </div>
            <div className="row">
              <label>Source image</label>
              <label className="file-btn">
                Upload PNG / JPG
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={(e) => onUpload(e.target.files?.[0])}
                />
              </label>
              <div className="hint">Or keep the built-in demo heightmap.</div>
            </div>
          </>
        )}

        {mode === 'motion' && (
          <div className="hint">Idle bob + turntable for product-style presentation.</div>
        )}
      </aside>

      <div className="status">{status}</div>
    </div>
  )
}
