/* Shared presentation of an AI steganalysis result (used by Steganalysis and Forensics). */
import { motion } from 'framer-motion'
import { BrainCircuit, Fingerprint, Info } from 'lucide-react'
import { useState } from 'react'
import { pct } from '../lib/format'
import { useArtifactUrl } from '../lib/hooks'
import type { AnalysisResult, TileProbability } from '../lib/types'
import { ArtifactImage } from './ArtifactImage'
import { BarList, ProbabilityBars, VIZ } from './charts'
import { RiskGauge } from './RiskGauge'
import { KeyValue, Panel, Segmented, Skeleton, StatusBadge, TechniqueChip, cx } from './ui'

type AiResult = Omit<AnalysisResult, 'analysis_id' | 'image' | 'artifacts' | 'created_at' | 'duration_ms'>

export function Verdict({ result }: { result: AiResult }) {
  const stego = result.prediction === 'stego'
  return (
    <Panel title="AI verdict" index="A" brackets actions={<span className="font-mono text-[11px] text-ink-3">{result.model.name} v{result.model.version}</span>}>
      <div className="grid items-center gap-6 md:grid-cols-[minmax(0,1fr)_auto]">
        <div>
          <p className="label-mono">Classification</p>
          <motion.p initial={{ opacity: 0, letterSpacing: '0.4em' }} animate={{ opacity: 1, letterSpacing: '0.06em' }} transition={{ duration: 0.6 }} className={cx('font-display text-6xl font-extrabold uppercase md:text-7xl', stego ? 'text-ink' : 'text-ink-2')}>
            {stego ? 'Stego' : 'Cover'}
          </motion.p>
          <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2">
            <span className="text-sm text-ink-2">
              P(stego) <span className="font-mono text-ink tabular">{pct(result.p_stego, 1)}</span>
            </span>
            <span className="flex items-center gap-2 text-sm text-ink-2">
              Technique <TechniqueChip technique={result.predicted_technique} />
            </span>
            <span className="text-sm text-ink-2">
              Confidence <span className="font-mono text-ink tabular">{pct(result.confidence, 1)}</span>
            </span>
            {result.technique_confidence !== null && (
              <span className="text-sm text-ink-2">
                P(technique | stego) <span className="font-mono text-ink tabular">{pct(result.technique_confidence, 1)}</span>
              </span>
            )}
          </div>
          {result.signature && (
            <div className="mt-4 flex flex-col gap-2">
              <StatusBadge tone="critical" icon={Fingerprint} className="self-start">
                StegoLab {result.signature.algorithm} frame present · {result.signature.integrity}
              </StatusBadge>
              {result.prediction === 'cover' && (
                <p className="max-w-xl text-xs leading-relaxed text-ink-3">
                  The statistical detectors did not flag this image — the payload is too small relative to the image for its noise to be measurable. The
                  risk score comes from the frame header that is physically present and decodable, which is independent evidence.
                </p>
              )}
            </div>
          )}
          <p className="mt-4 max-w-xl text-sm leading-relaxed text-ink-2">{result.risk.recommendation}</p>
        </div>
        <RiskGauge score={result.risk.score} level={result.risk.level} />
      </div>
    </Panel>
  )
}

export function ProbabilityPanels({ result }: { result: AiResult }) {
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Panel title="StegoNet · CNN probabilities" index="B" actions={<BrainCircuit className="size-4 text-ink-4" aria-hidden />}>
        <ProbabilityBars probs={result.probabilities} highlight={result.predicted_technique} />
        <p className="mt-4 text-xs text-ink-3">Mean softmax over {result.tiles.length} grid-aligned tile(s). Decision rule: arg-max class (identical to the evaluated test metric).</p>
      </Panel>
      <Panel title="Random Forest · handcrafted features" index="C">
        {result.rf ? (
          <>
            <ProbabilityBars probs={result.rf.probabilities} />
            <div className="mt-4 grid grid-cols-2 gap-3 border-t border-line pt-3">
              <div>
                <p className="label-mono">Anomaly percentile</p>
                <p className="font-mono text-lg text-ink tabular">{pct(result.rf.anomaly, 1)}</p>
              </div>
              <div>
                <p className="label-mono">CNN ↔ RF</p>
                <p className="font-mono text-lg text-ink">{result.risk.agreement === 'agree' ? 'Agree' : result.risk.agreement === 'disagree' ? 'Disagree' : '—'}</p>
              </div>
            </div>
          </>
        ) : (
          <p className="text-sm text-ink-3">Random Forest model not trained.</p>
        )}
      </Panel>
    </div>
  )
}

