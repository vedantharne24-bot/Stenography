/*
 * Scroll storytelling: a pinned visual that transforms through six stages while the
 * narrative scrolls past. Stages 3-6 render the live demo (a real embedding + real
 * model inference on a held-out test image), so every number there is measured.
 */
import { AnimatePresence, motion, useMotionValueEvent, useScroll, useTransform } from 'framer-motion'
import { FileCheck2, KeyRound, Layers, Lock, ScanSearch, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ProbabilityBars } from '../components/charts'
import { RiskGauge } from '../components/RiskGauge'
import { TechniqueChip, cx } from '../components/ui'
import { num, pct } from '../lib/format'
import type { Demo } from './data'

const STAGES = [
  { key: 'secret', title: 'Secret data', icon: KeyRound, text: 'A message or file that must cross a monitored channel without drawing attention.' },
  { key: 'encrypt', title: 'Encryption', icon: Lock, text: 'Sealed with AES-256-GCM under an Argon2id-derived key; a SHA-256 digest binds the ciphertext.' },
  { key: 'embed', title: 'Stego embedding', icon: Layers, text: 'Ciphertext bits are written into pixels (LSB) or transform coefficients (DCT / DWT) — invisibly.' },
  { key: 'analyse', title: 'Steganalysis', icon: ScanSearch, text: 'A defender inspects the noise layer, where payloads live, with high-pass residuals and transform statistics.' },
  { key: 'detect', title: 'AI detection', icon: Sparkles, text: 'StegoNet classifies cover vs stego and names the technique; Grad-CAM shows where the evidence was found.' },
  { key: 'report', title: 'Security report', icon: FileCheck2, text: 'A transparent risk score, hashes and model version become a chain-of-custody report.' },
] as const

const SAMPLE = 'rendezvous 03:00 · pier 7 · bring the second key'
const HEX = '0123456789abcdef'

function Scramble({ text, active }: { text: string; active: boolean }) {
  const [out, setOut] = useState(text)
  useEffect(() => {
    if (!active) {
      setOut(text)
      return
    }
    let frame = 0
    const id = setInterval(() => {
      frame++
      setOut(
        text
          .split('')
          .map((c, i) => (i < frame * 1.5 ? HEX[(i * 7 + frame * 3) % 16] : c))
          .join(''),
      )
      if (frame * 1.5 > text.length + 4) clearInterval(id)
    }, 40)
    return () => clearInterval(id)
  }, [text, active])
  return <>{out}</>
}

function Frame({ children, label }: { children: ReactNode; label: string }) {
  return (
    <motion.div initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 1.02 }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }} className="bracket absolute inset-0 flex flex-col rounded-xs border border-line bg-surface/80 p-4 backdrop-blur md:p-6">
      <p className="label-mono mb-4">{label}</p>
      <div className="relative min-h-0 flex-1">{children}</div>
    </motion.div>
  )
}

function LiveImage({ src, alt, children }: { src?: string; alt: string; children?: ReactNode }) {
  return (
    <div className="checker relative h-full overflow-hidden rounded-xs border border-line">
      {src ? <img src={src} alt={alt} className="pixelated h-full w-full object-contain" /> : <div className="grid h-full place-items-center font-mono text-xs text-ink-4">live image unavailable</div>}
      {children}
    </div>
  )
}

