import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import {
  BufferAttribute,
  BufferGeometry,
  DoubleSide,
  type Mesh,
} from 'three'
import type { HeightmapData } from '../lib/heightmap'

export type ShapeKind = 'icosahedron' | 'torus' | 'box' | 'sphere'
export type MaterialKind = 'metal' | 'clay' | 'glass' | 'toon'
export type Mode = 'shapes' | 'relief' | 'materials' | 'motion'

type Props = {
  mode: Mode
  shape: ShapeKind
  material: MaterialKind
  reliefStrength: number
  heightmap: HeightmapData
  autoRotate: boolean
  meshRef: React.RefObject<Mesh | null>
}

function materialProps(kind: MaterialKind) {
  switch (kind) {
    case 'metal':
      return {
        color: '#d7dde0',
        metalness: 1,
        roughness: 0.18,
        transmission: 0,
        opacity: 1,
        transparent: false,
      }
    case 'clay':
      return {
        color: '#ff8f6b',
        metalness: 0,
        roughness: 0.92,
        transmission: 0,
        opacity: 1,
        transparent: false,
      }
    case 'glass':
      return {
        color: '#b8fff5',
        metalness: 0,
        roughness: 0.05,
        transmission: 0.85,
        opacity: 1,
        transparent: true,
      }
    case 'toon':
      return {
        color: '#e8ff47',
        metalness: 0.05,
        roughness: 0.55,
        transmission: 0,
        opacity: 1,
        transparent: false,
      }
  }
}

function Geometry({ shape }: { shape: ShapeKind }) {
  switch (shape) {
    case 'torus':
      return <torusKnotGeometry args={[0.7, 0.24, 128, 24]} />
    case 'box':
      return <boxGeometry args={[1.4, 1.4, 1.4]} />
    case 'sphere':
      return <sphereGeometry args={[1, 64, 64]} />
    default:
      return <icosahedronGeometry args={[1.15, 1]} />
  }
}

function buildReliefGeometry(heightmap: HeightmapData, strength: number) {
  const { width, height, values } = heightmap
  const positions = new Float32Array(width * height * 3)
  const indices: number[] = []

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = y * width + x
      const u = x / (width - 1)
      const v = y / (height - 1)
      positions[i * 3] = (u - 0.5) * 2.4
      positions[i * 3 + 1] = values[i] * strength
      positions[i * 3 + 2] = (v - 0.5) * 2.4
    }
  }

  for (let y = 0; y < height - 1; y += 1) {
    for (let x = 0; x < width - 1; x += 1) {
      const a = y * width + x
      const b = a + 1
      const c = a + width
      const d = c + 1
      indices.push(a, c, b, b, c, d)
    }
  }

  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new BufferAttribute(positions, 3))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  return geometry
}

function ReliefMesh({
  heightmap,
  strength,
  meshRef,
  autoRotate,
}: {
  heightmap: HeightmapData
  strength: number
  meshRef: React.RefObject<Mesh | null>
  autoRotate: boolean
}) {
  const local = useRef<Mesh>(null)
  const mat = materialProps('clay')
  const geometry = useMemo(
    () => buildReliefGeometry(heightmap, strength),
    [heightmap, strength],
  )

  useEffect(() => () => geometry.dispose(), [geometry])

  useFrame((_, dt) => {
    const mesh = local.current
    if (!mesh) return
    if (autoRotate) mesh.rotation.y += dt * 0.35
    ;(meshRef as React.MutableRefObject<Mesh | null>).current = mesh
  })

  return (
    <mesh
      ref={local}
      geometry={geometry}
      rotation={[-Math.PI / 2.6, 0, 0]}
      castShadow
      receiveShadow
    >
      <meshPhysicalMaterial
        color={mat.color}
        metalness={mat.metalness}
        roughness={mat.roughness}
        flatShading
        side={DoubleSide}
      />
    </mesh>
  )
}

export function DemoObject({
  mode,
  shape,
  material,
  reliefStrength,
  heightmap,
  autoRotate,
  meshRef,
}: Props) {
  const local = useRef<Mesh>(null)
  const activeMaterial = material
  const mat = materialProps(activeMaterial)
  const spin = mode === 'motion' || autoRotate

  useFrame((state, dt) => {
    const mesh = local.current
    if (!mesh || mode === 'relief') return
    if (spin) mesh.rotation.y += dt * (mode === 'motion' ? 0.7 : 0.35)
    if (mode === 'motion') {
      mesh.position.y = Math.sin(state.clock.elapsedTime * 1.4) * 0.18
      mesh.rotation.x = Math.sin(state.clock.elapsedTime * 0.6) * 0.25
    } else {
      mesh.position.y = 0
      if (!spin) mesh.rotation.x = 0.2
    }
    ;(meshRef as React.MutableRefObject<Mesh | null>).current = mesh
  })

  if (mode === 'relief') {
    return (
      <ReliefMesh
        heightmap={heightmap}
        strength={reliefStrength}
        meshRef={meshRef}
        autoRotate={autoRotate}
      />
    )
  }

  return (
    <mesh ref={local} castShadow receiveShadow>
      <Geometry shape={shape} />
      {activeMaterial === 'toon' ? (
        <meshToonMaterial color={mat.color} />
      ) : (
        <meshPhysicalMaterial
          color={mat.color}
          metalness={mat.metalness}
          roughness={mat.roughness}
          transmission={mat.transmission}
          transparent={mat.transparent}
          opacity={mat.opacity}
          thickness={1.2}
        />
      )}
    </mesh>
  )
}