export function RiskBreakdown({ result }: { result: AiResult }) {
  const factors = result.risk.factors
  return (
    <Panel title="Risk score derivation" index="E" actions={<span className="font-mono text-[11px] text-ink-3">{result.risk.formula}</span>}>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-left">
            <th className="label-mono pb-2 font-normal">Factor</th>
            <th className="label-mono pb-2 text-right font-normal">Value</th>
            <th className="label-mono pb-2 text-right font-normal">Weight</th>
            <th className="label-mono pb-2 text-right font-normal">Points</th>
          </tr>
        </thead>
        <tbody>
          {factors.map((f) => (
            <tr key={f.key} className="border-b border-line/60">
              <td className="py-2 text-ink-2">{f.label}</td>
              <td className="py-2 text-right font-mono text-ink tabular">{typeof f.value === 'number' ? pct(f.value) : f.value ? String(f.value).toUpperCase() : 'none'}</td>
              <td className="py-2 text-right font-mono text-ink-3 tabular">{f.effective_weight === null ? 'floor' : f.effective_weight ? f.effective_weight.toFixed(2) : '—'}</td>
              <td className="py-2 text-right font-mono text-ink tabular">{f.contribution.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 flex gap-2 text-xs text-ink-3">
        <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        Weighted evidence = {(result.risk.evidence * 100).toFixed(1)}; payload floor = {(result.risk.floor * 100).toFixed(0)}. Score is the larger of the two. Thresholds are set by an administrator.
      </p>
    </Panel>
  )
}

/** Tile-level P(stego) drawn over the preview (coordinates in source-image pixels). */
function TileOverlay({ tiles, width, height }: { tiles: TileProbability[]; width: number; height: number }) {
  return (
    <div className="pointer-events-none absolute inset-0">
      {tiles.map((t, i) => (
        <div
          key={i}
          className="absolute border border-bg/40"
          style={{
            left: `${(t.x / width) * 100}%`,
            top: `${(t.y / height) * 100}%`,
            width: `${(t.w / width) * 100}%`,
            height: `${(t.h / height) * 100}%`,
            background: `color-mix(in oklab, var(--color-critical) ${Math.round(t.p_stego * 55)}%, transparent)`,
          }}
          title={`P(stego) ${pct(t.p_stego)}`}
        />
      ))}
    </div>
  )
}

export function Explainability({ result, artifacts, width, height }: { result: AiResult; artifacts: { preview?: string; heatmap?: string; overlay?: string }; width: number; height: number }) {
  const [view, setView] = useState<'overlay' | 'heatmap' | 'tiles'>('overlay')
  const preview = useArtifactUrl(artifacts.preview)
  const exp = result.explanation
  return (
    <Panel title="Explainable AI" index="D" actions={exp && <span className="font-mono text-[11px] text-ink-3">Grad-CAM → {exp.target_class.toUpperCase()}</span>}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <Segmented
          label="Explanation view"
          size="sm"
          value={view}
          onChange={setView}
          options={[
            { value: 'overlay', label: 'Overlay', disabled: !artifacts.overlay },
            { value: 'heatmap', label: 'Heat-map', disabled: !artifacts.heatmap },
            { value: 'tiles', label: 'Tile P(stego)' },
          ]}
        />
      </div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="checker relative overflow-hidden rounded-xs border border-line">
          {view === 'tiles' ? (
            preview.url ? (
              <div className="relative">
                <img src={preview.url} alt="Analysed image" className="block w-full" />
                <TileOverlay tiles={result.tiles} width={width} height={height} />
              </div>
            ) : (
              <Skeleton className="aspect-[4/3] w-full" />
            )
          ) : (
            <ArtifactImage id={view === 'overlay' ? artifacts.overlay : artifacts.heatmap} alt={`Grad-CAM ${view}`} className="block aspect-[4/3] w-full" />
          )}
        </div>
        <div className="flex flex-col gap-4">
          {exp ? (
            <>
              <div>
                <p className="label-mono mb-2">Evidence share by analysis domain</p>
                <BarList
                  rows={[
                    { label: 'Spatial residuals (SRM)', value: exp.branch_share.spatial },
                    { label: 'Block-DCT histogram', value: exp.branch_share.dct },
                    { label: 'Wavelet histogram', value: exp.branch_share.dwt },
                  ]}
                  color={VIZ.measure}
                />
              </div>
              <p className="text-xs leading-relaxed text-ink-3">{exp.note}</p>
            </>
          ) : (
            <p className="text-sm text-ink-3">Explanation was not requested for this run.</p>
          )}
          {result.rf?.top_features && result.rf.top_features.length > 0 && (
            <div className="border-t border-line pt-3">
              <p className="label-mono mb-2">Strongest handcrafted signals (z vs clean covers)</p>
              <ul className="flex flex-col gap-1">
                {result.rf.top_features.slice(0, 6).map((f) => (
                  <li key={f.feature} className="flex justify-between gap-2 font-mono text-[11px]">
                    <span className="truncate text-ink-2">{f.feature}</span>
                    <span className={cx('tabular', Math.abs(f.z_vs_covers) > 2 ? 'text-ink' : 'text-ink-3')}>{f.z_vs_covers > 0 ? '+' : ''}{f.z_vs_covers.toFixed(2)}σ</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <KeyValue rows={Object.entries(result.timings_ms).map(([k, v]) => [k, `${v.toFixed(0)} ms`] as [string, string])} />
        </div>
      </div>
    </Panel>
  )
}
