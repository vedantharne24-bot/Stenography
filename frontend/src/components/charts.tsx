/*
 * Chart components. Colour rules (validated palette, see styles/index.css):
 *  - technique identity: normal gray, LSB blue, DCT magenta, DWT yellow - only for technique series;
 *  - generic single measures: neutral bone (--viz-measure);
 *  - status (risk/integrity) always paired with icon + label elsewhere;
 *  - text never wears a series colour.
 */
import { motion } from 'framer-motion'
import type { ReactNode } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from 'recharts'
import { pct } from '../lib/format'
import type { ClassName, Probabilities, RocCurve } from '../lib/types'
import { TECHNIQUE_COLOR, cx } from './ui'

export const VIZ = {
  measure: '#b5afa5',
  measureStrong: '#ece7df',
  grid: '#1f2328',
  axis: '#33383f',
  tick: '#8f8a81',
  font: "'IBM Plex Mono', monospace",
}

export const CLASS_ORDER: ClassName[] = ['normal', 'lsb', 'dct', 'dwt']
export const CLASS_LABEL: Record<string, string> = { normal: 'Normal', lsb: 'LSB', dct: 'DCT', dwt: 'DWT', binary: 'Cover vs stego' }

export const axisProps = {
  tick: { fill: VIZ.tick, fontSize: 11, fontFamily: VIZ.font },
  axisLine: { stroke: VIZ.axis },
  tickLine: false,
} as const

/* ---------------------------------------------------------------- tooltip & legend */

export function ChartTooltip({ active, payload, label, format = (v: number) => v.toLocaleString('en-US') }: Partial<TooltipContentProps<number, string>> & { format?: (v: number) => string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-xs border border-line-strong bg-bg/95 px-3 py-2 shadow-xl backdrop-blur">
      {label !== undefined && <p className="mb-1 font-mono text-[11px] text-ink-3">{String(label)}</p>}
      {payload.map((item) => (
        <p key={String(item.dataKey)} className="flex items-center gap-2 text-xs text-ink">
          <span className="inline-block size-2 rounded-[1px]" style={{ background: (item.color as string) ?? VIZ.measure }} aria-hidden />
          <span className="text-ink-2">{item.name}</span>
          <span className="ml-auto pl-3 font-mono tabular">{typeof item.value === 'number' ? format(item.value) : String(item.value)}</span>
        </p>
      ))}
    </div>
  )
}

export function Legend({ items }: { items: { label: string; color: string; dashed?: boolean }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1" aria-label="Legend">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 font-mono text-[11px] text-ink-2">
          {item.dashed !== undefined ? (
            <svg width="18" height="6" aria-hidden>
              <line x1="0" y1="3" x2="18" y2="3" stroke={item.color} strokeWidth="2" strokeDasharray={item.dashed ? '4 3' : undefined} />
            </svg>
          ) : (
            <span className="inline-block size-2.5 rounded-[1px]" style={{ background: item.color }} aria-hidden />
          )}
          {item.label}
        </li>
      ))}
    </ul>
  )
}

/* ---------------------------------------------------------------- probability bars */

/** Class probability distribution - directly labelled, so identity never relies on colour. */
export function ProbabilityBars({ probs, highlight, compact = false }: { probs: Probabilities; highlight?: ClassName; compact?: boolean }) {
  return (
    <div className="flex flex-col gap-2.5" role="list" aria-label="Class probabilities">
      {CLASS_ORDER.map((cls, i) => {
        const value = probs[cls] ?? 0
        const strong = cls === highlight
        return (
          <div key={cls} role="listitem" className="grid grid-cols-[56px_minmax(0,1fr)_64px] items-center gap-3">
            <span className={cx('font-mono text-xs tracking-wider uppercase', strong ? 'text-ink' : 'text-ink-3')}>{CLASS_LABEL[cls]}</span>
            <div className={cx('relative overflow-hidden rounded-[1px] bg-raised', compact ? 'h-1.5' : 'h-2.5')}>
              <motion.div
                className="absolute inset-y-0 left-0 rounded-r-[3px]"
                style={{ background: TECHNIQUE_COLOR[cls] }}
                initial={{ width: 0 }}
                animate={{ width: `${Math.max(value * 100, 0.4)}%` }}
                transition={{ duration: 0.9, delay: i * 0.08, ease: [0.16, 1, 0.3, 1] }}
              />
            </div>
            <span className={cx('text-right font-mono text-xs tabular', strong ? 'text-ink' : 'text-ink-2')}>{pct(value, 1)}</span>
          </div>
        )
      })}
    </div>
  )
}

/* ---------------------------------------------------------------- bar list (single measure) */

export function BarList({ rows, format = (v) => pct(v, 0), max = 1, color = VIZ.measure }: { rows: { label: ReactNode; value: number | null; note?: ReactNode }[]; format?: (v: number) => string; max?: number; color?: string }) {
  return (
    <ul className="flex flex-col gap-2">
      {rows.map((row, i) => (
        <li key={i} className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,2fr)_56px] items-center gap-3">
          <span className="truncate text-xs text-ink-2">{row.label}</span>
          <div className="relative h-2 overflow-hidden rounded-[1px] bg-raised" title={row.note ? String(row.note) : undefined}>
            <motion.div
              className="absolute inset-y-0 left-0 rounded-r-[3px]"
              style={{ background: color }}
              initial={{ width: 0 }}
              whileInView={{ width: `${row.value === null ? 0 : Math.max(0.5, (row.value / max) * 100)}%` }}
              viewport={{ once: true }}
              transition={{ duration: 0.8, delay: i * 0.03 }}
            />
          </div>
          <span className="text-right font-mono text-xs text-ink tabular">{row.value === null ? '—' : format(row.value)}</span>
        </li>
      ))}
    </ul>
  )
}