function StageVisual({ stage, demo, scan }: { stage: number; demo: Demo | null; scan: number }) {
  switch (stage) {
    case 0:
      return (
        <Frame label="Plaintext · example message">
          <div className="flex h-full flex-col justify-center gap-4 font-mono">
            <p className="text-lg text-ink md:text-2xl">
              {SAMPLE}
              <span className="ml-1 inline-block h-5 w-2.5 animate-blink bg-accent align-middle" />
            </p>
            <p className="text-xs text-ink-3">The live demo below hides {demo ? `${demo.payload_bytes} random bytes` : 'a random payload'} — the server never sees a real secret.</p>
          </div>
        </Frame>
      )
    case 1:
      return (
        <Frame label="AES-256-GCM · Argon2id · SHA-256">
          <div className="flex h-full flex-col justify-center gap-5 font-mono">
            <p className="text-lg break-all text-accent md:text-2xl"><Scramble text={SAMPLE} active /></p>
            <div className="grid gap-2 text-xs text-ink-2 sm:grid-cols-2">
              <span>nonce · 96-bit random</span>
              <span>tag · 128-bit authentication</span>
              <span>KDF · Argon2id 64 MiB, t=3</span>
              <span>header bound as associated data</span>
            </div>
            {demo && <p className="truncate text-[11px] text-ink-3">live envelope SHA-256 · {demo.envelope_sha256}</p>}
          </div>
        </Frame>
      )
    case 2:
      return (
        <Frame label={demo ? `Embedding · ${demo.algorithm.toUpperCase()} · ${pct(demo.utilization)} of capacity` : 'Embedding'}>
          <div className="grid h-full grid-cols-2 gap-3">
            <LiveImage src={demo?.images.cover} alt="Held-out cover image" />
            <LiveImage src={demo?.images.difference} alt="Amplified pixel difference showing where bits landed" />
          </div>
          {demo && <p className="absolute right-0 bottom-0 left-0 translate-y-7 text-center font-mono text-[11px] text-ink-3">cover · |stego − cover| × 48 — PSNR {num(demo.quality.psnr, 2)} dB, SSIM {num(demo.quality.ssim, 4)}</p>}
        </Frame>
      )
    case 3:
      return (
        <Frame label="Steganalysis · scanning the noise layer">
          <LiveImage src={demo?.images.stego} alt="Stego image under inspection">
            <div className="pointer-events-none absolute inset-x-0" style={{ top: `${scan * 100}%` }}>
              <div className="h-16 -translate-y-full bg-gradient-to-b from-transparent to-accent/30" />
              <div className="h-0.5 bg-accent shadow-[0_0_18px_var(--color-accent)]" />
            </div>
          </LiveImage>
        </Frame>
      )
    case 4:
      return (
        <Frame label={demo ? `StegoNet v${demo.stego.model.version} · live inference` : 'AI detection'}>
          {demo ? (
            <div className="grid h-full gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <LiveImage src={demo.stego.overlay ?? demo.images.stego} alt="Grad-CAM overlay on the stego image" />
              <div className="flex flex-col justify-center gap-4">
                <div>
                  <p className="label-mono">Verdict</p>
                  <p className="font-display text-5xl font-extrabold uppercase">{demo.stego.prediction}</p>
                  <div className="mt-1 flex gap-3 text-sm text-ink-2">
                    P(stego) <span className="font-mono text-ink">{pct(demo.stego.p_stego)}</span>
                    <TechniqueChip technique={demo.stego.predicted_technique} />
                  </div>
                </div>
                <ProbabilityBars probs={demo.stego.probabilities} highlight={demo.stego.predicted_technique} compact />
                <p className="font-mono text-[11px] text-ink-3">same model on the clean cover: P(stego) {pct(demo.cover.p_stego)}</p>
              </div>
            </div>
          ) : (
            <p className="text-sm text-ink-3">Live inference loads when the API is running.</p>
          )}
        </Frame>
      )
    default:
      return (
        <Frame label="Security report">
          {demo ? (
            <div className="grid h-full items-center gap-6 md:grid-cols-[auto_minmax(0,1fr)]">
              <RiskGauge score={demo.stego.risk.score} level={demo.stego.risk.level} size={200} />
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 font-mono text-xs">
                <dt className="text-ink-3">carrier</dt><dd className="truncate text-ink">{demo.carrier}</dd>
                <dt className="text-ink-3">technique</dt><dd className="text-ink">{demo.algorithm.toUpperCase()} → predicted {demo.stego.predicted_technique.toUpperCase()}</dd>
                <dt className="text-ink-3">payload</dt><dd className="text-ink">{demo.payload_bytes} B · utilisation {pct(demo.utilization)}</dd>
                <dt className="text-ink-3">quality</dt><dd className="text-ink">PSNR {num(demo.quality.psnr, 2)} dB · SSIM {num(demo.quality.ssim, 4)}</dd>
                <dt className="text-ink-3">sha-256</dt><dd className="truncate text-ink">{demo.envelope_sha256}</dd>
                <dt className="text-ink-3">model</dt><dd className="text-ink">{demo.stego.model.name} v{demo.stego.model.version}</dd>
                <dd className="col-span-2 mt-2 font-sans text-sm leading-relaxed text-ink-2">{demo.stego.risk.recommendation}</dd>
              </dl>
            </div>
          ) : (
            <p className="text-sm text-ink-3">Report data loads with the live demo.</p>
          )}
        </Frame>
      )
  }
}

