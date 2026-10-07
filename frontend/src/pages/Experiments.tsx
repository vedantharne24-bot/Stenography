import { motion } from 'framer-motion'
import { FlaskConical, Trophy } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ChartTooltip, Legend, VIZ, axisProps } from '../components/charts'
import { TerminalLog } from '../components/TerminalLog'
import { Button, EmptyState, ErrorNotice, Field, Input, PageHeader, Panel, Segmented, Skeleton, TECHNIQUE_COLOR, TechniqueChip, cx } from '../components/ui'
import { api } from '../lib/api'
import { bytes, dateTime, ms, num, pct } from '../lib/format'
import { useApi, useOperation } from '../lib/hooks'
import type { Algorithm, ExperimentResult } from '../lib/types'

const ALGOS: Algorithm[] = ['lsb', 'dct', 'dwt']
const CRITERIA = ['capacity', 'quality', 'robustness', 'undetectability'] as const

function ComparisonTable({ r }: { r: ExperimentResult }) {
  const rows: [string, (a: Algorithm) => string, string][] = [
    ['Capacity (payload)', (a) => bytes(r.summary[a].capacity_bytes), 'max plaintext bytes per image'],
    ['Capacity (bpp)', (a) => num(r.summary[a].capacity_bpp, 4), 'payload bits per pixel'],
    ['Payload tested', (a) => bytes(r.summary[a].payload_bytes), 'mean bytes embedded'],
    ['PSNR', (a) => `${num(r.summary[a].psnr, 2)} ± ${num(r.summary[a].psnr_std, 2)} dB`, 'higher = less visible'],
    ['SSIM', (a) => num(r.summary[a].ssim, 5), 'structural similarity'],
    ['MSE', (a) => num(r.summary[a].mse, 4), 'mean squared error'],
    ['Extraction success', (a) => pct(r.summary[a].extraction_success, 1), 'unattacked'],
    ['AI detection rate', (a) => pct(r.summary[a].detection_rate, 1), 'StegoNet flags stego'],
    ['Technique identified', (a) => pct(r.summary[a].technique_accuracy, 1), 'correct class'],
    ['Robustness', (a) => pct(r.summary[a].robustness, 1), `survival over ${r.attacks.length} attacks`],
    ['Embed time', (a) => ms(r.summary[a].embed_ms), 'computational cost'],
    ['Extract time', (a) => ms(r.summary[a].extract_ms), 'computational cost'],
  ]
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="text-left">
            <th className="label-mono pb-2 font-normal">Metric</th>
            {ALGOS.map((a) => <th key={a} className="pb-2 text-right font-normal"><TechniqueChip technique={a} /></th>)}
            <th className="label-mono hidden pb-2 pl-4 font-normal md:table-cell">Meaning</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, fn, meaning]) => (
            <tr key={label} className="border-t border-line">
              <td className="py-2 text-ink-2">{label}</td>
              {ALGOS.map((a) => <td key={a} className="py-2 text-right font-mono tabular">{fn(a)}</td>)}
              <td className="hidden py-2 pl-4 text-xs text-ink-3 md:table-cell">{meaning}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ExperimentView({ r }: { r: ExperimentResult }) {
  const radar = CRITERIA.map((c) => ({ criterion: c, ...Object.fromEntries(ALGOS.map((a) => [a, r.normalised[c]?.[a] ?? 0])) }))
  const attackLabels = Object.keys(r.summary.lsb.per_attack)
  const perAttack = attackLabels.map((label) => ({ label: label.replace(':', ' '), ...Object.fromEntries(ALGOS.map((a) => [a, r.summary[a].per_attack[label] ?? 0])) }))
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-6">
      <Panel brackets>
        <div className="flex flex-col gap-4 md:flex-row md:items-center">
          <Trophy className="size-8 shrink-0 text-accent" aria-hidden />
          <div className="flex-1">
            <p className="label-mono">Answer from measured data · run {r.run_id.slice(0, 8)} · {dateTime(r.created_at)}</p>
            <p className="mt-1 text-lg leading-snug text-ink">{r.answer}</p>
          </div>
          <div className="flex gap-6">
            {r.ranking.map((a, i) => (
              <div key={a} className="text-center">
                <p className="font-mono text-[10px] text-ink-4">#{i + 1}</p>
                <TechniqueChip technique={a} />
                <p className="font-display text-2xl font-bold tabular">{num(r.balance_score[a], 2)}</p>
              </div>
            ))}
          </div>
        </div>
      </Panel>

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Panel title="Technique comparison" index="X1">
          {r.winners && (
            <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {CRITERIA.map((c) => (
                <div key={c} className="rounded-xs border border-line p-2">
                  <p className="label-mono">best {c}</p>
                  <div className="mt-1">{r.winners![c] === 'tie' ? <span className="font-mono text-xs text-ink-3">no meaningful difference</span> : <TechniqueChip technique={r.winners![c]} />}</div>
                </div>
              ))}
            </div>
          )}
          <ComparisonTable r={r} />
          <p className="mt-3 font-mono text-[11px] text-ink-3">Cover false-positive rate on the same images: {pct(r.cover_false_positive_rate, 1)}</p>
        </Panel>
        <Panel title="Balance profile (min-max normalised)" index="X2">
          <Legend items={ALGOS.map((a) => ({ label: a.toUpperCase(), color: TECHNIQUE_COLOR[a] }))} />
          <div className="h-72">
            <ResponsiveContainer>
              <RadarChart data={radar} outerRadius="72%">
                <PolarGrid stroke={VIZ.grid} />
                <PolarAngleAxis dataKey="criterion" tick={{ fill: VIZ.tick, fontSize: 11, fontFamily: VIZ.font }} />
                <PolarRadiusAxis domain={[0, 1]} tick={false} axisLine={false} />
                <Tooltip content={<ChartTooltip format={(v) => v.toFixed(2)} />} />
                {ALGOS.map((a) => (
                  <Radar key={a} dataKey={a} name={a.toUpperCase()} stroke={TECHNIQUE_COLOR[a]} strokeWidth={2} fill={TECHNIQUE_COLOR[a]} fillOpacity={0.08} />
                ))}
              </RadarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-ink-3">Capacity: log-scaled bpp, min-max across techniques. Quality: PSNR mapped from a fixed 35–55 dB range. Robustness: survival rate. Undetectability: 1 − AI detection rate. Absolute scales are used wherever one exists.</p>
        </Panel>
      </div>

      <Panel title="Payload survival per attack" index="X3">
        <Legend items={ALGOS.map((a) => ({ label: a.toUpperCase(), color: TECHNIQUE_COLOR[a] }))} />
        <div className="mt-2 h-72">
          <ResponsiveContainer>
            <BarChart data={perAttack} margin={{ top: 8, right: 8, left: 0, bottom: 30 }} barGap={2} barCategoryGap="20%">
              <CartesianGrid stroke={VIZ.grid} vertical={false} />
              <XAxis dataKey="label" {...axisProps} angle={-20} textAnchor="end" interval={0} height={50} />
              <YAxis {...axisProps} domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} width={40} />
              <Tooltip cursor={{ fill: 'rgba(255,255,255,0.03)' }} content={<ChartTooltip format={(v) => pct(v, 0)} />} />
              {ALGOS.map((a) => <Bar key={a} dataKey={a} name={a.toUpperCase()} fill={TECHNIQUE_COLOR[a]} radius={[4, 4, 0, 0]} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <details className="rounded-xs border border-line bg-surface p-4">
        <summary className="cursor-pointer font-mono text-xs tracking-wider text-ink-2 uppercase">Methodology</summary>
        <pre className="mt-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-ink-3">{r.methodology}</pre>
      </details>
    </motion.div>
  )
}

export default function Experiments() {
  const history = useApi<{ id: string; config: Record<string, unknown>; ranking: Algorithm[] | null; answer: string | null; created_at: string; duration_ms: number }[]>('/api/experiments')
  const [images, setImages] = useState(12)
  const [mode, setMode] = useState<'relative' | 'absolute'>('relative')
  const [relative, setRelative] = useState(0.5)
  const [absolute, setAbsolute] = useState(64)
  const [seed, setSeed] = useState(0)
  const [weights, setWeights] = useState<Record<string, number>>({ capacity: 1, quality: 1, robustness: 1, undetectability: 1 })
  const op = useOperation<ExperimentResult>('/api/experiments/run')
  const [loaded, setLoaded] = useState<ExperimentResult | null>(null)
  const [loadingRun, setLoadingRun] = useState(false)

  useEffect(() => {
    if (op.status === 'success') history.reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [op.status])

  useEffect(() => {
    const latest = history.data?.[0]
    if (!latest || loaded || op.result) return
    setLoadingRun(true)
    api<ExperimentResult>(`/api/experiments/${latest.id}`)
      .then(setLoaded)
      .finally(() => setLoadingRun(false))
  }, [history.data, loaded, op.result])

  const run = () => op.run({ images, payload_mode: mode, relative, absolute_bytes: absolute, seed, weights })
  const shown = op.result ?? loaded
  const progress = [...op.events].reverse().find((e) => e.stage === 'progress')?.data as { done?: number; total?: number } | undefined

  return (
    <div>
      <PageHeader
        index="07"
        kicker="Research · LSB vs DCT vs DWT"
        title="Experiments"
        description="Which steganographic technique gives the best balance between payload capacity, visual quality, robustness and AI detectability? Run the comparison on held-out test images the models never saw."
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <Panel title="Experiment design" index="01" brackets>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Held-out images" htmlFor="n">
              <Input id="n" type="number" min={3} max={60} value={images} onChange={(e) => setImages(Number(e.target.value))} />
            </Field>
            <Field label="Random seed" htmlFor="seed" hint="Same seed = same image sample">
              <Input id="seed" type="number" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
            </Field>
            <Field label="Payload">
              <Segmented label="Payload mode" size="sm" value={mode} onChange={setMode} options={[{ value: 'relative', label: '% of capacity' }, { value: 'absolute', label: 'Fixed bytes' }]} />
            </Field>
            {mode === 'relative' ? (
              <Field label={`Relative payload · ${Math.round(relative * 100)}%`} htmlFor="rel">
                <input id="rel" type="range" min={0.05} max={1} step={0.05} value={relative} onChange={(e) => setRelative(Number(e.target.value))} />
              </Field>
            ) : (
              <Field label="Payload bytes" htmlFor="abs" hint="Images too small for a technique are skipped and counted">
                <Input id="abs" type="number" min={1} value={absolute} onChange={(e) => setAbsolute(Number(e.target.value))} />
              </Field>
            )}
          </div>
          <div className="mt-5 border-t border-line pt-4">
            <p className="label-mono mb-3">Balance weights</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {CRITERIA.map((c) => (
                <label key={c} className="flex flex-col gap-1">
                  <span className="flex justify-between font-mono text-[11px] text-ink-2"><span>{c}</span><span className="tabular">{weights[c].toFixed(1)}</span></span>
                  <input type="range" min={0} max={3} step={0.5} value={weights[c]} onChange={(e) => setWeights((w) => ({ ...w, [c]: Number(e.target.value) }))} aria-label={`${c} weight`} />
                </label>
              ))}
            </div>
          </div>
          <div className="mt-5 flex items-center justify-between gap-3">
            {op.status === 'running' && progress?.total ? (
              <span className="font-mono text-xs text-ink-2 tabular">{progress.done}/{progress.total} images measured</span>
            ) : (
              <span />
            )}
            <Button variant="primary" size="lg" icon={FlaskConical} onClick={run} loading={op.status === 'running'} disabled={op.status === 'running'}>
              Run comparison
            </Button>
          </div>
        </Panel>
        <div className="flex flex-col gap-4">
          <TerminalLog events={op.events} status={op.status} upload={op.upload} title="experiment.log" maxHeight="max-h-64" />
          <ErrorNotice error={op.error} title="Experiment failed" />
          <Panel title="Previous runs" index="02">
            {history.loading ? (
              <Skeleton className="h-24" />
            ) : history.data?.length ? (
              <ul className="flex max-h-56 flex-col overflow-y-auto">
                {history.data.map((h) => (
                  <li key={h.id}>
                    <button
                      type="button"
                      className={cx('flex w-full items-center justify-between gap-3 border-b border-line py-2 text-left text-sm hover:text-ink', shown?.run_id === h.id ? 'text-ink' : 'text-ink-2')}
                      onClick={async () => {
                        setLoadingRun(true)
                        try {
                          setLoaded(await api<ExperimentResult>(`/api/experiments/${h.id}`))
                          op.reset()
                        } finally {
                          setLoadingRun(false)
                        }
                      }}
                    >
                      <span className="font-mono text-xs">{dateTime(h.created_at)} · {String(h.config.images)} imgs · {String(h.config.payload_mode) === 'absolute' ? `${String(h.config.absolute_bytes)} B` : `${Math.round(Number(h.config.relative) * 100)}%`}{h.config.model_version ? ` · model v${String(h.config.model_version)}` : ''}</span>
                      <span className="font-mono text-xs">{h.ranking?.map((a) => a.toUpperCase()).join(' > ')}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No runs yet" />
            )}
          </Panel>
        </div>
      </div>
      <div className="mt-8">{loadingRun ? <Skeleton className="h-96" /> : shown ? <ExperimentView r={shown} /> : null}</div>
    </div>
  )
}
