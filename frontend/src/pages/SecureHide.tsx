import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, CheckCircle2, Download, Eye, EyeOff, KeyRound, LockKeyhole, RefreshCw, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ArtifactImage } from '../components/ArtifactImage'
import { CompareSlider } from '../components/CompareSlider'
import { Dropzone } from '../components/Dropzone'
import { TerminalLog } from '../components/TerminalLog'
import { Button, ErrorNotice, Field, Hash, Input, KeyValue, Meter, PageHeader, Panel, Segmented, Skeleton, StatusBadge, TECHNIQUE_COLOR, Textarea, cx } from '../components/ui'
import { ApiError, api } from '../lib/api'
import { bytes, int, ms, num, pct } from '../lib/format'
import { downloadArtifact, useArtifactUrl, useOperation } from '../lib/hooks'
import type { Algorithm, CapacityInfo, EmbedResult } from '../lib/types'

const ENVELOPE_OVERHEAD = 39 + 16 + 4 + 32 // header + GCM tag + plaintext header + inner SHA-256 (see crypto.py)

const ALGORITHM_COPY: Record<Algorithm, { title: string; blurb: string; traits: string[] }> = {
  lsb: { title: 'LSB', blurb: 'Replaces the least-significant bit of every R, G, B value. Maximum capacity, invisible, but destroyed by any lossy processing.', traits: ['3 bpp', 'Spatial', 'Fragile'] },
  dct: { title: 'DCT', blurb: 'QIM on five mid-frequency coefficients of each 8×8 luma block — the JPEG domain. Survives moderate JPEG re-compression.', traits: ['5/64 bpp', 'Frequency', 'RS-ECC'] },
  dwt: { title: 'DWT', blurb: 'QIM on level-3 Haar wavelet detail bands of luma. Lowest capacity, highest robustness to compression and noise.', traits: ['2/64 bpp', 'Wavelet', 'RS-ECC'] },
}

function passphraseScore(p: string): { score: number; label: string } {
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(p)).length
  const score = Math.min(1, (Math.min(p.length, 24) / 24) * 0.7 + (classes / 4) * 0.3)
  return { score, label: p.length < 8 ? 'too short' : score < 0.5 ? 'weak' : score < 0.75 ? 'fair' : 'strong' }
}

function StepLabel({ n, title, done }: { n: string; title: string; done: boolean }) {
  return (
    <div className="mb-3 flex items-center gap-3">
      <span className={cx('grid size-6 place-items-center rounded-full border font-mono text-[10px]', done ? 'border-ok bg-ok/15 text-ok-ink' : 'border-line-strong text-ink-3')}>
        {done ? <CheckCircle2 className="size-3.5" aria-hidden /> : n}
      </span>
      <h2 className="font-mono text-[11px] tracking-[0.14em] text-ink-2 uppercase">{title}</h2>
    </div>
  )
}

