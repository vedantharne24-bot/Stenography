import { motion } from 'framer-motion'
import { Activity, ArrowUpRight, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { BarList, ChartTooltip, Legend, MeasureBars, VIZ, axisProps } from '../components/charts'
import { Button, CountUp, EmptyState, ErrorNotice, PageHeader, Panel, RISK_TONE, RiskBadge, Skeleton, Stat, StatusBadge, TECHNIQUE_COLOR, TechniqueChip, cx } from '../components/ui'
import { useAuth } from '../lib/auth'
import { int, ms, num, pct, relative } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { RiskLevel } from '../lib/types'

interface DashboardData {
  scope: 'global' | 'personal'
  generated_at: string
  totals: {
    images_analyzed: number
    stego_detected: number
    normal_images: number
    detection_rate: number | null
    average_confidence: number | null
    high_risk: number
    average_risk: number | null
    average_inference_ms: number | null
    encryption_operations: number
    extraction_operations: number
    failed_operations: number
    attack_experiments: number
    research_runs: number
    registered_model_versions: number
  }
  models: Record<string, { id: string; name: string; version: string; accuracy: number | null; f1: number | null; roc_auc: number | null; binary_accuracy?: number; detection_rate?: number; false_positive_rate?: number; trained_at: string | null } | null>
  trends: { date: string; total: number; stego: number; cover: number; avg_risk: number }[]
  technique_distribution: { technique: string; count: number }[]
  risk_distribution: { level: RiskLevel; count: number }[]
  risk_histogram: { bin: string; count: number }[]
  attack_robustness: { attack: string; runs: number; extraction_success: number; mean_detection: number; mean_psnr: number | null }[]
  algorithms: { algorithm: string; count: number; avg_psnr: number | null; avg_ssim: number | null; avg_utilization: number | null }[]
  recent: { id: string; filename: string; prediction: string; technique: string; confidence: number; risk_score: number; risk_level: RiskLevel; source: string; created_at: string }[]
}

const STATUS_COLOR: Record<RiskLevel, string> = { LOW: 'var(--color-ok)', MEDIUM: 'var(--color-warn)', HIGH: 'var(--color-serious)', CRITICAL: 'var(--color-critical)' }

export default function Dashboard() {
  const { user } = useAuth()
  const { data, error, loading, reload } = useApi<DashboardData>('/api/dashboard/stats')
  const cnn = data?.models['steganalysis-cnn']
  const rf = data?.models['steganalysis-rf']
  const t = data?.totals

  return (
    <div>
      <PageHeader
        index="01"
        kicker={data ? (data.scope === 'global' ? 'Command centre · all operators' : 'Command centre · your activity') : 'Command centre'}
        title="Dashboard"
        description={`Live figures computed from the database${data ? ` at ${new Date(data.generated_at).toLocaleTimeString('en-GB')}` : ''}. Nothing on this page is static.`}
        actions={
          <Button variant="ghost" icon={RefreshCw} onClick={reload} loading={loading}>
            Refresh
          </Button>
        }
      />
      <ErrorNotice error={error} title="Could not load dashboard" />

      {loading && !data ? (
        <div className="grid gap-4 md:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : data && t ? (
        <div className="flex flex-col gap-6">
          <Panel brackets bodyClassName="grid grid-cols-2 gap-y-6 py-5 md:grid-cols-4 xl:grid-cols-5">
            <Stat label="Images analysed" value={<CountUp value={t.images_analyzed} />} sub={`${int(t.normal_images)} classified normal`} />
            <Stat label="Stego detected" value={<CountUp value={t.stego_detected} />} sub={`detection rate ${pct(t.detection_rate)}`} />
            <Stat label="High-risk" value={<CountUp value={t.high_risk} />} sub={`avg risk ${num(t.average_risk, 1)}`} tone={t.high_risk ? 'serious' : undefined} />
            <Stat label="Avg confidence" value={t.average_confidence === null ? '—' : <CountUp value={t.average_confidence * 100} format={(v) => `${v.toFixed(1)}%`} />} sub={`inference ${ms(t.average_inference_ms)}`} />
            <Stat label="Encryptions" value={<CountUp value={t.encryption_operations} />} sub={`${int(t.extraction_operations)} extractions`} />
            <Stat label="Model accuracy" value={cnn?.accuracy ? <CountUp value={cnn.accuracy * 100} format={(v) => `${v.toFixed(2)}%`} /> : '—'} sub={cnn ? `StegoNet v${cnn.version} · test split` : 'no model trained'} />
            <Stat label="Binary detection" value={cnn?.detection_rate ? pct(cnn.detection_rate, 1) : '—'} sub={cnn ? `FPR ${pct(cnn.false_positive_rate, 2)}` : undefined} />
            <Stat label="Attack runs" value={<CountUp value={t.attack_experiments} />} sub={`${int(t.research_runs)} research runs`} />
            <Stat label="Failed operations" value={<CountUp value={t.failed_operations} />} sub="capacity / integrity" tone={t.failed_operations ? 'warn' : undefined} />
            <Stat label="Model versions" value={<CountUp value={t.registered_model_versions} />} sub={rf ? `RF v${rf.version} acc ${pct(rf.accuracy)}` : 'registry'} />
          </Panel>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Panel title="Detection trend · last 30 days" index="T1" actions={<Legend items={[{ label: 'Cover', color: 'var(--color-normal)' }, { label: 'Stego', color: 'var(--color-serious)' }]} />}>
              {data.trends.length ? (
                <div className="h-64">
                  <ResponsiveContainer>
                    <BarChart data={data.trends} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="22%">
                      <CartesianGrid stroke={VIZ.grid} vertical={false} />
                      <XAxis dataKey="date" {...axisProps} tickFormatter={(d: string) => d.slice(5)} />
                      <YAxis {...axisProps} width={32} allowDecimals={false} />
                      <Tooltip cursor={{ fill: 'rgba(255,255,255,0.03)' }} content={<ChartTooltip />} />
                      <Bar dataKey="cover" name="Cover" stackId="a" fill="var(--color-normal)" stroke="var(--color-surface)" strokeWidth={2} />
                      <Bar dataKey="stego" name="Stego" stackId="a" fill="var(--color-serious)" stroke="var(--color-surface)" strokeWidth={2} radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState icon={Activity} title="No analyses yet">
                  Run an analysis in <Link className="text-accent" to="/steganalysis">Steganalysis</Link> — results appear here immediately.
                </EmptyState>
              )}
            </Panel>
            <Panel title="Risk distribution" index="T2">
              <ul className="flex flex-col gap-3">
                {data.risk_distribution.map((row) => {
                  const total = data.risk_distribution.reduce((a, b) => a + b.count, 0) || 1
                  return (
                    <li key={row.level} className="grid grid-cols-[110px_minmax(0,1fr)_48px] items-center gap-3">
                      <RiskBadge level={row.level} />
                      <div className="h-2 overflow-hidden rounded-[1px] bg-raised">
                        <motion.div className="h-full rounded-r-[3px]" style={{ background: STATUS_COLOR[row.level] }} initial={{ width: 0 }} animate={{ width: `${(row.count / total) * 100}%` }} transition={{ duration: 0.8 }} />
                      </div>
                      <span className="text-right font-mono text-xs tabular">{row.count}</span>
                    </li>
                  )
                })}
              </ul>
              <div className="mt-5 border-t border-line pt-4">
                <p className="label-mono mb-2">Risk score histogram</p>
                <MeasureBars data={data.risk_histogram} xKey="bin" yKey="count" name="Analyses" height={130} />
              </div>
            </Panel>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Panel title="Predicted technique" index="T3">
              <MeasureBars
                data={data.technique_distribution.map((d) => ({ ...d, label: d.technique === 'normal' ? 'Normal' : d.technique.toUpperCase() }))}
                xKey="label"
                yKey="count"
                name="Analyses"
                height={200}
                colorFor={(row) => TECHNIQUE_COLOR[row.technique as string]}
              />
            </Panel>
            <Panel title="Attack robustness" index="T4" actions={<Link to="/attack-lab" className="text-ink-3 hover:text-accent" aria-label="Open attack lab"><ArrowUpRight className="size-4" /></Link>}>
              {data.attack_robustness.length ? (
                <>
                  <p className="label-mono mb-3">Payload extraction survival by attack</p>
                  <BarList rows={data.attack_robustness.map((a) => ({ label: `${a.attack} (${a.runs})`, value: a.extraction_success }))} />
                </>
              ) : (
                <EmptyState title="No attack experiments yet" />
              )}
            </Panel>
            <Panel title="Embedding operations" index="T5">
              {data.algorithms.length ? (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left">
                      <th className="label-mono pb-2 font-normal">Alg.</th>
                      <th className="label-mono pb-2 text-right font-normal">Ops</th>
                      <th className="label-mono pb-2 text-right font-normal">PSNR</th>
                      <th className="label-mono pb-2 text-right font-normal">SSIM</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.algorithms.map((a) => (
                      <tr key={a.algorithm} className="border-t border-line">
                        <td className="py-2"><TechniqueChip technique={a.algorithm} /></td>
                        <td className="py-2 text-right font-mono tabular">{a.count}</td>
                        <td className="py-2 text-right font-mono tabular">{num(a.avg_psnr, 2)}</td>
                        <td className="py-2 text-right font-mono tabular">{num(a.avg_ssim, 4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <EmptyState title="No embeddings yet" />
              )}
            </Panel>
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <Panel title="Model performance" index="T6">
              {cnn || rf ? (
                <div className="flex flex-col gap-4">
                  {[cnn, rf].filter(Boolean).map((m) => (
                    <div key={m!.id} className="border-b border-line pb-3 last:border-0">
                      <p className="flex items-center justify-between font-mono text-xs text-ink-2">
                        {m!.name} <span className="text-ink-3">v{m!.version}</span>
                      </p>
                      <div className="mt-2 grid grid-cols-3 gap-2">
                        {[['Accuracy', m!.accuracy], ['Macro F1', m!.f1], ['ROC-AUC', m!.roc_auc]].map(([k, v]) => (
                          <div key={k as string}>
                            <p className="label-mono">{k}</p>
                            <p className="font-mono text-lg tabular">{pct(v as number | null, 2)}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                  <Link to="/models" className="text-sm text-accent hover:underline">Full evaluation →</Link>
                </div>
              ) : (
                <EmptyState title="No trained model registered" />
              )}
            </Panel>
            <Panel title="Analysis history" index="T7" actions={<Link to="/history" className="text-xs text-accent hover:underline">All →</Link>}>
              {data.recent.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] text-sm">
                    <thead>
                      <tr className="text-left">
                        <th className="label-mono pb-2 font-normal">File</th>
                        <th className="label-mono pb-2 font-normal">Verdict</th>
                        <th className="label-mono pb-2 font-normal">Technique</th>
                        <th className="label-mono pb-2 text-right font-normal">Conf.</th>
                        <th className="label-mono pb-2 font-normal">Risk</th>
                        <th className="label-mono pb-2 text-right font-normal">When</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.recent.map((r) => (
                        <tr key={r.id} className="border-t border-line">
                          <td className="max-w-48 truncate py-2 text-ink-2" title={r.filename}>{r.filename}</td>
                          <td className="py-2"><StatusBadge tone={r.prediction === 'stego' ? RISK_TONE[r.risk_level] : 'neutral'} icon={null}>{r.prediction}</StatusBadge></td>
                          <td className="py-2"><TechniqueChip technique={r.technique} /></td>
                          <td className="py-2 text-right font-mono tabular">{pct(r.confidence)}</td>
                          <td className="py-2"><RiskBadge level={r.risk_level} score={r.risk_score} /></td>
                          <td className={cx('py-2 text-right font-mono text-xs text-ink-3')}>{relative(r.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="Nothing analysed yet" />
              )}
            </Panel>
          </div>
          {user && <p className="font-mono text-[10px] text-ink-4">Scope: {data.scope === 'global' ? 'all operators (analyst/admin view)' : `records owned by ${user.email}`}</p>}
        </div>
      ) : null}
    </div>
  )
}
