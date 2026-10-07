import { motion } from 'framer-motion'
import { ArrowRight, Check, FlaskConical, Play, Swords, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ChartTooltip, VIZ, axisProps } from '../components/charts'
import { CompareSlider } from '../components/CompareSlider'
import { Dropzone } from '../components/Dropzone'
import { TerminalLog } from '../components/TerminalLog'
import { Button, ErrorNotice, Field, Input, IntegrityBadge, PageHeader, Panel, Segmented, Skeleton, StatusBadge, TechniqueChip, cx } from '../components/ui'
import { num, pct } from '../lib/format'
import { useApi, useArtifactUrl, useOperation } from '../lib/hooks'
import type { AttackBaseline, AttackBatchResult, AttackRow, AttackSingleResult, AttackSpec } from '../lib/types'

const STEP: Record<string, number> = { quality: 1, kernel: 2, delta: 1, restore: 1, sigma: 0.1, amount: 0.0005, scale: 0.05, ratio: 0.01, factor: 0.05, degrees: 0.5 }

function paramLabel(name: string, value: number): string {
  if (name === 'restore') return value >= 0.5 ? 'restore size: yes' : 'restore size: no'
  if (name === 'amount') return `${(value * 100).toFixed(2)}% pixels`
  return `${name} ${Number.isInteger(value) ? value : value.toFixed(2)}`
}

function StateColumn({ title, detection, technique, extraction, ber, quality }: { title: string; detection: number; technique: string; extraction: AttackBaseline['extraction']; ber?: number | null; quality?: AttackRow['quality'] }) {
  return (
    <div className="flex flex-col gap-3">
      <p className="font-display text-2xl font-bold tracking-wider uppercase">{title}</p>
      <div>
        <p className="label-mono">Detection P(stego)</p>
        <p className="font-display text-4xl font-bold tabular">{pct(detection, 1)}</p>
        <div className="mt-1"><TechniqueChip technique={technique} /></div>
      </div>
      <div className="flex flex-col gap-1.5">
        <span className="flex items-center justify-between gap-2 text-sm text-ink-2">
          Extraction
          {extraction.success ? <StatusBadge tone="ok" icon={Check}>Success</StatusBadge> : <StatusBadge tone="critical" icon={X}>Failed</StatusBadge>}
        </span>
        <span className="flex items-center justify-between gap-2 text-sm text-ink-2">
          Integrity <IntegrityBadge status={extraction.integrity} />
        </span>
        <span className="flex items-center justify-between gap-2 text-sm text-ink-2">
          Decryption
          {extraction.decryption === 'success' ? <StatusBadge tone="ok" icon={Check}>Success</StatusBadge> : extraction.decryption === 'failed' ? <StatusBadge tone="critical">Failed</StatusBadge> : <StatusBadge tone="neutral" icon={null}>n/a</StatusBadge>}
        </span>
        {ber !== undefined && (
          <span className="flex items-center justify-between gap-2 text-sm text-ink-2">
            Bit error rate <span className="font-mono text-ink tabular">{ber === null ? 'n/a (geometry)' : pct(ber, 2)}</span>
          </span>
        )}
        {extraction.ecc_corrected > 0 && <span className="font-mono text-[11px] text-ink-3">{extraction.ecc_corrected} symbols corrected by Reed-Solomon</span>}
      </div>
      {quality && (
        <div className="grid grid-cols-3 gap-2 border-t border-line pt-3">
          <div><p className="label-mono">PSNR</p><p className="font-mono text-sm tabular">{quality.psnr === null ? '∞' : `${num(quality.psnr, 2)} dB`}</p></div>
          <div><p className="label-mono">SSIM</p><p className="font-mono text-sm tabular">{num(quality.ssim, 4)}</p></div>
          <div><p className="label-mono">MSE</p><p className="font-mono text-sm tabular">{num(quality.mse, 2)}</p></div>
          <p className="col-span-3 font-mono text-[10px] text-ink-4">vs {quality.reference}</p>
        </div>
      )}
    </div>
  )
}

function SingleResult({ result }: { result: AttackSingleResult }) {
  const before = useArtifactUrl(result.artifacts.before_preview)
  const after = useArtifactUrl(result.artifacts.after_preview)
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <Panel title={`${result.after.label} · ${Object.entries(result.after.params).map(([k, v]) => paramLabel(k, v)).join(' · ')}`} index="R">
        <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-4">
          <StateColumn title="Before" detection={result.before.detection_probability} technique={result.before.predicted_technique} extraction={result.before.extraction} />
          <ArrowRight className="mt-10 size-5 text-ink-4" aria-hidden />
          <StateColumn title="After" detection={result.after.detection_probability} technique={result.after.predicted_technique} extraction={result.after.extraction} ber={result.after.bit_error_rate} quality={result.after.quality} />
        </div>
      </Panel>
      <Panel title="Visual comparison" index="V">
        {before.url && after.url ? <CompareSlider before={before.url} after={after.url} beforeLabel="Before" afterLabel="After attack" /> : <Skeleton className="aspect-[4/3] w-full" />}
      </Panel>
    </motion.div>
  )
}

