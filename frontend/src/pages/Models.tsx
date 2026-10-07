import { motion } from 'framer-motion'
import { BrainCircuit, CheckCircle2, Power } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { BarList, CLASS_LABEL, CLASS_ORDER, ChartTooltip, ConfusionMatrix, Legend, RocChart, VIZ, axisProps } from '../components/charts'
import { Button, EmptyState, ErrorNotice, Hash, KeyValue, PageHeader, Panel, Skeleton, Stat, StatusBadge, TECHNIQUE_COLOR, cx } from '../components/ui'
import { api, type ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime, int, num, pct } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { ModelDetail, ModelRow } from '../lib/types'

function UtilisationChart({ rows }: { rows: NonNullable<ModelDetail['metrics']['by_utilisation']> }) {
  const bins = Array.from(new Set(rows.map((r) => r.bin)))
  const data = bins.map((bin) => ({
    bin,
    ...Object.fromEntries(rows.filter((r) => r.bin === bin).map((r) => [r.technique, r.detection_rate])),
    ...Object.fromEntries(rows.filter((r) => r.bin === bin).map((r) => [`${r.technique}_n`, r.samples])),
  }))
  return (
    <div className="flex flex-col gap-3">
      <Legend items={(['lsb', 'dct', 'dwt'] as const).map((t) => ({ label: t.toUpperCase(), color: TECHNIQUE_COLOR[t] }))} />
      <div className="h-64">
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={2} barCategoryGap="22%">
            <CartesianGrid stroke={VIZ.grid} vertical={false} />
            <XAxis dataKey="bin" {...axisProps} />
            <YAxis {...axisProps} domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} width={40} />
            <Tooltip cursor={{ fill: 'rgba(255,255,255,0.03)' }} content={<ChartTooltip format={(v) => pct(v, 1)} />} />
            {(['lsb', 'dct', 'dwt'] as const).map((t) => (
              <Bar key={t} dataKey={t} name={t.toUpperCase()} fill={TECHNIQUE_COLOR[t]} radius={[4, 4, 0, 0]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-ink-3">Detection rate on held-out test stego images, binned by embedding utilisation (share of carrier slots used). Low-payload embedding is substantially harder to detect.</p>
    </div>
  )
}

function TrainingCurves({ history }: { history: NonNullable<ModelDetail['history']> }) {
  const data = history.history
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="label-mono">Loss</p>
          <Legend items={[{ label: 'train', color: VIZ.tick, dashed: true }, { label: 'validation', color: VIZ.measureStrong, dashed: false }]} />
        </div>
        <div className="h-52">
          <ResponsiveContainer>
            <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={VIZ.grid} vertical={false} />
              <XAxis dataKey="epoch" {...axisProps} />
              <YAxis {...axisProps} width={44} tickFormatter={(v) => v.toFixed(2)} />
              <Tooltip content={<ChartTooltip format={(v) => v.toFixed(4)} />} labelFormatter={(e) => `epoch ${e}`} />
              <Line dataKey="train_loss" name="train" stroke={VIZ.tick} strokeDasharray="4 3" strokeWidth={2} dot={false} />
              <Line dataKey="val_loss" name="validation" stroke={VIZ.measureStrong} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="label-mono">Accuracy</p>
          <Legend items={[{ label: 'train', color: VIZ.tick, dashed: true }, { label: 'validation', color: VIZ.measureStrong, dashed: false }]} />
        </div>
        <div className="h-52">
          <ResponsiveContainer>
            <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={VIZ.grid} vertical={false} />
              <XAxis dataKey="epoch" {...axisProps} />
              <YAxis {...axisProps} width={44} domain={[(min: number) => Math.floor(min * 20) / 20, 1]} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
              <Tooltip content={<ChartTooltip format={(v) => pct(v, 2)} />} labelFormatter={(e) => `epoch ${e}`} />
              <Line dataKey="train_accuracy" name="train" stroke={VIZ.tick} strokeDasharray="4 3" strokeWidth={2} dot={false} />
              <Line dataKey="val_accuracy" name="validation" stroke={VIZ.measureStrong} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
      <p className="font-mono text-[11px] text-ink-3 md:col-span-2">Best epoch {history.best.epoch} · val macro-F1 {num(history.best.f1, 4)} · checkpoint selected on validation, metrics below are on the untouched test split.</p>
    </div>
  )
}

function ModelDetailView({ id }: { id: string }) {
  const { data, error, loading } = useApi<ModelDetail>(`/api/models/${id}/metrics`)
  if (loading) return <Skeleton className="h-96" />
  if (error) return <ErrorNotice error={error} />
  if (!data) return null
  const m = data.metrics
  if (!m?.multiclass) return <EmptyState title="No evaluation metrics for this version" />
  const card = (data.card ?? {}) as Record<string, any>
  return (
    <motion.div key={id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col gap-6">
      <Panel brackets bodyClassName="grid grid-cols-2 gap-y-6 py-5 md:grid-cols-4 xl:grid-cols-7">
        <Stat label="Accuracy" value={pct(m.multiclass.accuracy, 2)} sub="4-class, test split" />
        <Stat label="Precision" value={pct(m.multiclass.precision_macro, 2)} sub="macro" />
        <Stat label="Recall" value={pct(m.multiclass.recall_macro, 2)} sub="macro" />
        <Stat label="F1" value={pct(m.multiclass.f1_macro, 2)} sub="macro" />
        <Stat label="ROC-AUC" value={num(m.multiclass.roc_auc_macro_ovr, 4)} sub="macro one-vs-rest" />
        <Stat label="Detection" value={pct(m.binary.detection_rate, 2)} sub="stego recall" />
        <Stat label="False pos." value={pct(m.binary.false_positive_rate, 2)} sub={`${int(m.samples)} test images`} />
      </Panel>
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Confusion matrix · test split" index="E1">
          <ConfusionMatrix matrix={m.multiclass.confusion_matrix} />
        </Panel>
        <Panel title="ROC curves" index="E2">
          <RocChart curves={m.roc_curves} />
        </Panel>
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <Panel title="Classification report" index="E3">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left">
                {['Class', 'Precision', 'Recall', 'F1', 'AUC', 'Support'].map((h, i) => <th key={h} className={cx('label-mono px-2 pb-2 font-normal first:pl-0', i > 0 && 'text-right')}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {CLASS_ORDER.map((c) => {
                const row = m.multiclass.per_class[c]
                return (
                  <tr key={c} className="border-t border-line">
                    <td className="py-2"><span className="flex items-center gap-2 font-mono text-xs uppercase"><span className="size-2 rounded-[1px]" style={{ background: TECHNIQUE_COLOR[c] }} />{CLASS_LABEL[c]}</span></td>
                    <td className="px-2 py-2 text-right font-mono tabular">{num(row.precision, 4)}</td>
                    <td className="px-2 py-2 text-right font-mono tabular">{num(row.recall, 4)}</td>
                    <td className="px-2 py-2 text-right font-mono tabular">{num(row.f1, 4)}</td>
                    <td className="px-2 py-2 text-right font-mono tabular">{num(row.roc_auc, 4)}</td>
                    <td className="px-2 py-2 text-right font-mono tabular">{int(row.support)}</td>
                  </tr>
                )
              })}
              <tr className="border-t border-line-strong">
                <td className="py-2 font-mono text-xs text-ink-3 uppercase">Cover vs stego</td>
                <td className="px-2 py-2 text-right font-mono tabular">{num(m.binary.precision, 4)}</td>
                <td className="px-2 py-2 text-right font-mono tabular">{num(m.binary.recall, 4)}</td>
                <td className="px-2 py-2 text-right font-mono tabular">{num(m.binary.f1, 4)}</td>
                <td className="px-2 py-2 text-right font-mono tabular">{num(m.binary.roc_auc, 4)}</td>
                <td className="px-2 py-2 text-right font-mono tabular">{int(m.samples)}</td>
              </tr>
            </tbody>
          </table>
        </Panel>
        {m.by_utilisation && (
          <Panel title="Detection vs payload size" index="E4">
            <UtilisationChart rows={m.by_utilisation} />
          </Panel>
        )}
      </div>
      {data.history && (
        <Panel title="Training curves" index="E5">
          <TrainingCurves history={data.history} />
        </Panel>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        {m.by_cover_variant && (
          <Panel title="By cover source" index="E6">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left">
                  {['Cover variant', 'Covers', 'FPR', 'Detection', 'Accuracy'].map((h, i) => <th key={h} className={cx('label-mono px-2 pb-2 font-normal first:pl-0', i > 0 && 'text-right')}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {m.by_cover_variant.map((v) => (
                  <tr key={v.variant} className="border-t border-line">
                    <td className="py-2 font-mono text-xs">{v.variant}</td>
                    <td className="px-2 py-2 text-right font-mono tabular">{int(v.covers)}</td>
                    <td className="px-2 py-2 text-right font-mono tabular">{pct(v.false_positive_rate, 2)}</td>
                    <td className="px-2 py-2 text-right font-mono tabular">{pct(v.detection_rate, 2)}</td>
                    <td className="px-2 py-2 text-right font-mono tabular">{pct(v.accuracy, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-3 text-xs text-ink-3">native_jpeg_grid covers keep JPEG quantisation traces (hard negatives for the DCT class); downscaled covers are artefact-free.</p>
          </Panel>
        )}
        {m.feature_importance && (
          <Panel title="Feature importance" index="E7">
            {m.feature_group_importance && (
              <div className="mb-4">
                <p className="label-mono mb-2">By feature group</p>
                <BarList rows={Object.entries(m.feature_group_importance).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: k, value: v }))} format={(v) => pct(v, 1)} max={Math.max(...Object.values(m.feature_group_importance))} />
              </div>
            )}
            <p className="label-mono mb-2">Top features (Gini importance)</p>
            <BarList rows={m.feature_importance.slice(0, 10).map((f) => ({ label: f.feature, value: f.importance }))} format={(v) => v.toFixed(3)} max={m.feature_importance[0]?.importance || 1} />
            {m.anomaly_model && <p className="mt-3 font-mono text-[11px] text-ink-3">Anomaly model test AUC (cover vs stego): {num(m.anomaly_model.test_auc_cover_vs_stego, 4)}</p>}
          </Panel>
        )}
        <Panel title="Model card · provenance" index="E8">
          <KeyValue
            rows={[
              ['Name', String(card.display_name ?? data.model_name)],
              ['Version', data.version],
              ['Framework', data.framework],
              ['Trained', dateTime(data.trained_at)],
              ...(card.parameters ? ([['Parameters', int(card.parameters as number)]] as [string, string][]) : []),
              ...(card.training?.best_epoch ? ([['Best epoch', `${card.training.best_epoch} / ${card.training.epochs_run}`]] as [string, string][]) : []),
              ...(card.training?.device ? ([['Device', String(card.training.device)]] as [string, string][]) : []),
              ['Train / val / test images', card.dataset?.images ? `${int(card.dataset.images.train)} / ${int(card.dataset.images.val)} / ${int(card.dataset.images.test)}` : '—'],
              ['Source-level leakage check', card.dataset?.leakage_check?.passed ? 'passed (0 shared sources)' : '—'],
            ]}
          />
          <div className="mt-3 border-t border-line pt-3">
            <Hash label="Weights SHA-256" value={data.weights_sha256} />
          </div>
        </Panel>
      </div>
    </motion.div>
  )
}

export default function Models() {
  const { can } = useAuth()
  const { data, error, loading, reload } = useApi<ModelRow[]>('/api/models')
  const [selected, setSelected] = useState<string | null>(null)
  const [activateError, setActivateError] = useState<ApiError | null>(null)
  useEffect(() => {
    if (data && !selected) setSelected(data.find((m) => m.is_active && m.kind === 'cnn')?.id ?? data[0]?.id ?? null)
  }, [data, selected])
  const groups = useMemo(() => {
    const semver = (v: string) => v.split('.').map(Number)
    const newestFirst = (a: ModelRow, b: ModelRow) => {
      const [x, y] = [semver(a.version), semver(b.version)]
      for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return y[i] - x[i]
      return 0
    }
    const out: Record<string, ModelRow[]> = {}
    for (const m of data ?? []) (out[m.model_name] ??= []).push(m)
    Object.values(out).forEach((list) => list.sort(newestFirst))
    return out
  }, [data])

  const activate = async (id: string) => {
    setActivateError(null)
    try {
      await api(`/api/models/${id}/activate`, { method: 'POST' })
      reload()
    } catch (err) {
      setActivateError(err as ApiError)
    }
  }

  return (
    <div>
      <PageHeader
        index="10"
        kicker="AI · model registry & evaluation"
        title="Models"
        description="Every metric is read from the evaluation reports produced by pipeline/train_model.py and pipeline/evaluate_model.py on the held-out test split, then served from the model registry. Each version's headline numbers come from the test split of the dataset it was trained on; for an apples-to-apples comparison on identical images see docs/experiments/model_comparison.md (python -m pipeline.compare_models)."
      />
      <ErrorNotice error={error ?? activateError} />
      {loading ? (
        <Skeleton className="h-40" />
      ) : data && data.length ? (
        <div className="flex flex-col gap-6">
          <div className="grid gap-4 md:grid-cols-2">
            {Object.entries(groups).map(([name, versions]) => (
              <Panel key={name} title={name} index={name.endsWith('cnn') ? 'CNN' : 'RF'}>
                <ul className="flex flex-col gap-2">
                  {versions.map((v) => (
                    <li key={v.id}>
                      <div className={cx('flex flex-wrap items-center justify-between gap-3 rounded-xs border p-3 transition-colors', selected === v.id ? 'border-accent bg-accent/5' : 'border-line hover:border-line-strong')}>
                        <button type="button" onClick={() => setSelected(v.id)} className="flex min-w-0 flex-1 flex-col text-left" aria-pressed={selected === v.id}>
                          <span className="flex items-center gap-2 font-mono text-sm text-ink">
                            v{v.version} {v.is_active && <StatusBadge tone="ok" icon={CheckCircle2}>Active</StatusBadge>}
                          </span>
                          <span className="font-mono text-[11px] text-ink-3">acc {pct(v.accuracy, 2)} · F1 {num(v.f1, 4)} · AUC {num(v.roc_auc, 4)} · {dateTime(v.trained_at)}</span>
                        </button>
                        {can('models:manage') && !v.is_active && (
                          <Button size="sm" icon={Power} onClick={() => activate(v.id)}>
                            Activate
                          </Button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </Panel>
            ))}
          </div>
          {selected && <ModelDetailView id={selected} />}
        </div>
      ) : (
        <EmptyState icon={BrainCircuit} title="No models registered">
          Train with <code className="font-mono text-accent">python -m pipeline.train_model --model all</code>, then restart the API (or run <code className="font-mono">python -m app.cli sync-models</code>).
        </EmptyState>
      )}
    </div>
  )
}