export default function SecureHide() {
  const [cover, setCover] = useState<File | null>(null)
  const [capacity, setCapacity] = useState<CapacityInfo[] | null>(null)
  const [capacityError, setCapacityError] = useState<ApiError | null>(null)
  const [payloadType, setPayloadType] = useState<'text' | 'file'>('text')
  const [message, setMessage] = useState('')
  const [payloadFile, setPayloadFile] = useState<File | null>(null)
  const [algorithm, setAlgorithm] = useState<Algorithm>('lsb')
  const [keyMode, setKeyMode] = useState<'passphrase' | 'generate'>('passphrase')
  const [passphrase, setPassphrase] = useState('')
  const [showPass, setShowPass] = useState(false)
  const op = useOperation<EmbedResult>('/api/steganography/embed')

  useEffect(() => {
    setCapacity(null)
    setCapacityError(null)
    if (!cover) return
    const form = new FormData()
    form.append('image', cover)
    let cancelled = false
    api<{ algorithms: CapacityInfo[] }>('/api/steganography/capacity', { method: 'POST', body: form })
      .then((res) => !cancelled && setCapacity(res.algorithms))
      .catch((err: ApiError) => !cancelled && setCapacityError(err))
    return () => {
      cancelled = true
    }
  }, [cover])

  const payloadBytes = payloadType === 'text' ? new TextEncoder().encode(message).length : (payloadFile?.size ?? 0)
  const selectedCap = capacity?.find((c) => c.algorithm === algorithm) ?? null
  const fits = selectedCap ? payloadBytes <= selectedCap.max_payload_bytes : true
  const strength = passphraseScore(passphrase)
  const keyReady = keyMode === 'generate' || passphrase.length >= 8
  const canRun = Boolean(cover && payloadBytes > 0 && keyReady && op.status !== 'running')

  const submit = () => {
    if (!cover) return
    const form = new FormData()
    form.append('image', cover)
    form.append('algorithm', algorithm)
    form.append('payload_type', payloadType)
    if (payloadType === 'text') form.append('message', message)
    else if (payloadFile) form.append('payload_file', payloadFile)
    form.append('key_mode', keyMode)
    if (keyMode === 'passphrase') form.append('passphrase', passphrase)
    op.run(form)
  }

  return (
    <div>
      <PageHeader
        index="02"
        kicker="Defence · secure communication"
        title="Secure Hide"
        description="Encrypt a message or file with AES-256-GCM, bind it to a SHA-256 integrity digest, and embed the ciphertext into a cover image using LSB, DCT or DWT steganography."
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-6">
          <Panel brackets>
            <StepLabel n="01" title="Cover image" done={Boolean(cover)} />
            <Dropzone file={cover} onFile={setCover} label="Drop a cover image" />
            {capacityError && <div className="mt-3"><ErrorNotice error={capacityError} title="Image rejected" /></div>}
          </Panel>

          <Panel>
            <StepLabel n="02" title="Secret payload" done={payloadBytes > 0} />
            <div className="mb-3 flex items-center justify-between gap-3">
              <Segmented label="Payload type" value={payloadType} onChange={setPayloadType} options={[{ value: 'text', label: 'Message' }, { value: 'file', label: 'File' }]} size="sm" />
              <span className="font-mono text-xs text-ink-3 tabular">{bytes(payloadBytes)}</span>
            </div>
            {payloadType === 'text' ? (
              <Textarea aria-label="Secret message" placeholder="Type the secret message…" value={message} onChange={(e) => setMessage(e.target.value)} spellCheck={false} />
            ) : (
              <Dropzone file={payloadFile} onFile={setPayloadFile} accept="any" maxBytes={2 * 1024 * 1024} label="Drop a file to conceal (≤ 2 MB)" compact />
            )}
            <p className="mt-2 text-xs text-ink-3">The plaintext never touches disk or the database — only its size and SHA-256 are recorded.</p>
          </Panel>

          <Panel>
            <StepLabel n="03" title="Embedding algorithm" done />
            <div className="grid gap-3 sm:grid-cols-3" role="radiogroup" aria-label="Embedding algorithm">
              {(['lsb', 'dct', 'dwt'] as Algorithm[]).map((a) => {
                const cap = capacity?.find((c) => c.algorithm === a)
                const active = a === algorithm
                const overflow = cap ? payloadBytes > cap.max_payload_bytes : false
                return (
                  <button
                    key={a}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setAlgorithm(a)}
                    className={cx('relative flex flex-col gap-2 rounded-xs border p-3 text-left transition-colors', active ? 'border-accent bg-accent/5' : 'border-line hover:border-line-strong')}
                  >
                    <span className="flex items-center justify-between">
                      <span className="flex items-center gap-2 font-display text-2xl font-bold tracking-wider">
                        <span className="inline-block size-2 rounded-[1px]" style={{ background: TECHNIQUE_COLOR[a] }} aria-hidden />
                        {ALGORITHM_COPY[a].title}
                      </span>
                      {active && <CheckCircle2 className="size-4 text-accent" aria-hidden />}
                    </span>
                    <span className="text-xs leading-relaxed text-ink-2">{ALGORITHM_COPY[a].blurb}</span>
                    <span className="mt-auto flex flex-wrap gap-1">
                      {ALGORITHM_COPY[a].traits.map((t) => (
                        <span key={t} className="rounded-[1px] border border-line px-1.5 py-0.5 font-mono text-[10px] text-ink-3">
                          {t}
                        </span>
                      ))}
                    </span>
                    <span className="font-mono text-[11px] text-ink-3">
                      {cap ? (
                        <span className={overflow ? 'text-critical-ink' : 'text-ink-2'}>capacity {bytes(cap.max_payload_bytes)}</span>
                      ) : cover ? (
                        <Skeleton className="h-3 w-24" />
                      ) : (
                        'capacity: load a cover'
                      )}
                    </span>
                  </button>
                )
              })}
            </div>
            {selectedCap && (
              <div className="mt-4 flex flex-col gap-1.5">
                <div className="flex justify-between font-mono text-[11px] text-ink-3">
                  <span>Estimated frame fill (payload + {ENVELOPE_OVERHEAD} B envelope, before compression)</span>
                  <span className={fits ? 'text-ink-2' : 'text-critical-ink'}>{pct(Math.min(1, (payloadBytes + ENVELOPE_OVERHEAD) / Math.max(1, selectedCap.max_envelope_bytes)))}</span>
                </div>
                <Meter value={(payloadBytes + ENVELOPE_OVERHEAD) / Math.max(1, selectedCap.max_envelope_bytes)} color={fits ? TECHNIQUE_COLOR[algorithm] : 'var(--color-critical)'} label="Estimated capacity utilisation" />
                {!fits && (
                  <p className="flex items-center gap-1.5 text-xs text-critical-ink">
                    <AlertTriangle className="size-3.5" aria-hidden /> Payload exceeds {algorithm.toUpperCase()} capacity for this image ({bytes(selectedCap.max_payload_bytes)}). Compressible text may still fit; the server checks exactly.
                  </p>
                )}
              </div>
            )}
          </Panel>

          <Panel>
            <StepLabel n="04" title="Encryption key" done={keyReady} />
            <Segmented
              label="Key mode"
              value={keyMode}
              onChange={setKeyMode}
              options={[
                { value: 'passphrase', label: 'Passphrase · Argon2id' },
                { value: 'generate', label: 'Generate 256-bit key' },
              ]}
              size="sm"
            />
            <div className="mt-4">
              {keyMode === 'passphrase' ? (
                <Field label="Passphrase" htmlFor="pass" hint="Stretched with Argon2id (64 MiB, t=3, p=4) and a fresh 128-bit salt.">
                  <div className="relative">
                    <Input id="pass" type={showPass ? 'text' : 'password'} value={passphrase} onChange={(e) => setPassphrase(e.target.value)} autoComplete="new-password" className="pr-10" />
                    <button type="button" onClick={() => setShowPass((v) => !v)} className="absolute top-1/2 right-2 -translate-y-1/2 p-1 text-ink-3 hover:text-ink" aria-label={showPass ? 'Hide passphrase' : 'Show passphrase'}>
                      {showPass ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                    </button>
                  </div>
                  {passphrase && (
                    <div className="mt-2 flex items-center gap-3">
                      <Meter value={strength.score} label="Passphrase strength" color={strength.score < 0.5 ? 'var(--color-serious)' : strength.score < 0.75 ? 'var(--color-warn)' : 'var(--color-ok)'} />
                      <span className="w-20 shrink-0 font-mono text-[11px] text-ink-2 uppercase">{strength.label}</span>
                    </div>
                  )}
                </Field>
              ) : (
                <p className="text-sm text-ink-2">
                  The server draws 32 bytes from the OS CSPRNG. The key is shown <strong className="text-ink">once</strong> after embedding and is never stored or logged.
                </p>
              )}
            </div>
          </Panel>

          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" size="lg" icon={LockKeyhole} onClick={submit} disabled={!canRun} loading={op.status === 'running'}>
              Encrypt &amp; embed
            </Button>
            {op.status !== 'idle' && (
              <Button variant="ghost" icon={RefreshCw} onClick={op.reset}>
                Reset
              </Button>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-6 xl:sticky xl:top-20 xl:self-start">
          <TerminalLog events={op.events} status={op.status} upload={op.upload} title="secure-hide.log" idleText="Configure the four steps, then run. Every line here is emitted by the backend as it happens." />
          <ErrorNotice error={op.error} title="Embedding failed" />
          {op.result && <ResultSummary result={op.result} />}
        </div>
      </div>

      <AnimatePresence>{op.result && <ResultDetail key={op.result.operation_id} result={op.result} />}</AnimatePresence>
    </div>
  )
}

function ResultSummary({ result }: { result: EmbedResult }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <Panel title="Result" index="✓" actions={<StatusBadge tone="ok">Embedded · verified</StatusBadge>}>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="label-mono">PSNR</p>
            <p className="font-display text-3xl font-bold tabular">{result.quality.psnr === null ? '∞' : num(result.quality.psnr, 2)}<span className="ml-1 text-sm text-ink-3">dB</span></p>
          </div>
          <div>
            <p className="label-mono">SSIM</p>
            <p className="font-display text-3xl font-bold tabular">{num(result.quality.ssim, 4)}</p>
          </div>
          <div>
            <p className="label-mono">Utilisation</p>
            <p className="font-display text-3xl font-bold tabular">{pct(result.utilization)}</p>
          </div>
        </div>
        {result.generated_key && <GeneratedKey value={result.generated_key} />}
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" icon={Download} onClick={() => downloadArtifact(result.artifacts.stego, `stego-${result.algorithm}-${result.operation_id.slice(0, 8)}.png`)}>
            Download stego PNG
          </Button>
        </div>
      </Panel>
    </motion.div>
  )
}

function GeneratedKey({ value }: { value: string }) {
  return (
    <div className="mt-4 rounded-xs border border-warn/50 bg-warn/8 p-3">
      <p className="flex items-center gap-2 font-mono text-[11px] tracking-wider text-warn uppercase">
        <KeyRound className="size-3.5" aria-hidden /> Generated key — shown once
      </p>
      <div className="mt-2">
        <Hash value={value} truncate={false} />
      </div>
      <p className="mt-1 text-xs text-ink-2">Store it in a password manager now. Without it the payload cannot be decrypted; StegoLab keeps no copy.</p>
    </div>
  )
}

function ResultDetail({ result }: { result: EmbedResult }) {
  const before = useArtifactUrl(result.artifacts.cover_preview)
  const after = useArtifactUrl(result.artifacts.stego_preview)
  const [diffMode, setDiffMode] = useState<'difference' | 'difference_amplified'>('difference_amplified')
  const timings = useMemo(() => Object.entries(result.timings_ms).filter(([k]) => k !== 'total'), [result])

  return (
    <motion.section initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <Panel title="Before / after inspection" index="A" actions={<span className="font-mono text-[11px] text-ink-3">{result.cover.width}×{result.cover.height}</span>}>
        {before.url && after.url ? <CompareSlider before={before.url} after={after.url} beforeLabel="Cover" afterLabel="Stego" /> : <Skeleton className="aspect-[4/3] w-full" />}
        <div className="mt-5">
          <div className="mb-2 flex items-center justify-between">
            <p className="label-mono">Pixel difference</p>
            <Segmented label="Difference view" size="sm" value={diffMode} onChange={setDiffMode} options={[{ value: 'difference', label: '|Δ| raw' }, { value: 'difference_amplified', label: '|Δ| × 32' }]} />
          </div>
          <ArtifactImage id={result.artifacts[diffMode]} alt="Difference between cover and stego image" className="checker aspect-[4/3] w-full rounded-xs border border-line" />
          <p className="mt-2 text-xs text-ink-3">
            {diffMode === 'difference' ? 'Absolute per-pixel change (max over channels). Typically invisible: values of 0–3 grey levels.' : 'Same difference amplified ×32 to reveal where the embedding touched the image.'}
          </p>
        </div>
      </Panel>

      <div className="flex flex-col gap-6">
        <Panel title="Image quality" index="B">
          <KeyValue
            rows={[
              ['MSE', num(result.quality.mse, 4)],
              ['PSNR', result.quality.psnr === null ? '∞ (identical)' : `${num(result.quality.psnr, 3)} dB`],
              ['SSIM', num(result.quality.ssim, 5)],
              ['Payload', `${bytes(result.payload.size)} ${result.payload.kind}`],
              ['Envelope (ciphertext)', bytes(result.encryption.envelope_bytes)],
              ['Capacity (payload)', bytes(result.capacity.max_payload_bytes)],
              ['Frame bits / slots', `${int(result.frame_bits)} / ${int(result.capacity.slots)}`],
              ['Utilisation', pct(result.utilization, 2)],
              ...(result.qim ? ([['QIM correction', `${result.qim.iterations} round(s) · ${result.qim.residual_errors} residual`]] as [string, string][]) : []),
            ]}
          />
        </Panel>
        <Panel title="Cryptography" index="C" actions={<Sparkles className="size-4 text-ink-4" aria-hidden />}>
          <KeyValue
            rows={[
              ['Cipher', result.encryption.cipher],
              ['Key derivation', result.encryption.kdf_params ? `Argon2id · ${result.encryption.kdf_params.memory_kib / 1024} MiB · t=${result.encryption.kdf_params.time_cost} · p=${result.encryption.kdf_params.parallelism}` : 'Raw 256-bit key'],
              ['Compression', result.encryption.compressed ? 'zlib (smaller)' : 'none (incompressible)'],
              ['ECC', result.capacity.ecc_parity ? `Reed-Solomon, ${result.capacity.ecc_parity} parity / 255 B` : 'none (LSB)'],
            ]}
          />
          <div className="mt-4 flex flex-col gap-2 border-t border-line pt-4">
            <Hash label="Nonce" value={result.encryption.nonce_hex} />
            <Hash label="SHA-256 envelope" value={result.encryption.envelope_sha256} />
            <Hash label="SHA-256 plaintext" value={result.encryption.content_sha256} />
            <Hash label="SHA-256 cover" value={result.cover.sha256} />
            <Hash label="SHA-256 stego" value={result.stego.sha256} />
          </div>
        </Panel>
        <Panel title="Timing" index="D">
          <KeyValue rows={timings.map(([k, v]) => [k.replace('_', ' '), ms(v)] as [string, string])} />
          <p className="mt-3 font-mono text-[11px] text-ink-3">Total {ms(result.timings_ms.total)} — Argon2id dominates by design (brute-force resistance).</p>
        </Panel>
      </div>
    </motion.section>
  )
}
