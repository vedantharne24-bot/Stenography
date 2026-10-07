import { motion, useMotionValueEvent, useScroll, useTransform } from 'framer-motion'
import { ArrowDown, ArrowRight } from 'lucide-react'
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Logo } from '../components/Logo'
import { CountUp, buttonClasses, cx } from '../components/ui'
import { useOverview, useDemo } from '../landing/data'
import { Architecture, CryptoPipeline, FinalCta, LiveDetection, ModelSection, Research, Robustness, Solution, SpotThePayload, Techniques } from '../landing/Sections'
import { Story } from '../landing/Story'
import { useAuth } from '../lib/auth'
import { pct } from '../lib/format'
import { useDeviceTier, usePrefersReducedMotion } from '../lib/hooks'
import type { SceneNode } from '../three/HeroScene'

const HeroScene = lazy(() => import('../three/HeroScene'))

const NODES: SceneNode[] = [
  { key: 'hide', label: 'Encrypt + embed', sub: 'Secure Hide', route: '/secure-hide' },
  { key: 'extract', label: 'Extract', sub: 'Recover payload', route: '/extract' },
  { key: 'detect', label: 'Detect', sub: 'Steganalysis', route: '/steganalysis' },
  { key: 'forensics', label: 'Forensics', sub: 'Evidence workup', route: '/forensics' },
  { key: 'attack', label: 'Attack lab', sub: 'Robustness', route: '/attack-lab' },
]

const ANCHORS = [
  ['problem', 'Problem'],
  ['pipeline', 'Pipeline'],
  ['ai-detection', 'Live AI'],
  ['techniques', 'Techniques'],
  ['research', 'Research'],
  ['architecture', 'Architecture'],
] as const

function LandingNav({ authed }: { authed: boolean }) {
  const { scrollY } = useScroll()
  const [solid, setSolid] = useState(false)
  useMotionValueEvent(scrollY, 'change', (y) => setSolid(y > 40))
  return (
    <nav className={cx('fixed inset-x-0 top-0 z-40 transition-colors duration-300', solid ? 'border-b border-line bg-bg/85 backdrop-blur' : 'border-b border-transparent')} aria-label="Primary">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-6 px-4 md:px-10">
        <Link to="/" aria-label="StegoLab home"><Logo /></Link>
        <ul className="hidden items-center gap-6 lg:flex">
          {ANCHORS.map(([id, label]) => (
            <li key={id}><a href={`#${id}`} className="font-mono text-[11px] tracking-[0.14em] text-ink-2 uppercase transition-colors hover:text-accent">{label}</a></li>
          ))}
        </ul>
        <div className="flex items-center gap-2">
          {!authed && <Link to="/login" className={buttonClasses('ghost', 'sm')}>Sign in</Link>}
          <Link to={authed ? '/dashboard' : '/login'} className={buttonClasses('primary', 'sm')}>Launch lab</Link>
        </div>
      </div>
    </nav>
  )
}

