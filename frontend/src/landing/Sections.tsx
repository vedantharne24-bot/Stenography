import { AnimatePresence, motion } from 'framer-motion'
import { ArrowRight, Check, ChevronDown, Eye, Play, RefreshCw, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ChartTooltip, ConfusionMatrix, Legend, ProbabilityBars, VIZ, axisProps } from '../components/charts'
import { CompareSlider } from '../components/CompareSlider'
import { TerminalLog } from '../components/TerminalLog'
import { Button, CountUp, Segmented, TECHNIQUE_COLOR, TechniqueChip, buttonClasses, cx } from '../components/ui'
import { num, pct } from '../lib/format'
import type { Algorithm } from '../lib/types'
import type { Demo, Overview } from './data'

const ALGOS: Algorithm[] = ['lsb', 'dct', 'dwt']

export function SectionHead({ index, kicker, title, children }: { index: string; kicker: string; title: ReactNode; children?: ReactNode }) {
  return (
    <motion.header initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-80px' }} transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }} className="mb-10 max-w-3xl">
      <p className="label-mono mb-3"><span className="text-accent">{index}</span> <span className="text-ink-4">/</span> {kicker}</p>
      <h2 className="font-display text-4xl leading-[0.95] font-bold tracking-wide uppercase md:text-6xl">{title}</h2>
      {children && <div className="mt-4 text-base leading-relaxed text-ink-2">{children}</div>}
    </motion.header>
  )
}

function Unavailable({ what }: { what: string }) {
  return <p className="rounded-xs border border-dashed border-line-strong p-4 font-mono text-xs text-ink-3">{what} will appear once the API is running and the pipeline has produced it.</p>
}

/* ------------------------------------------------------------------ problem: spot the payload */

