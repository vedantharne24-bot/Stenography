/*
 * Hero 3D scene: encryption -> embedding -> detection, as one object.
 *  - encrypted data core (icosahedron lattice + glowing nucleus)
 *  - image fragments (procedural pixel tiles) orbiting the core
 *  - encrypted packets streaming from module nodes into the core (instanced)
 *  - scanning rings + a sweeping detection beam
 *  - module nodes: hover reveals the module, click opens it
 *  - threat particles drifting through the field
 * Scroll progress (0..1) drives convergence; pointer drives parallax.
 */
import { Html, PerformanceMonitor } from '@react-three/drei'
import { Canvas, useFrame, useThree, type ThreeEvent } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'

const ACCENT = new THREE.Color('#5ce1e6')
const BONE = new THREE.Color('#ece7df')
const THREAT = new THREE.Color('#d03b3b')

export interface SceneNode {
  key: string
  label: string
  sub: string
  route: string
}

interface SceneProps {
  progress: { current: number }
  tier: 'low' | 'high'
  reducedMotion: boolean
  nodes: SceneNode[]
  onNavigate: (route: string) => void
}

/** Deterministic PRNG (mulberry32) so scene layouts are stable across renders. */
function seeded(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function pixelTexture(seed: number): THREE.DataTexture {
  const size = 16
  const data = new Uint8Array(size * size * 4)
  let s = seed * 9301 + 49297
  const rand = () => ((s = (s * 9301 + 49297) % 233280) / 233280)
  const base = 40 + rand() * 60
  for (let i = 0; i < size * size; i++) {
    const x = i % size
    const y = Math.floor(i / size)
    const v = base + Math.sin((x + seed) * 0.6) * 30 + Math.cos((y - seed) * 0.5) * 30 + rand() * 18
    const hidden = rand() < 0.06 // a few "modified" pixels glow cyan
    data[i * 4] = hidden ? 92 : v
    data[i * 4 + 1] = hidden ? 225 : v * 0.97
    data[i * 4 + 2] = hidden ? 230 : v * 0.92
    data[i * 4 + 3] = 255
  }
  const tex = new THREE.DataTexture(data, size, size, THREE.RGBAFormat)
  tex.magFilter = THREE.NearestFilter
  tex.minFilter = THREE.NearestFilter
  tex.needsUpdate = true
  return tex
}

function Core({ progress }: { progress: { current: number } }) {
  const lattice = useRef<THREE.Mesh>(null)
  const nucleus = useRef<THREE.Mesh>(null)
  const material = useRef<THREE.MeshBasicMaterial>(null)
  useFrame((state, delta) => {
    const p = progress.current
    if (lattice.current) {
      lattice.current.rotation.y += delta * (0.12 + p * 0.5)
      lattice.current.rotation.x += delta * 0.05
      const s = 1 - p * 0.18
      lattice.current.scale.setScalar(s)
    }
    if (nucleus.current) {
      const pulse = 1 + Math.sin(state.clock.elapsedTime * 2.2) * 0.04
      nucleus.current.scale.setScalar(0.62 * pulse * (1 + p * 0.25))
    }
    if (material.current) material.current.opacity = 0.18 + p * 0.25
  })
  return (
    <group>
      <mesh ref={lattice}>
        <icosahedronGeometry args={[1.25, 1]} />
        <meshBasicMaterial color={BONE} wireframe transparent opacity={0.35} />
      </mesh>
      <mesh ref={nucleus}>
        <icosahedronGeometry args={[1, 3]} />
        <meshBasicMaterial ref={material} color={ACCENT} transparent opacity={0.2} />
      </mesh>
      <mesh scale={0.38}>
        <sphereGeometry args={[1, 24, 24]} />
        <meshBasicMaterial color={ACCENT} />
      </mesh>
    </group>
  )
}

function Rings({ progress }: { progress: { current: number } }) {
  const group = useRef<THREE.Group>(null)
  const beam = useRef<THREE.Mesh>(null)
  useFrame((state, delta) => {
    if (group.current) {
      group.current.children.forEach((child, i) => {
        child.rotation.z += delta * (0.15 + i * 0.07) * (i % 2 ? -1 : 1) * (1 + progress.current * 2)
      })
    }
    if (beam.current) {
      // Detection beam sweeps vertically through the scene.
      beam.current.position.y = Math.sin(state.clock.elapsedTime * 0.7) * 2.2
      ;(beam.current.material as THREE.MeshBasicMaterial).opacity = 0.05 + progress.current * 0.1
    }
  })
  return (
    <>
      <group ref={group}>
        {[2.1, 2.6, 3.4].map((r, i) => (
          <mesh key={r} rotation={[Math.PI / 2 + i * 0.35, i * 0.4, 0]}>
            <torusGeometry args={[r, 0.006, 6, 160, Math.PI * (1.4 + i * 0.2)]} />
            <meshBasicMaterial color={i === 1 ? ACCENT : BONE} transparent opacity={i === 1 ? 0.7 : 0.25} />
          </mesh>
        ))}
      </group>
      <mesh ref={beam} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[9, 9]} />
        <meshBasicMaterial color={ACCENT} transparent opacity={0.05} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
    </>
  )
}