function Hero({ authed, overview }: { authed: boolean; overview: ReturnType<typeof useOverview>['data'] }) {
  const ref = useRef<HTMLElement>(null)
  const progress = useRef(0)
  const reduced = usePrefersReducedMotion()
  const tier = useDeviceTier()
  const navigate = useNavigate()
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end start'] })
  useMotionValueEvent(scrollYProgress, 'change', (p) => (progress.current = p))
  const textY = useTransform(scrollYProgress, [0, 1], [0, reduced ? 0 : 120])
  const textOpacity = useTransform(scrollYProgress, [0, 0.7], [1, 0])
  const [webgl, setWebgl] = useState(true)
  useEffect(() => {
    try {
      const c = document.createElement('canvas')
      setWebgl(Boolean(c.getContext('webgl2') || c.getContext('webgl')))
    } catch {
      setWebgl(false)
    }
  }, [])
  const cnn = overview?.models['steganalysis-cnn']
  const go = useCallback((route: string) => navigate(authed ? route : '/login', authed ? undefined : { state: { from: route } }), [authed, navigate])

  return (
    <section ref={ref} className="relative h-[100svh] min-h-[640px] overflow-hidden" aria-label="Introduction">
      <div className="grid-bg absolute inset-0 opacity-40" aria-hidden />
      <div className="absolute inset-0 md:left-[30%]">
        {webgl ? (
          <Suspense fallback={null}>
            <HeroScene progress={progress} tier={tier} reducedMotion={reduced} nodes={NODES} onNavigate={go} />
          </Suspense>
        ) : null}
      </div>
      <div className="pointer-events-none absolute inset-0 z-[5] bg-gradient-to-r from-bg via-bg/70 to-transparent md:via-bg/40" aria-hidden />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[5] h-40 bg-gradient-to-t from-bg to-transparent" aria-hidden />

      <motion.div style={{ y: textY, opacity: textOpacity }} className="pointer-events-none relative z-10 mx-auto flex h-full max-w-7xl flex-col justify-center px-4 pt-16 md:px-10">
        <motion.p initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="label-mono mb-6">
          <span className="text-accent">●</span> Information security × machine learning
        </motion.p>
        <h1 className="max-w-4xl font-display text-[clamp(2.9rem,8.6vw,7.4rem)] leading-[0.86] font-extrabold tracking-[0.01em] uppercase">
          {['AI-Enhanced', 'Secure Steganography', '& Steganalysis'].map((line, i) => (
            <motion.span key={line} className="block" initial={{ opacity: 0, y: 40 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 + i * 0.12, duration: 0.8, ease: [0.16, 1, 0.3, 1] }}>
              {i === 2 ? <><span className="font-serif font-normal text-accent normal-case italic">&amp;</span> Steganalysis</> : line}
            </motion.span>
          ))}
        </h1>
        <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.6 }} className="mt-6 max-w-xl text-lg leading-relaxed text-ink-2">
          Protect hidden information. Detect hidden threats. Analyze covert communication.
        </motion.p>
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.75 }} className="pointer-events-auto mt-8 flex flex-wrap gap-3">
          <Link to={authed ? '/dashboard' : '/login'} className={buttonClasses('primary', 'lg')}>
            Launch security lab <ArrowRight className="size-4" aria-hidden />
          </Link>
          <a href="#pipeline" className={buttonClasses('secondary', 'lg')}>
            See the pipeline <ArrowDown className="size-4" aria-hidden />
          </a>
        </motion.div>
      </motion.div>

      <div className="absolute inset-x-0 bottom-0 z-10 border-t border-line/70 bg-bg/60 backdrop-blur">
        <dl className="mx-auto grid max-w-7xl grid-cols-2 gap-y-3 px-4 py-4 md:grid-cols-4 md:px-10">
          {[
            ['Model accuracy (test)', cnn?.accuracy ? <CountUp value={cnn.accuracy * 100} format={(v) => `${v.toFixed(2)}%`} /> : '—'],
            ['Stego detection · FPR', cnn?.binary ? `${pct(cnn.binary.detection_rate, 1)} · ${pct(cnn.binary.false_positive_rate, 1)}` : '—'],
            ['Images analysed', overview ? <CountUp value={overview.counters.images_analyzed} /> : '—'],
            ['Payloads embedded', overview ? <CountUp value={overview.counters.embeddings} /> : '—'],
          ].map(([k, v]) => (
            <div key={k as string} className="border-l border-line pl-3">
              <dt className="label-mono">{k}</dt>
              <dd className="font-display text-2xl font-bold tabular">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  )
}

export default function Landing() {
  const { user } = useAuth()
  const authed = Boolean(user)
  const { data: overview } = useOverview()
  const demo = useDemo()
  const ensureDemo = useCallback(() => {
    if (!demo.demo && !demo.loading) demo.run('random')
  }, [demo])
  // Sections request the demo lazily via IntersectionObserver; this timer is a fallback for
  // environments where observers do not fire (background tabs, very old browsers).
  const ensureRef = useRef(ensureDemo)
  ensureRef.current = ensureDemo
  useEffect(() => {
    const timer = setTimeout(() => ensureRef.current(), 2500)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div className="bg-bg">
      <LandingNav authed={authed} />
      <main>
        <Hero authed={authed} overview={overview} />
        <SpotThePayload demo={demo.demo} loading={demo.loading} onRun={() => demo.run('random')} onNeedDemo={ensureDemo} />
        <Solution overview={overview} />
        <Story demo={demo.demo} onNeedDemo={ensureDemo} />
        <CryptoPipeline />
        <LiveDetection demo={demo.demo} loading={demo.loading} error={demo.error} onRun={(a) => demo.run(a)} />
        <Techniques overview={overview} />
        <ModelSection overview={overview} />
        <Robustness overview={overview} />
        <Research overview={overview} />
        <Architecture />
        <FinalCta authed={authed} />
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-8 font-mono text-[11px] text-ink-4 md:flex-row md:justify-between md:px-10">
          <span>StegoLab · AI-Enhanced Secure Steganography &amp; Steganalysis System</span>
          <span>AES-256-GCM · Argon2id · SHA-256 · LSB / DCT / DWT · StegoNet</span>
        </div>
      </footer>
    </div>
  )
}