function BatchResult({ result }: { result: AttackBatchResult }) {
  const chart = result.rows.map((r) => ({
    name: `${r.attack.replace('_', ' ')} ${Object.entries(r.params).filter(([k]) => k !== 'restore').map(([, v]) => v).join('/')}`,
    detection: r.detection_probability,
  }))
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 flex flex-col gap-6">
      <Panel brackets bodyClassName="grid grid-cols-2 gap-6 md:grid-cols-4">
        <div><p className="label-mono">Baseline</p><p className="mt-1 text-sm">{result.before.extraction.algorithm ? <TechniqueChip technique={result.before.extraction.algorithm} /> : 'no frame'} · P(stego) {pct(result.before.detection_probability)}</p></div>
        <div><p className="label-mono">Payload survived</p><p className="font-display text-3xl font-bold tabular">{pct(result.summary.extraction_survival_rate, 0)}</p></div>
        <div><p className="label-mono">Detector still flags</p><p className="font-display text-3xl font-bold tabular">{pct(result.summary.detection_rate, 0)}</p></div>
        <div><p className="label-mono">Mean PSNR after attack</p><p className="font-display text-3xl font-bold tabular">{num(result.summary.mean_psnr, 1)}<span className="text-sm text-ink-3"> dB</span></p></div>
      </Panel>
      <Panel title="Detection probability after each attack" index="C1" actions={<span className="font-mono text-[11px] text-ink-3">dashed = before ({pct(result.before.detection_probability, 0)})</span>}>
        <div className="h-72">
          <ResponsiveContainer>
            <BarChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 48 }}>
              <CartesianGrid stroke={VIZ.grid} vertical={false} />
              <XAxis dataKey="name" {...axisProps} angle={-35} textAnchor="end" interval={0} height={60} />
              <YAxis {...axisProps} domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} width={40} />
              <Tooltip cursor={{ fill: 'rgba(255,255,255,0.03)' }} content={<ChartTooltip format={(v) => pct(v, 1)} />} />
              <Bar dataKey="detection" name="P(stego)" fill={VIZ.measure} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>
      <Panel title="Robustness table" index="C2">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="text-left">
                {['Attack', 'Parameters', 'Detection', 'Extraction', 'Integrity', 'BER', 'PSNR', 'SSIM'].map((h, i) => (
                  <th key={h} className={cx('label-mono px-2 pb-2 font-normal first:pl-0', i >= 2 && i !== 3 && i !== 4 && 'text-right')}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((r, i) => (
                <tr key={i} className="border-t border-line">
                  <td className="py-2 pr-2 text-ink">{r.label}</td>
                  <td className="px-2 py-2 font-mono text-xs text-ink-2">{Object.entries(r.params).map(([k, v]) => paramLabel(k, v)).join(', ')}</td>
                  <td className="px-2 py-2 text-right font-mono tabular">{pct(r.detection_probability, 1)}</td>
                  <td className="px-2 py-2">{r.extraction.success ? <StatusBadge tone="ok" icon={Check}>Success</StatusBadge> : <StatusBadge tone="critical" icon={X}>Failed</StatusBadge>}</td>
                  <td className="px-2 py-2"><IntegrityBadge status={r.extraction.integrity} /></td>
                  <td className="px-2 py-2 text-right font-mono tabular">{r.bit_error_rate === null ? '—' : pct(r.bit_error_rate, 2)}</td>
                  <td className="px-2 py-2 text-right font-mono tabular">{r.quality.psnr === null ? '∞' : num(r.quality.psnr, 2)}</td>
                  <td className="px-2 py-2 text-right font-mono tabular">{num(r.quality.ssim, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </motion.div>
  )
}

export default function AttackLab() {
  const catalogue = useApi<{ attacks: AttackSpec[] }>('/api/attacks/catalogue')
  const [file, setFile] = useState<File | null>(null)
  const [secret, setSecret] = useState('')
  const [mode, setMode] = useState<'single' | 'batch'>('single')
  const [attack, setAttack] = useState('jpeg')
  const [params, setParams] = useState<Record<string, number>>({})
  const [autoRun, setAutoRun] = useState(false)
  const single = useOperation<AttackSingleResult>('/api/attacks/run')
  const batch = useOperation<AttackBatchResult>('/api/attacks/batch')
  const spec = useMemo(() => catalogue.data?.attacks.find((a) => a.key === attack) ?? null, [catalogue.data, attack])

  useEffect(() => {
    if (spec) setParams(Object.fromEntries(Object.entries(spec.params).map(([k, v]) => [k, v.default])))
  }, [spec])

  const runSingle = () => {
    if (!file) return
    const form = new FormData()
    form.append('image', file)
    form.append('attack', attack)
    form.append('params', JSON.stringify(params))
    if (secret) form.append('secret', secret)
    single.run(form)
  }
  const runBatch = () => {
    if (!file) return
    const form = new FormData()
    form.append('image', file)
    if (secret) form.append('secret', secret)
    batch.run(form)
  }

  // Optional live mode: re-run (debounced) when a control changes. Each run is a real backend computation.
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (!autoRun || mode !== 'single' || !file || !spec) return
    if (debounce.current) clearTimeout(debounce.current)
    debounce.current = setTimeout(runSingle, 650)
    return () => {
      if (debounce.current) clearTimeout(debounce.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, attack, autoRun])

  const op = mode === 'single' ? single : batch
  return (
    <div>
      <PageHeader
        index="06"
        kicker="Robustness · adversarial processing"
        title="Attack Lab"
        description="Apply controlled transformations to a stego image and re-measure everything live: the AI detector, frame extraction, SHA-256 integrity, decryption, bit-error rate and image quality."
        actions={<Segmented label="Mode" value={mode} onChange={setMode} options={[{ value: 'single', label: 'Single attack' }, { value: 'batch', label: 'Robustness batch' }]} />}
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="flex flex-col gap-6">
          <Panel title="Target" index="01" brackets>
            <Dropzone file={file} onFile={setFile} label="Drop a stego image produced by Secure Hide" compact={Boolean(file)} />
            <div className="mt-4">
              <Field label="Key (optional)" htmlFor="atk-secret" hint="Supply it to also test decryption after each attack.">
                <Input id="atk-secret" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off" className="font-mono" />
              </Field>
            </div>
          </Panel>

          {mode === 'single' ? (
            <Panel title="Attack controls" index="02">
              {catalogue.loading ? (
                <Skeleton className="h-40" />
              ) : catalogue.data ? (
                <div className="flex flex-col gap-5">
                  <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Attack type">
                    {catalogue.data.attacks.map((a) => (
                      <button key={a.key} type="button" role="radio" aria-checked={a.key === attack} onClick={() => setAttack(a.key)} className={cx('rounded-xs border px-2.5 py-1.5 text-xs transition-colors', a.key === attack ? 'border-accent bg-accent/10 text-ink' : 'border-line text-ink-2 hover:border-line-strong')}>
                        {a.label}
                      </button>
                    ))}
                  </div>
                  {spec && (
                    <>
                      <p className="text-sm text-ink-2">{spec.description}</p>
                      {Object.entries(spec.params).map(([name, p]) => (
                        <div key={name} className="flex flex-col gap-1.5">
                          <div className="flex justify-between">
                            <label htmlFor={`p-${name}`} className="label-mono">{name}</label>
                            <span className="font-mono text-xs text-ink tabular">{paramLabel(name, params[name] ?? p.default)}</span>
                          </div>
                          <input id={`p-${name}`} type="range" min={p.min} max={p.max} step={STEP[name] ?? (p.max - p.min) / 100} value={params[name] ?? p.default} onChange={(e) => setParams((prev) => ({ ...prev, [name]: Number(e.target.value) }))} className="w-full" />
                          <div className="flex justify-between font-mono text-[10px] text-ink-4"><span>{p.min}</span><span>{p.max}</span></div>
                        </div>
                      ))}
                    </>
                  )}
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
                      <input type="checkbox" checked={autoRun} onChange={(e) => setAutoRun(e.target.checked)} className="size-4 accent-[var(--color-accent)]" />
                      Re-run automatically on change
                    </label>
                    <Button variant="primary" icon={Play} onClick={runSingle} disabled={!file || single.status === 'running'} loading={single.status === 'running'}>
                      Run attack
                    </Button>
                  </div>
                </div>
              ) : (
                <ErrorNotice error={catalogue.error} />
              )}
            </Panel>
          ) : (
            <Panel title="Robustness suite" index="02">
              <p className="text-sm text-ink-2">Runs the standard suite of 21 attacks (JPEG 95→50, Gaussian noise, salt &amp; pepper, blur, median, resize, crop, brightness, contrast, rotation) against the same image and records each result.</p>
              <div className="mt-4 flex justify-end">
                <Button variant="primary" icon={FlaskConical} onClick={runBatch} disabled={!file || batch.status === 'running'} loading={batch.status === 'running'}>
                  Run robustness experiment
                </Button>
              </div>
            </Panel>
          )}
        </div>
        <div className="flex flex-col gap-4">
          <TerminalLog events={op.events} status={op.status} upload={op.upload} title={mode === 'single' ? 'attack.log' : 'robustness-batch.log'} idleText="Results are recomputed by the backend for every attack — detector, extractor, integrity and quality." />
          <ErrorNotice error={op.error} title="Attack failed" />
          {!op.result && op.status === 'idle' && (
            <Panel>
              <div className="flex items-center gap-3 text-sm text-ink-3">
                <Swords className="size-5 text-ink-4" aria-hidden />
                Tip: run the same JPEG quality against LSB, DCT and DWT stego images and compare — batch mode records every outcome.
              </div>
            </Panel>
          )}
        </div>
      </div>
      {mode === 'single' && single.result && <SingleResult result={single.result} />}
      {mode === 'batch' && batch.result && <BatchResult result={batch.result} />}
    </div>
  )
}