function Fragments({ count, progress }: { count: number; progress: { current: number } }) {
  const textures = useMemo(() => Array.from({ length: count }, (_, i) => pixelTexture(i + 3)), [count])
  const refs = useRef<(THREE.Mesh | null)[]>([])
  const phases = useMemo(() => Array.from({ length: count }, (_, i) => ({ r: 3 + (i % 3) * 0.55, a: (i / count) * Math.PI * 2, y: ((i % 4) - 1.5) * 0.7, s: 0.12 + (i % 3) * 0.04 })), [count])
  useEffect(() => () => textures.forEach((t) => t.dispose()), [textures])
  useFrame((state) => {
    const t = state.clock.elapsedTime
    const p = progress.current
    refs.current.forEach((mesh, i) => {
      if (!mesh) return
      const ph = phases[i]
      const r = ph.r * (1 - p * 0.45)
      const a = ph.a + t * ph.s
      mesh.position.set(Math.cos(a) * r, ph.y + Math.sin(t * 0.8 + i) * 0.12, Math.sin(a) * r)
      mesh.lookAt(state.camera.position)
    })
  })
  return (
    <>
      {textures.map((tex, i) => (
        <mesh key={i} ref={(m) => { refs.current[i] = m }}>
          <planeGeometry args={[0.55, 0.55]} />
          <meshBasicMaterial map={tex} transparent opacity={0.9} />
        </mesh>
      ))}
    </>
  )
}

function Packets({ count, sources, progress }: { count: number; sources: THREE.Vector3[]; progress: { current: number } }) {
  const mesh = useRef<THREE.InstancedMesh>(null)
  const instanceTransform = useMemo(() => new THREE.Object3D(), [])
  const seeds = useMemo(() => {
    const rand = seeded(7)
    return Array.from({ length: count }, (_, i) => ({ src: i % sources.length, offset: rand(), speed: 0.12 + rand() * 0.18, wobble: rand() * Math.PI * 2 }))
  }, [count, sources.length])
  useFrame((state) => {
    if (!mesh.current) return
    const t = state.clock.elapsedTime
    const speedUp = 1 + progress.current * 2.5
    seeds.forEach((s, i) => {
      const k = (s.offset + t * s.speed * speedUp) % 1
      const from = sources[s.src]
      // Quadratic curve from node to core with a lifted control point.
      const ctrl = from.clone().multiplyScalar(0.5).add(new THREE.Vector3(0, 1.2 * Math.sin(s.wobble), 0))
      const a = from.clone().multiplyScalar((1 - k) * (1 - k))
      const b = ctrl.multiplyScalar(2 * (1 - k) * k)
      instanceTransform.position.copy(a.add(b))
      instanceTransform.scale.setScalar(0.035 * (1 - k * 0.6))
      instanceTransform.rotation.set(t + i, t * 0.7 + i, 0)
      instanceTransform.updateMatrix()
      mesh.current!.setMatrixAt(i, instanceTransform.matrix)
    })
    mesh.current.instanceMatrix.needsUpdate = true
  })
  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, count]}>
      <boxGeometry args={[1, 1, 1]} />
      <meshBasicMaterial color={ACCENT} transparent opacity={0.85} />
    </instancedMesh>
  )
}

function Particles({ count }: { count: number }) {
  const points = useRef<THREE.Points>(null)
  const { positions, colors } = useMemo(() => {
    const rand = seeded(42)
    const pos = new Float32Array(count * 3)
    const col = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const r = 4 + rand() * 9
      const theta = rand() * Math.PI * 2
      const phi = Math.acos(2 * rand() - 1)
      pos[i * 3] = r * Math.sin(phi) * Math.cos(theta)
      pos[i * 3 + 1] = r * Math.cos(phi) * 0.6
      pos[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta)
      const roll = rand()
      const c = roll < 0.06 ? THREAT : roll < 0.3 ? ACCENT : BONE
      col.set([c.r, c.g, c.b], i * 3)
    }
    return { positions: pos, colors: col }
  }, [count])
  useFrame((_, delta) => {
    if (points.current) points.current.rotation.y += delta * 0.015
  })
  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[colors, 3]} />
      </bufferGeometry>
      <pointsMaterial size={0.035} vertexColors transparent opacity={0.65} sizeAttenuation depthWrite={false} />
    </points>
  )
}

