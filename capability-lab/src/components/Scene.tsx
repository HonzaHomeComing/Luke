import { Canvas } from '@react-three/fiber'
import { ContactShadows, Environment, OrbitControls } from '@react-three/drei'
import type { Mesh } from 'three'
import {
  DemoObject,
  type MaterialKind,
  type Mode,
  type ShapeKind,
} from './DemoObject'
import type { HeightmapData } from '../lib/heightmap'

type Props = {
  mode: Mode
  shape: ShapeKind
  material: MaterialKind
  reliefStrength: number
  heightmap: HeightmapData
  autoRotate: boolean
  meshRef: React.RefObject<Mesh | null>
}

export function Scene({
  mode,
  shape,
  material,
  reliefStrength,
  heightmap,
  autoRotate,
  meshRef,
}: Props) {
  return (
    <Canvas
      shadows
      dpr={[1, 1.75]}
      camera={{ position: [2.6, 1.8, 3.2], fov: 42 }}
      gl={{ antialias: true, preserveDrawingBuffer: true }}
    >
      <color attach="background" args={['#071316']} />
      <fog attach="fog" args={['#071316', 8, 18]} />
      <ambientLight intensity={0.35} />
      <directionalLight
        castShadow
        position={[4, 6, 2]}
        intensity={1.35}
        shadow-mapSize={[1024, 1024]}
      />
      <spotLight position={[-4, 3, -2]} intensity={1.1} color="#2ec4b6" />
      <DemoObject
        mode={mode}
        shape={shape}
        material={material}
        reliefStrength={reliefStrength}
        heightmap={heightmap}
        autoRotate={autoRotate}
        meshRef={meshRef}
      />
      <ContactShadows
        position={[0, -1.25, 0]}
        opacity={0.55}
        scale={12}
        blur={2.5}
        far={4}
      />
      <Environment preset="city" />
      <OrbitControls
        makeDefault
        enablePan={false}
        minDistance={2}
        maxDistance={8}
        maxPolarAngle={Math.PI / 1.9}
      />
    </Canvas>
  )
}