/* ---------------------------------------------------------------- confusion matrix */

/** Row-normalised confusion matrix; sequential neutral ramp (recedes to the surface at 0). */
export function ConfusionMatrix({ matrix, labels = CLASS_ORDER }: { matrix: number[][]; labels?: string[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[320px] border-separate border-spacing-[2px] text-center">
        <caption className="sr-only">Confusion matrix: rows are true classes, columns are predicted classes</caption>
        <thead>
          <tr>
            <th className="w-20 text-left font-mono text-[10px] font-normal text-ink-4">true ↓ pred →</th>
            {labels.map((l) => (
              <th key={l} scope="col" className="pb-1 font-mono text-[11px] font-normal tracking-wider text-ink-3 uppercase">
                {CLASS_LABEL[l] ?? l}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, r) => {
            const total = row.reduce((a, b) => a + b, 0) || 1
            return (
              <tr key={r}>
                <th scope="row" className="pr-2 text-left font-mono text-[11px] font-normal tracking-wider text-ink-3 uppercase">
                  {CLASS_LABEL[labels[r]] ?? labels[r]}
                </th>
                {row.map((count, c) => {
                  const share = count / total
                  const light = share > 0.55
                  return (
                    <td
                      key={c}
                      className={cx('h-14 rounded-[2px] font-mono text-xs tabular', r === c && 'outline outline-1 outline-ink-4')}
                      style={{ background: `color-mix(in oklab, #ece7df ${Math.round(4 + share * 82)}%, #111317)`, color: light ? '#08090b' : '#ece7df' }}
                      title={`${CLASS_LABEL[labels[r]]} → ${CLASS_LABEL[labels[c]]}: ${count} (${pct(share)})`}
                    >
                      <span className="block text-[13px] font-medium">{count.toLocaleString('en-US')}</span>
                      <span className="block text-[10px] opacity-75">{pct(share, 1)}</span>
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/* ---------------------------------------------------------------- ROC */

export function RocChart({ curves, height = 280 }: { curves: Record<string, RocCurve>; height?: number }) {
  const keys = Object.keys(curves)
  const colorFor = (k: string) => (k === 'binary' ? VIZ.measureStrong : (TECHNIQUE_COLOR[k] ?? VIZ.measure))
  return (
    <div className="flex flex-col gap-3">
      <Legend items={keys.map((k) => ({ label: CLASS_LABEL[k] ?? k, color: colorFor(k), dashed: k === 'binary' }))} />
      <div style={{ height }}>
        <ResponsiveContainer>
          <LineChart margin={{ top: 4, right: 12, bottom: 18, left: 0 }}>
            <CartesianGrid stroke={VIZ.grid} strokeWidth={1} />
            <XAxis type="number" dataKey="fpr" domain={[0, 1]} {...axisProps} tickFormatter={(v) => v.toFixed(1)} label={{ value: 'False positive rate', position: 'insideBottom', offset: -10, fill: VIZ.tick, fontSize: 11, fontFamily: VIZ.font }} />
            <YAxis type="number" dataKey="tpr" domain={[0, 1]} {...axisProps} tickFormatter={(v) => v.toFixed(1)} width={36} />
            <Tooltip content={<ChartTooltip format={(v) => v.toFixed(3)} />} />
            <Line data={[{ fpr: 0, tpr: 0 }, { fpr: 1, tpr: 1 }]} dataKey="tpr" stroke={VIZ.axis} strokeDasharray="3 4" dot={false} isAnimationActive={false} name="Chance" />
            {keys.map((k) => (
              <Line
                key={k}
                data={curves[k].fpr.map((f, i) => ({ fpr: f, tpr: curves[k].tpr[i] }))}
                dataKey="tpr"
                name={CLASS_LABEL[k] ?? k}
                stroke={colorFor(k)}
                strokeWidth={2}
                strokeDasharray={k === 'binary' ? '5 3' : undefined}
                dot={false}
                type="linear"
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- simple vertical bars */

export function MeasureBars({ data, xKey, yKey, name, height = 220, format = (v: number) => v.toLocaleString('en-US'), colorFor }: { data: Record<string, unknown>[]; xKey: string; yKey: string; name: string; height?: number; format?: (v: number) => string; colorFor?: (row: Record<string, unknown>) => string }) {
  return (
    <div style={{ height }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap="18%">
          <CartesianGrid stroke={VIZ.grid} vertical={false} />
          <XAxis dataKey={xKey} {...axisProps} />
          <YAxis {...axisProps} width={40} tickFormatter={(v) => format(v)} />
          <Tooltip cursor={{ fill: 'rgba(255,255,255,0.03)' }} content={<ChartTooltip format={format} />} />
          <Bar dataKey={yKey} name={name} radius={[4, 4, 0, 0]} fill={VIZ.measure} shape={colorFor ? (props: unknown) => {
            const p = props as { x: number; y: number; width: number; height: number; payload: Record<string, unknown> }
            const r = Math.min(4, p.width / 2, Math.max(0, p.height))
            return <path d={`M${p.x},${p.y + p.height} V${p.y + r} Q${p.x},${p.y} ${p.x + r},${p.y} H${p.x + p.width - r} Q${p.x + p.width},${p.y} ${p.x + p.width},${p.y + r} V${p.y + p.height} Z`} fill={colorFor(p.payload)} />
          } : undefined} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function Sparkline({ values, color = VIZ.measure, height = 36 }: { values: number[]; color?: string; height?: number }) {
  if (values.length < 2) return null
  return (
    <div style={{ height }} aria-hidden>
      <ResponsiveContainer>
        <LineChart data={values.map((v, i) => ({ i, v }))} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
          <Line dataKey="v" stroke={color} strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