function ModuleNode({ node, position, onNavigate }: { node: SceneNode; position: THREE.Vector3; onNavigate: (route: string) => void }) {
  const [hovered, setHovered] = useState(false)
  const mesh = useRef<THREE.Mesh>(null)
  useFrame((state) => {
    if (mesh.current) mesh.current.scale.setScalar((hovered ? 1.6 : 1) * (1 + Math.sin(state.clock.elapsedTime * 3 + position.x) * 0.06))
  })
  const over = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation()
    setHovered(true)
    document.body.style.cursor = 'pointer'
  }
  const out = () => {
    setHovered(false)
    document.body.style.cursor = ''
  }
  useEffect(() => () => { document.body.style.cursor = '' }, [])
  return (
    <group position={position}>
      <mesh ref={mesh} onPointerOver={over} onPointerOut={out} onClick={() => onNavigate(node.route)}>
        <octahedronGeometry args={[0.11, 0]} />
        <meshBasicMaterial color={hovered ? ACCENT : BONE} />
      </mesh>
      <mesh>
        <ringGeometry args={[0.2, 0.215, 32]} />
        <meshBasicMaterial color={ACCENT} transparent opacity={hovered ? 0.9 : 0.3} side={THREE.DoubleSide} />
      </mesh>
      <Html center distanceFactor={6} style={{ pointerEvents: 'none' }} zIndexRange={[4, 0]}>
        <div className={`whitespace-nowrap transition-opacity duration-200 ${hovered ? 'opacity-100' : 'opacity-60'}`} style={{ transform: 'translateY(-34px)' }}>
          <p className="font-mono text-[10px] tracking-[0.18em] text-ink uppercase">{node.label}</p>
          {hovered && <p className="font-mono text-[9px] text-accent">{node.sub} →</p>}
        </div>
      </Html>
    </group>
  )
}

function Rig({ reducedMotion }: { reducedMotion: boolean }) {
  const { camera, pointer } = useThree()
  useFrame(() => {
    if (reducedMotion) return
    camera.position.x += (pointer.x * 1.4 - camera.position.x) * 0.04
    camera.position.y += (0.6 + pointer.y * 0.8 - camera.position.y) * 0.04
    camera.lookAt(0, 0, 0)
  })
  return null
}

function Scene({ progress, tier, reducedMotion, nodes, onNavigate }: SceneProps) {
  const positions = useMemo(
    () => nodes.map((_, i) => {
      const a = (i / nodes.length) * Math.PI * 2 + 0.4
      return new THREE.Vector3(Math.cos(a) * 4.6, ((i % 2) - 0.5) * 1.6, Math.sin(a) * 4.6)
    }),
    [nodes],
  )
  const high = tier === 'high'
  return (
    <>
      <Rig reducedMotion={reducedMotion} />
      <Core progress={progress} />
      <Rings progress={progress} />
      <Fragments count={high ? 12 : 6} progress={progress} />
      <Packets count={high ? 220 : 70} sources={positions} progress={progress} />
      <Particles count={high ? 1800 : 450} />
      {nodes.map((node, i) => (
        <ModuleNode key={node.key} node={node} position={positions[i]} onNavigate={onNavigate} />
      ))}
    </>
  )
}

export default function HeroScene(props: SceneProps) {
  const container = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(true)
  const [dpr, setDpr] = useState<[number, number]>(props.tier === 'high' ? [1, 1.75] : [1, 1])

  // Pause rendering entirely when the hero is off-screen.
  useEffect(() => {
    const el = container.current
    if (!el) return
    const io = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { threshold: 0.01 })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  return (
    <div ref={container} className="absolute inset-0" aria-hidden>
      <Canvas
        dpr={dpr}
        camera={{ position: [0, 0.6, 8.5], fov: 42 }}
        gl={{ antialias: props.tier === 'high', powerPreference: 'high-performance', alpha: true }}
        frameloop={props.reducedMotion ? 'demand' : visible ? 'always' : 'never'}
      >
        <PerformanceMonitor onDecline={() => setDpr([1, 1])} onIncline={() => props.tier === 'high' && setDpr([1, 1.75])} />
        <fog attach="fog" args={['#08090b', 8, 18]} />
        <Scene {...props} />
      </Canvas>
    </div>
  )
}