export function SpotThePayload({ demo, loading, onRun, onNeedDemo }: { demo: Demo | null; loading: boolean; onRun: () => void; onNeedDemo: () => void }) {
  const [guess, setGuess] = useState<number | null>(null)
  const sectionRef = useRef<HTMLElement>(null)
  // Request the live demo shortly before this section scrolls into view (lazy: no request for bounce visits).
  useEffect(() => {
    const el = sectionRef.current
    if (!el) return
    const io = new IntersectionObserver(([entry]) => entry.isIntersecting && onNeedDemo(), { rootMargin: '400px 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [onNeedDemo])
  const order = useMemo(() => (demo ? (demo.envelope_sha256.charCodeAt(0) % 2 === 0 ? [0, 1] : [1, 0]) : [0, 1]), [demo])
  const images = demo ? [demo.images.cover, demo.images.stego] : []
  const stegoSlot = order.indexOf(1)
  return (
    <section ref={sectionRef} className="mx-auto max-w-7xl px-4 py-24 md:px-10 md:py-32" id="problem">
      <SectionHead index="01" kicker="The problem" title={<>Hidden information <span className="font-serif font-normal text-accent normal-case italic">evades</span> inspection</>}>
        Firewalls, DLP filters and human reviewers see an ordinary photo. One of these two held-out test images carries an encrypted payload embedded live by the server. Which one?
      </SectionHead>
      <div className="grid gap-4 md:grid-cols-2">
        {demo
          ? order.map((which, slot) => {
              const revealed = guess !== null
              const isStego = which === 1
              return (
                <button
                  key={slot}
                  type="button"
                  onClick={() => setGuess(slot)}
                  disabled={revealed}
                  className={cx('bracket group relative overflow-hidden rounded-xs border text-left transition-colors', revealed ? (isStego ? 'border-serious' : 'border-line') : 'border-line hover:border-accent')}
                  aria-label={`Image ${slot + 1}${revealed ? (isStego ? ' — stego' : ' — cover') : ''}`}
                >
                  <img src={images[which]} alt="" className="pixelated block aspect-square w-full object-cover" />
                  <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-bg/95 to-transparent px-4 pt-10 pb-3">
                    <span className="font-mono text-xs tracking-widest text-ink uppercase">Image {slot + 1}</span>
                    {revealed ? (
                      <span className={cx('font-mono text-xs tracking-widest uppercase', isStego ? 'text-serious' : 'text-ink-2')}>{isStego ? `stego · ${demo.algorithm}` : 'clean cover'}</span>
                    ) : (
                      <span className="font-mono text-xs text-ink-3 group-hover:text-accent">select →</span>
                    )}
                  </div>
                </button>
              )
            })
          : [0, 1].map((i) => <div key={i} className="checker aspect-square animate-pulse-soft rounded-xs border border-line" />)}
      </div>
      <AnimatePresence>
        {demo && guess !== null && (
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 grid gap-6 rounded-xs border border-line bg-surface p-5 md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-center">
            <span className={cx('grid size-12 place-items-center rounded-full border', guess === stegoSlot ? 'border-ok text-ok-ink' : 'border-critical text-critical-ink')}>
              {guess === stegoSlot ? <Check className="size-5" /> : <X className="size-5" />}
            </span>
            <p className="text-sm leading-relaxed text-ink-2">
              {guess === stegoSlot ? 'Correct — but only a coin-flip for a human. ' : 'Missed it — as most people do. '}
              The payload is <span className="text-ink">{demo.payload_bytes} bytes</span> of AES-256-GCM ciphertext; the two images differ by PSNR <span className="text-ink">{num(demo.quality.psnr, 2)} dB</span>, SSIM <span className="text-ink">{num(demo.quality.ssim, 4)}</span>. StegoNet flagged the stego image with P(stego) <span className="text-ink">{pct(demo.stego.p_stego)}</span> vs <span className="text-ink">{pct(demo.cover.p_stego)}</span> for the cover.
            </p>
            <Button variant="secondary" icon={RefreshCw} onClick={() => { setGuess(null); onRun() }} loading={loading}>New pair</Button>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  )
}

/* ------------------------------------------------------------------ solution */

export function Solution({ overview }: { overview: Overview | null }) {
  const cnn = overview?.models['steganalysis-cnn']
  const q = overview?.dataset?.embedding_quality
  const items = [
    { k: 'Encrypt', v: '256-bit', sub: 'AES-GCM key · Argon2id KDF · 128-bit auth tag', note: 'confidentiality + integrity before anything is hidden' },
    { k: 'Embed', v: q ? `${num(Math.min(q.lsb.psnr.mean, q.dct.psnr.mean, q.dwt.psnr.mean), 1)} dB` : '—', sub: 'lowest per-technique mean PSNR across the generated dataset (LSB · DCT · DWT)', note: 'invisible to the eye (> 40 dB)' },
    { k: 'Detect', v: cnn?.accuracy ? pct(cnn.accuracy, 2) : '—', sub: cnn ? `StegoNet v${cnn.version} 4-class accuracy · ${cnn.samples?.toLocaleString()} held-out images` : 'awaiting trained model', note: 'measured on the untouched test split' },
  ]
  return (
    <section className="border-y border-line bg-surface" id="solution">
      <div className="mx-auto grid max-w-7xl md:grid-cols-[minmax(0,0.8fr)_repeat(3,minmax(0,1fr))]">
        <div className="border-b border-line px-4 py-10 md:border-r md:border-b-0 md:px-10">
          <p className="label-mono mb-3"><span className="text-accent">02</span> / The solution</p>
          <p className="font-display text-3xl leading-none font-bold uppercase">Defence in depth</p>
          <p className="mt-3 text-sm text-ink-2">Encryption protects the content, steganography hides the channel, AI steganalysis exposes channels others hide.</p>
        </div>
        {items.map((item, i) => (
          <motion.div key={item.k} initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }} transition={{ delay: i * 0.12 }} className="border-b border-line px-4 py-10 last:border-b-0 md:border-r md:border-b-0 md:px-8 md:last:border-r-0">
            <p className="label-mono">{item.k}</p>
            <p className="mt-2 font-display text-5xl font-bold">{item.v}</p>
            <p className="mt-2 text-sm text-ink-2">{item.sub}</p>
            <p className="mt-1 font-mono text-[11px] text-ink-3">{item.note}</p>
          </motion.div>
        ))}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ crypto pipeline (expandable) */

const PIPE = [
  { k: 'Plaintext', d: 'Message or file (≤ 2 MB). zlib-compressed only if it shrinks; its SHA-256 is sealed inside the ciphertext.' },
  { k: 'Argon2id', d: 'Passphrase → 256-bit key with 64 MiB memory, 3 passes, 4 lanes and a fresh 128-bit salt. Or: a CSPRNG-generated raw key shown once.' },
  { k: 'AES-256-GCM', d: 'Authenticated encryption via OpenSSL (cryptography lib). 96-bit random nonce; the 39-byte header (KDF params, salt, nonce) is bound as associated data.' },
  { k: 'SHA-256 frame', d: 'The envelope plus SHA-256(envelope) form the frame body; a Reed-Solomon-protected header stores algorithm and length. Integrity is checkable without the key.' },
  { k: 'Embed', d: 'Frame bits are dispersed over carrier slots by a Weyl permutation, then written by LSB replacement or QIM on DCT/DWT coefficients, with a self-check on the rendered 8-bit image.' },
  { k: 'Stego PNG', d: 'Saved losslessly; only the ICC profile is kept — other metadata is stripped. MSE, PSNR and SSIM are computed against the cover.' },
]

export function CryptoPipeline() {
  const [open, setOpen] = useState(2)
  return (
    <section className="mx-auto max-w-7xl px-4 py-24 md:px-10" id="secure-communication">
      <SectionHead index="04" kicker="Secure communication" title="Seal, frame, conceal">Every step is a real primitive — click a stage for the exact parameters used by the backend.</SectionHead>
      <ol className="grid gap-px overflow-hidden rounded-xs border border-line bg-line md:grid-cols-6">
        {PIPE.map((p, i) => (
          <li key={p.k} className="bg-bg">
            <button type="button" onClick={() => setOpen(i)} aria-expanded={open === i} className={cx('flex h-full w-full flex-col gap-3 p-4 text-left transition-colors', open === i ? 'bg-surface' : 'hover:bg-surface/60')}>
              <span className="flex items-center justify-between font-mono text-[10px] text-ink-4">
                0{i + 1}
                {i < PIPE.length - 1 && <ArrowRight className="hidden size-3 md:block" aria-hidden />}
              </span>
              <span className={cx('font-display text-xl font-bold tracking-wide uppercase', open === i ? 'text-accent' : 'text-ink')}>{p.k}</span>
              <ChevronDown className={cx('size-4 text-ink-4 transition-transform md:hidden', open === i && 'rotate-180')} aria-hidden />
            </button>
          </li>
        ))}
      </ol>
      <AnimatePresence mode="wait">
        <motion.p key={open} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mt-4 max-w-3xl border-l-2 border-accent pl-4 text-sm leading-relaxed text-ink-2">
          <span className="mr-2 font-mono text-xs text-accent uppercase">{PIPE[open].k}</span>
          {PIPE[open].d}
        </motion.p>
      </AnimatePresence>
    </section>
  )
}

/* ------------------------------------------------------------------ live AI detection */

export function LiveDetection({ demo, loading, error, onRun }: { demo: Demo | null; loading: boolean; error: string | null; onRun: (a: Algorithm | 'random') => void }) {
  const [algo, setAlgo] = useState<Algorithm | 'random'>('random')
  return (
    <section className="border-y border-line bg-surface" id="ai-detection">
      <div className="mx-auto max-w-7xl px-4 py-24 md:px-10">
        <SectionHead index="05" kicker="AI detection · live" title="A real inference, right here">
          The server picks a held-out image, hides a random payload, and runs StegoNet + the Random Forest on both versions. Nothing below is pre-rendered.
        </SectionHead>
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <Segmented label="Technique" value={algo} onChange={setAlgo} options={[{ value: 'random', label: 'Random' }, { value: 'lsb', label: 'LSB' }, { value: 'dct', label: 'DCT' }, { value: 'dwt', label: 'DWT' }]} />
          <Button variant="primary" icon={Play} onClick={() => onRun(algo)} loading={loading}>Run live analysis</Button>
          {error && <span className="text-sm text-critical-ink">{error}</span>}
        </div>
        {demo ? (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <CompareSlider before={demo.images.cover} after={demo.stego.overlay ?? demo.images.stego} beforeLabel="Cover" afterLabel="Stego · Grad-CAM" />
            <div className="flex flex-col gap-5">
              <div className="grid grid-cols-2 gap-5">
                {(['cover', 'stego'] as const).map((side) => (
                  <div key={side}>
                    <p className="label-mono mb-2">{side === 'cover' ? 'Clean cover' : `Stego · ${demo.algorithm.toUpperCase()}`}</p>
                    <p className="font-display text-3xl font-bold uppercase">{demo[side].prediction}</p>
                    <p className="mb-3 font-mono text-xs text-ink-3">P(stego) {pct(demo[side].p_stego)} · risk {demo[side].risk.score.toFixed(1)} {demo[side].risk.level}</p>
                    <ProbabilityBars probs={demo[side].probabilities} highlight={demo[side].predicted_technique} compact />
                  </div>
                ))}
              </div>
              <TerminalLog events={demo.trace} status="success" title={`inference · ${demo.carrier}`} maxHeight="max-h-52" />
            </div>
          </div>
        ) : (
          <div className="grid h-72 place-items-center rounded-xs border border-dashed border-line-strong font-mono text-xs text-ink-3">{loading ? 'embedding + analysing…' : 'Press “Run live analysis”'}</div>
        )}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ techniques (interactive mini-visuals) */

function LsbViz() {
  const [value, setValue] = useState(182)
  const bits = value.toString(2).padStart(8, '0').split('')
  return (
    <div>
      <div className="flex gap-1" role="group" aria-label="Pixel value bits">
        {bits.map((b, i) => (
          <button key={i} type="button" onClick={() => i === 7 && setValue((v) => v ^ 1)} disabled={i !== 7} className={cx('grid h-10 flex-1 place-items-center rounded-[2px] border font-mono text-sm', i === 7 ? 'border-lsb text-ink hover:bg-lsb/20' : 'border-line text-ink-3')} aria-label={i === 7 ? 'Toggle least-significant bit' : undefined}>
            {b}
          </button>
        ))}
      </div>
      <p className="mt-3 font-mono text-xs text-ink-2">value {value} · flipping bit 0 changes it by exactly 1 of 255</p>
    </div>
  )
}

const JPEG_Q50 = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
const DCT_POS = new Set(['1,2', '2,1', '2,2', '0,3', '3,0'])

function DctViz() {
  const [hover, setHover] = useState<[number, number] | null>([2, 2])
  return (
    <div>
      <div className="grid grid-cols-8 gap-0.5" role="grid" aria-label="8 by 8 DCT block">
        {Array.from({ length: 64 }, (_, i) => {
          const u = Math.floor(i / 8)
          const v = i % 8
          const used = DCT_POS.has(`${u},${v}`)
          return <div key={i} role="gridcell" onMouseEnter={() => setHover([u, v])} onFocus={() => setHover([u, v])} tabIndex={-1} className={cx('aspect-square rounded-[1px]', used ? 'bg-dct' : 'bg-raised hover:bg-line-strong')} style={{ opacity: used ? 1 : 0.4 + (1 - (u + v) / 14) * 0.6 }} />
        })}
      </div>
      <p className="mt-3 font-mono text-xs text-ink-2">{hover ? `(${hover[0]},${hover[1]}) · JPEG Q50 step ${JPEG_Q50[hover[0] * 8 + hover[1]]}${DCT_POS.has(`${hover[0]},${hover[1]}`) ? ' · carries 1 bit (QIM Δ=24)' : ''}` : 'hover a coefficient'}</p>
    </div>
  )
}

function DwtViz() {
  const [band, setBand] = useState('LH3')
  const cells = [
    { k: 'LL3', x: 0, y: 0, s: 1 }, { k: 'HL3', x: 1, y: 0, s: 1 }, { k: 'LH3', x: 0, y: 1, s: 1 }, { k: 'HH3', x: 1, y: 1, s: 1 },
    { k: 'HL2', x: 2, y: 0, s: 2 }, { k: 'LH2', x: 0, y: 2, s: 2 }, { k: 'HH2', x: 2, y: 2, s: 2 },
    { k: 'HL1', x: 4, y: 0, s: 4 }, { k: 'LH1', x: 0, y: 4, s: 4 }, { k: 'HH1', x: 4, y: 4, s: 4 },
  ]
  return (
    <div>
      <svg viewBox="0 0 8 8" className="aspect-square w-full" role="img" aria-label="Three-level Haar wavelet decomposition">
        {cells.map((c) => {
          const used = c.k === 'LH3' || c.k === 'HL3'
          return (
            <rect key={c.k} x={c.x + 0.04} y={c.y + 0.04} width={c.s - 0.08} height={c.s - 0.08} rx={0.06} fill={used ? 'var(--color-dwt)' : 'var(--color-raised)'} stroke={band === c.k ? 'var(--color-ink)' : 'var(--color-line-strong)'} strokeWidth={0.04} onMouseEnter={() => setBand(c.k)} />
          )
        })}
      </svg>
      <p className="mt-3 font-mono text-xs text-ink-2">{band}{band === 'LH3' || band === 'HL3' ? ' · carries payload (QIM Δ=40)' : band === 'LL3' ? ' · approximation, untouched' : ' · detail band, untouched'}</p>
    </div>
  )
}

export function Techniques({ overview }: { overview: Overview | null }) {
  const exp = overview?.latest_experiment
  const q = overview?.dataset?.embedding_quality
  const cards: { a: Algorithm; title: string; body: string; viz: ReactNode }[] = [
    { a: 'lsb', title: 'Least significant bit', body: 'Replace bit 0 of R, G and B. Three bits per pixel, ±1 grey level — but any lossy processing destroys it.', viz: <LsbViz /> },
    { a: 'dct', title: 'Discrete cosine transform', body: 'Quantisation-index modulation on five mid-frequency coefficients of each 8×8 luma block, protected by Reed-Solomon.', viz: <DctViz /> },
    { a: 'dwt', title: 'Discrete wavelet transform', body: 'QIM on the level-3 Haar detail subbands. Coarse structure survives compression; capacity is the price.', viz: <DwtViz /> },
  ]
  return (
    <section className="mx-auto max-w-7xl px-4 py-24 md:px-10" id="techniques">
      <SectionHead index="06" kicker="Techniques" title="Three ways to hide">Interact with each mechanism. Numbers come from the latest stored research run{exp ? ` (${String(exp.config.images)} held-out images)` : ''}.</SectionHead>
      <div className="grid gap-px overflow-hidden rounded-xs border border-line bg-line lg:grid-cols-3">
        {cards.map((c) => {
          const s = exp?.summary[c.a]
          return (
            <div key={c.a} className="flex flex-col gap-5 bg-bg p-6">
              <div className="flex items-center justify-between">
                <TechniqueChip technique={c.a} />
                <span className="font-mono text-[10px] text-ink-4">{overview?.algorithms.find((x) => x.name === c.a)?.domain}</span>
              </div>
              <h3 className="font-display text-3xl font-bold uppercase">{c.title}</h3>
              <p className="text-sm leading-relaxed text-ink-2">{c.body}</p>
              <div className="rounded-xs border border-line bg-surface p-4">{c.viz}</div>
              <dl className="mt-auto grid grid-cols-3 gap-2 border-t border-line pt-4 font-mono text-xs">
                <div><dt className="text-ink-4">capacity</dt><dd className="text-ink">{s ? `${num(s.capacity_bpp, 3)} bpp` : '—'}</dd></div>
                <div><dt className="text-ink-4">PSNR</dt><dd className="text-ink">{s ? num(s.psnr, 1) : q ? num(q[c.a].psnr.mean, 1) : '—'} dB</dd></div>
                <div><dt className="text-ink-4">robust</dt><dd className="text-ink">{s ? pct(s.robustness, 0) : '—'}</dd></div>
              </dl>
            </div>
          )
        })}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ AI model */

export function ModelSection({ overview }: { overview: Overview | null }) {
  const cnn = overview?.models['steganalysis-cnn']
  const rf = overview?.models['steganalysis-rf']
  const branches = [
    { k: 'Spatial residuals', d: '10 SRM high-pass kernels × RGB, truncated ±3 → 5 conv blocks', c: 'Exposes LSB noise' },
    { k: 'Block-DCT histogram', d: '63 fixed 8×8 DCT bases (stride 8) → learnable projection → soft histogram', c: 'Sees quantisation lattices' },
    { k: 'Wavelet histogram', d: 'Haar level-2/3 details → soft histogram → convs', c: 'Sees wavelet-domain QIM' },
  ]
  return (
    <section className="border-y border-line bg-surface" id="model">
      <div className="mx-auto max-w-7xl px-4 py-24 md:px-10">
        <SectionHead index="07" kicker="AI · StegoNet" title="Built to see noise, not content">
          Generic vision CNNs learn what an image shows. StegoNet starts from three fixed forensic front-ends — one per embedding domain — and learns everything after them. A Random Forest on 99 handcrafted features gives independent evidence.
        </SectionHead>
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-2">
            {branches.map((b, i) => (
              <motion.div key={b.k} initial={{ opacity: 0, x: -16 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.1 }} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 rounded-xs border border-line bg-bg p-4">
                <div>
                  <p className="font-display text-xl font-bold uppercase">{b.k}</p>
                  <p className="mt-1 font-mono text-xs text-ink-3">{b.d}</p>
                </div>
                <span className="font-mono text-[11px] text-accent">{b.c}</span>
              </motion.div>
            ))}
            <div className="flex items-center gap-3 px-4 py-2 font-mono text-xs text-ink-3">
              <ArrowRight className="size-4 text-accent" aria-hidden /> global average pooling → MLP → softmax over normal · LSB · DCT · DWT · Grad-CAM on each branch head
            </div>
          </div>
          <div className="flex flex-col gap-5">
            {cnn ? (
              <>
                <div className="grid grid-cols-3 gap-4">
                  {[['Accuracy', cnn.accuracy], ['Macro F1', cnn.f1], ['ROC-AUC', cnn.roc_auc]].map(([k, v]) => (
                    <div key={k as string} className="border-l border-line pl-3">
                      <p className="label-mono">{k}</p>
                      <p className="font-display text-3xl font-bold">{v === null ? '—' : <CountUp value={(v as number) * 100} format={(x) => `${x.toFixed(2)}%`} />}</p>
                    </div>
                  ))}
                </div>
                <p className="font-mono text-[11px] text-ink-3">StegoNet v{cnn.version} · {cnn.samples?.toLocaleString()} held-out test images · binary detection {pct(cnn.binary?.detection_rate, 2)} at FPR {pct(cnn.binary?.false_positive_rate, 2)}{rf?.accuracy ? ` · Random Forest ${pct(rf.accuracy, 2)}` : ''}</p>
                {cnn.confusion_matrix && <ConfusionMatrix matrix={cnn.confusion_matrix} />}
              </>
            ) : (
              <Unavailable what="Model metrics" />
            )}
          </div>
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ attack lab + research */

export function Robustness({ overview }: { overview: Overview | null }) {
  const exp = overview?.latest_experiment
  const data = exp ? Object.keys(exp.summary.lsb.per_attack).map((label) => ({ label: label.split(':')[0].replace('_', ' ') + ' ' + (label.split(':')[1] ?? '').replace(/[a-z_]+=/g, ''), ...Object.fromEntries(ALGOS.map((a) => [a, exp.summary[a].per_attack[label] ?? 0])) })) : []
  return (
    <section className="mx-auto max-w-7xl px-4 py-24 md:px-10" id="attack-lab">
      <SectionHead index="08" kicker="Attack lab" title="What survives the real world">Compression, noise, blur and resizing are applied to stego images and the payload is re-extracted and SHA-256-verified. Survival rates from the latest research run:</SectionHead>
      {exp ? (
        <>
          <Legend items={ALGOS.map((a) => ({ label: a.toUpperCase(), color: TECHNIQUE_COLOR[a] }))} />
          <div className="mt-3 h-80">
            <ResponsiveContainer>
              <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 24 }} barGap={2} barCategoryGap="22%">
                <CartesianGrid stroke={VIZ.grid} vertical={false} />
                <XAxis dataKey="label" {...axisProps} interval={0} angle={-15} textAnchor="end" height={44} />
                <YAxis {...axisProps} domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} width={40} />
                <Tooltip cursor={{ fill: 'rgba(255,255,255,0.03)' }} content={<ChartTooltip format={(v) => pct(v, 0)} />} />
                {ALGOS.map((a) => <Bar key={a} dataKey={a} name={a.toUpperCase()} fill={TECHNIQUE_COLOR[a]} radius={[4, 4, 0, 0]} />)}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      ) : (
        <Unavailable what="Robustness results" />
      )}
    </section>
  )
}

export function Research({ overview }: { overview: Overview | null }) {
  const util = overview?.models['steganalysis-cnn']?.by_utilisation
  const exp = overview?.latest_experiment
  const bins = util ? Array.from(new Set(util.map((r) => r.bin))) : []
  const data = bins.map((bin) => ({ bin, ...Object.fromEntries((util ?? []).filter((r) => r.bin === bin).map((r) => [r.technique, r.detection_rate])) }))
  return (
    <section className="border-y border-line bg-surface" id="research">
      <div className="mx-auto max-w-7xl px-4 py-24 md:px-10">
        <SectionHead index="09" kicker="Research" title={<>Capacity · quality · robustness · <span className="font-serif font-normal normal-case italic">detectability</span></>}>
          {exp ? exp.answer : 'Run an experiment to answer the research question with measured data.'}
        </SectionHead>
        <div className="grid gap-10 lg:grid-cols-2">
          <div>
            <p className="label-mono mb-3">AI detection rate vs payload utilisation (test split)</p>
            {util ? (
              <>
                <Legend items={ALGOS.map((a) => ({ label: a.toUpperCase(), color: TECHNIQUE_COLOR[a] }))} />
                <div className="mt-3 h-64">
                  <ResponsiveContainer>
                    <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={2}>
                      <CartesianGrid stroke={VIZ.grid} vertical={false} />
                      <XAxis dataKey="bin" {...axisProps} />
                      <YAxis {...axisProps} domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} width={40} />
                      <Tooltip cursor={{ fill: 'rgba(255,255,255,0.03)' }} content={<ChartTooltip format={(v) => pct(v, 1)} />} />
                      {ALGOS.map((a) => <Bar key={a} dataKey={a} name={a.toUpperCase()} fill={TECHNIQUE_COLOR[a]} radius={[4, 4, 0, 0]} />)}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </>
            ) : (
              <Unavailable what="Detection-vs-payload curve" />
            )}
          </div>
          <div>
            <p className="label-mono mb-3">Balance score (equal weights)</p>
            {exp ? (
              <ul className="flex flex-col gap-4">
                {exp.ranking.map((a, i) => (
                  <li key={a} className="grid grid-cols-[32px_88px_minmax(0,1fr)_56px] items-center gap-3">
                    <span className="font-mono text-xs text-ink-4">#{i + 1}</span>
                    <TechniqueChip technique={a} />
                    <div className="h-2 overflow-hidden rounded-[1px] bg-raised">
                      <motion.div className="h-full rounded-r-[3px]" style={{ background: TECHNIQUE_COLOR[a] }} initial={{ width: 0 }} whileInView={{ width: `${exp.balance_score[a] * 100}%` }} viewport={{ once: true }} transition={{ duration: 1, delay: i * 0.15 }} />
                    </div>
                    <span className="text-right font-mono text-sm tabular">{num(exp.balance_score[a], 2)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <Unavailable what="The ranking" />
            )}
            {overview?.dataset && (
              <p className="mt-8 font-mono text-[11px] leading-relaxed text-ink-3">
                Dataset: {Object.values(overview.dataset.sources).reduce((a, b) => a + b, 0).toLocaleString()} source photos (DIV2K + COCO) → {Object.values(overview.dataset.images).reduce((a, b) => a + b, 0).toLocaleString()} tiles · split by source 70/15/15 · leakage check {overview.dataset.leakage_check.passed ? 'passed' : 'failed'}.
              </p>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ security architecture */

const ARCH: Record<string, { title: string; body: string }> = {
  user: { title: 'User', body: 'Browser SPA (React). Access token kept in memory only; refresh token in an httpOnly, SameSite=Strict cookie scoped to /api/auth.' },
  auth: { title: 'Authentication', body: 'Argon2id password hashing, generic login errors, account lockout, rotating refresh tokens with reuse detection, token-version revocation.' },
  gateway: { title: 'API gateway', body: 'FastAPI with sliding-window rate limits, request-size guard, strict CORS, security headers (CSP, nosniff, frame-deny) and per-route RBAC permission checks.' },
  crypto: { title: 'Cryptography', body: 'AES-256-GCM (OpenSSL via cryptography), Argon2id KDF, SHA-256 integrity at two layers. Keys and plaintext are never persisted or logged.' },
  stego: { title: 'Steganography', body: 'LSB, block-DCT QIM and Haar-DWT QIM over a Reed-Solomon framed bitstream, with automatic format detection on extraction.' },
  analysis: { title: 'Steganalysis', body: 'StegoNet CNN (GPU when available) + Random Forest + Mahalanobis anomaly model; Grad-CAM explanations; transparent risk scoring.' },
  attack: { title: 'Attack lab', body: 'JPEG, noise, blur, median, resize, crop, brightness, contrast and rotation — each re-measured for detection, extraction, BER and quality.' },
  report: { title: 'Reporting', body: 'PDF reports assembled from stored records with SHA-256 for chain-of-custody; all security events written to an append-only audit log.' },
  db: { title: 'Database', body: 'PostgreSQL via SQLAlchemy + Alembic migrations. Users, sessions, analyses, operations, experiments, model versions, reports, audit logs. Temporary artefacts expire by policy.' },
}

export function Architecture() {
  const [node, setNode] = useState('gateway')
  const box = (key: string, x: number, y: number, w: number, label: string) => (
    <g key={key} role="button" tabIndex={0} aria-label={label} onClick={() => setNode(key)} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setNode(key)} className="cursor-pointer outline-none">
      <rect x={x} y={y} width={w} height={44} rx={2} fill={node === key ? 'color-mix(in oklab, var(--color-accent) 14%, var(--color-surface))' : 'var(--color-surface)'} stroke={node === key ? 'var(--color-accent)' : 'var(--color-line-strong)'} />
      <text x={x + w / 2} y={y + 27} textAnchor="middle" fill={node === key ? 'var(--color-ink)' : 'var(--color-ink-2)'} style={{ font: '500 12px var(--font-mono)', letterSpacing: '0.1em' }}>{label.toUpperCase()}</text>
    </g>
  )
  const subs: [string, string][] = [['crypto', 'Crypto'], ['stego', 'Stego'], ['analysis', 'Analysis'], ['attack', 'Attack lab'], ['report', 'Reporting']]
  return (
    <section className="mx-auto max-w-7xl px-4 py-24 md:px-10" id="architecture">
      <SectionHead index="10" kicker="Security architecture" title="Defence in depth, end to end">Select a component to see how it is secured.</SectionHead>
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="overflow-x-auto">
          <svg viewBox="0 0 640 430" className="w-full min-w-[520px]">
            <g stroke="var(--color-line-strong)" strokeWidth="1" fill="none">
              <path d="M320 54 V80" /><path d="M320 124 V150" /><path d="M320 194 V214 H64 V240" />
              {subs.map((_, i) => <path key={i} d={`M${64 + i * 128} 214 V240`} />)}
              <path d="M64 284 V320 H576 V284" /><path d="M320 320 V356" />
            </g>
            <motion.circle r="3" fill="var(--color-accent)" animate={{ cy: [30, 380], opacity: [0, 1, 1, 0] }} transition={{ duration: 3.2, repeat: Infinity, ease: 'linear' }} cx={320} />
            {box('user', 240, 10, 160, 'User')}
            {box('auth', 240, 80, 160, 'Authentication')}
            {box('gateway', 240, 150, 160, 'API gateway')}
            {subs.map(([k, label], i) => box(k, 8 + i * 128, 240, 112, label))}
            {box('db', 240, 356, 160, 'Database')}
          </svg>
        </div>
        <AnimatePresence mode="wait">
          <motion.div key={node} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} className="bracket self-start rounded-xs border border-line bg-surface p-6">
            <p className="label-mono mb-2 flex items-center gap-2"><Eye className="size-3.5 text-accent" aria-hidden /> component</p>
            <p className="font-display text-3xl font-bold uppercase">{ARCH[node].title}</p>
            <p className="mt-3 text-sm leading-relaxed text-ink-2">{ARCH[node].body}</p>
          </motion.div>
        </AnimatePresence>
      </div>
    </section>
  )
}

export function FinalCta({ authed }: { authed: boolean }) {
  return (
    <section className="relative overflow-hidden border-t border-line">
      <div className="grid-bg absolute inset-0 opacity-50" aria-hidden />
      <div className="relative mx-auto flex max-w-7xl flex-col items-start gap-8 px-4 py-28 md:px-10">
        <p className="label-mono text-accent">11 / Enter the lab</p>
        <h2 className="max-w-4xl font-display text-5xl leading-[0.92] font-extrabold uppercase md:text-8xl">Hide it properly. <span className="text-ink-3">Find what others hid.</span></h2>
        <Link to={authed ? '/dashboard' : '/register'} className={buttonClasses('primary', 'lg')}>
          {authed ? 'Launch security lab' : 'Create an account'} <ArrowRight className="size-4" aria-hidden />
        </Link>
      </div>
    </section>
  )
}