export function Story({ demo, onNeedDemo }: { demo: Demo | null; onNeedDemo: () => void }) {
  const ref = useRef<HTMLElement>(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })
  const [stage, setStage] = useState(0)
  const [scan, setScan] = useState(0)
  const bar = useTransform(scrollYProgress, [0, 1], ['0%', '100%'])
  useMotionValueEvent(scrollYProgress, 'change', (p) => {
    setStage(Math.min(STAGES.length - 1, Math.floor(p * STAGES.length)))
    const local = (p * STAGES.length) % 1
    setScan(local)
  })
  // Fetch the live demo shortly before the story reaches the data-driven stages.
  const requested = useRef(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && !requested.current) {
        requested.current = true
        onNeedDemo()
      }
    }, { rootMargin: '600px 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [onNeedDemo])
  const Icon = useMemo(() => STAGES[stage].icon, [stage])

  return (
    <section ref={ref} id="pipeline" className="relative" style={{ height: `${STAGES.length * 90}vh` }} aria-label="How StegoLab works, step by step">
      <div className="sticky top-0 flex h-dvh flex-col justify-center overflow-hidden px-4 py-16 md:px-10">
        <div className="mx-auto grid w-full max-w-7xl gap-8 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.3fr)] md:gap-14">
          <div className="flex flex-col justify-center">
            <p className="label-mono mb-4 text-accent">The pipeline · scroll</p>
            <ol className="flex flex-col gap-1">
              {STAGES.map((s, i) => (
                <li key={s.key} className={cx('border-l-2 py-2 pl-4 transition-colors duration-300', i === stage ? 'border-accent' : 'border-line')}>
                  <p className={cx('font-display text-2xl font-bold tracking-wide uppercase transition-colors md:text-3xl', i === stage ? 'text-ink' : i < stage ? 'text-ink-3' : 'text-ink-4')}>
                    <span className="mr-3 font-mono text-xs text-ink-4">0{i + 1}</span>
                    {s.title}
                  </p>
                  <AnimatePresence initial={false}>
                    {i === stage && (
                      <motion.p initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden text-sm leading-relaxed text-ink-2">
                        <span className="block pt-1">{s.text}</span>
                      </motion.p>
                    )}
                  </AnimatePresence>
                </li>
              ))}
            </ol>
            <div className="mt-6 h-px w-full bg-line"><motion.div className="h-px bg-accent" style={{ width: bar }} /></div>
          </div>
          <div className="relative h-[46vh] md:h-[62vh]">
            <div className="absolute -top-8 right-0 flex items-center gap-2 font-mono text-[11px] text-ink-3">
              <Icon className="size-3.5 text-accent" aria-hidden /> stage {stage + 1}/6
            </div>
            <AnimatePresence mode="wait">
              <StageVisual key={stage} stage={stage} demo={demo} scan={scan} />
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  )
}
