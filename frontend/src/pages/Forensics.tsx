import { motion } from 'framer-motion'
import { AlertTriangle, Info, Microscope, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Explainability, ProbabilityPanels, RiskBreakdown, Verdict } from '../components/AnalysisView'
import { ArtifactImage } from '../components/ArtifactImage'
import { BarList, ChartTooltip, VIZ, axisProps } from '../components/charts'
import { Dropzone } from '../components/Dropzone'
import { TerminalLog } from '../components/TerminalLog'
import { Button, ErrorNotice, Hash, KeyValue, PageHeader, Panel, Segmented, StatusBadge, cx } from '../components/ui'
import { bytes, num, pct } from '../lib/format'
import { useOperation } from '../lib/hooks'
import type { ForensicResult } from '../lib/types'

const CHANNEL_STROKE: Record<'R' | 'G' | 'B', string> = { R: '#e66767', G: '#0ca30c', B: '#3987e5' }

function Histogram({ channel, values }: { channel: 'R' | 'G' | 'B'; values: number[] }) {
  const data = values.map((count, level) => ({ level, count }))
  return (
    <div>
      <p className="label-mono mb-1">Channel {channel}</p>
      <div className="h-28">
        <ResponsiveContainer>
          <AreaChart data={data} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
            <XAxis dataKey="level" hide />
            <YAxis hide />
            <Tooltip content={<ChartTooltip />} labelFormatter={(l) => `level ${l}`} />
            <Area type="stepAfter" dataKey="count" name={`${channel} pixels`} stroke={CHANNEL_STROKE[channel]} strokeWidth={1.5} fill={CHANNEL_STROKE[channel]} fillOpacity={0.12} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function Finding({ f }: { f: ForensicResult['findings'][number] }) {
  const tone = f.severity === 'high' ? 'critical' : f.severity === 'medium' ? 'warn' : 'neutral'
  const Icon = f.severity === 'high' ? ShieldAlert : f.severity === 'medium' ? AlertTriangle : Info
  return (
    <li className="flex gap-3 border-b border-line py-3 last:border-0">
      <StatusBadge tone={tone} icon={Icon} className="h-fit shrink-0">
        {f.severity}
      </StatusBadge>
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink">{f.title}</p>
        <p className="mt-0.5 text-sm text-ink-2">{f.detail}</p>
      </div>
    </li>
  )
}

export default function Forensics() {
  const [file, setFile] = useState<File | null>(null)
  const op = useOperation<ForensicResult>('/api/forensics/analyze')
  const [dctPos, setDctPos] = useState<'12' | '22'>('22')
  const [visual, setVisual] = useState<'lsb_plane' | 'noise_residual'>('lsb_plane')

  const run = () => {
    if (!file) return
    const form = new FormData()
    form.append('image', file)
    op.run(form)
  }
  const r = op.result

  return (
    <div>
      <PageHeader
        index="05"
        kicker="Investigation · digital forensics"
        title="Forensics"
        description="A full evidence workup: metadata, hashes, entropy, histograms, statistical LSB attacks, transform-domain diagnostics and visual attacks, combined with the AI verdict. Findings state what evidence is consistent with — never more."
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <Panel title="Exhibit" index="01" brackets>
          <Dropzone file={file} onFile={setFile} label="Drop an image for forensic analysis" />
          <div className="mt-4 flex justify-end">
            <Button variant="primary" size="lg" icon={Microscope} onClick={run} disabled={!file || op.status === 'running'} loading={op.status === 'running'}>
              Run forensic analysis
            </Button>
          </div>
        </Panel>
        <div className="flex flex-col gap-4">
          <TerminalLog events={op.events} status={op.status} upload={op.upload} title="forensics.log" />
          <ErrorNotice error={op.error} title="Forensic analysis failed" />
        </div>
      </div>

      {r && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mt-8 flex flex-col gap-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="File & metadata" index="F1">
              <KeyValue
                rows={[
                  ['Name', <span className="break-all">{r.file.filename}</span>],
                  ['Format / mode', `${r.file.format.toUpperCase()} · ${r.file.mode}`],
                  ['Dimensions', `${r.file.width} × ${r.file.height} (${num(r.file.megapixels, 2)} MP)`],
                  ['File size', bytes(r.file.file_size)],
                  ['EXIF tags', String((r.metadata.exif_tag_count as number | undefined) ?? 0)],
                  ...(Object.entries(r.metadata.exif ?? {}).map(([k, v]) => [`EXIF ${k}`, v]) as [string, string][]),
                  ['ICC profile', r.metadata.icc_profile ?? 'none'],
                  ...(r.metadata.jpeg_quality_estimate ? ([['JPEG quality (est.)', `≈ ${r.metadata.jpeg_quality_estimate}`]] as [string, string][]) : []),
                  ...(r.metadata.text_chunks?.length ? ([['PNG text chunks', r.metadata.text_chunks.join(', ')]] as [string, string][]) : []),
                ]}
              />
              <div className="mt-4 border-t border-line pt-3">
                <Hash label="SHA-256" value={r.file.sha256} truncate={false} />
              </div>
            </Panel>
            <Panel title="Findings" index="F2">
              <ul>{r.findings.map((f, i) => <Finding key={i} f={f} />)}</ul>
              <p className="mt-3 border-t border-line pt-3 text-xs text-ink-3">{r.disclaimer}</p>
            </Panel>
          </div>

          <Verdict result={r.ai} />
          <ProbabilityPanels result={r.ai} />

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
            <Panel title="RGB histograms" index="F3" actions={<span className="font-mono text-[11px] text-ink-3">luma entropy {num(r.entropy.luma_bits, 3)} bits</span>}>
              <div className="grid gap-4 sm:grid-cols-3">
                {(['R', 'G', 'B'] as const).map((c) => (
                  <Histogram key={c} channel={c} values={r.histograms[c]} />
                ))}
              </div>
              <p className="mt-3 text-xs text-ink-3">LSB replacement equalises adjacent histogram bins (2k, 2k+1); a comb-free, flattened fine structure is a classic indicator.</p>
            </Panel>
            <Panel title="Pixel statistics" index="F4">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[360px] text-sm">
                  <thead>
                    <tr className="text-left">
                      <th className="label-mono pb-2 font-normal">Stat</th>
                      {(['R', 'G', 'B'] as const).map((c) => <th key={c} className="label-mono pb-2 text-right font-normal">{c}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {(['mean', 'std', 'min', 'max', 'skewness', 'kurtosis', 'saturated_fraction', 'entropy_bits'] as const).map((k) => (
                      <tr key={k} className="border-t border-line">
                        <td className="py-1.5 font-mono text-xs text-ink-3">{k.replace('_', ' ')}</td>
                        {(['R', 'G', 'B'] as const).map((c) => (
                          <td key={c} className="py-1.5 text-right font-mono text-xs tabular">{k === 'saturated_fraction' ? pct(r.pixel_stats[c][k], 2) : num(r.pixel_stats[c][k], k === 'min' || k === 'max' ? 0 : 3)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="LSB statistical attacks" index="F5">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[360px] text-sm">
                  <thead>
                    <tr className="text-left">
                      <th className="label-mono pb-2 font-normal">Test</th>
                      {(['R', 'G', 'B'] as const).map((c) => <th key={c} className="label-mono pb-2 text-right font-normal">{c}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {(
                      [
                        ['chi_square_embedding_probability', 'χ² attack P(embed)', (v: number) => num(v, 3)],
                        ['spa_estimate', 'SPA embedding rate', (v: number) => num(v, 4)],
                        ['pair_asymmetry', 'Pair asymmetry', (v: number) => num(v, 4)],
                        ['ones_fraction', 'LSB ones fraction', (v: number) => pct(v, 2)],
                        ['lsb_horizontal_correlation', 'LSB-plane correlation', (v: number) => num(v, 4)],
                      ] as const
                    ).map(([key, label, fmt]) => (
                      <tr key={key} className="border-t border-line">
                        <td className="py-1.5 text-xs text-ink-2">{label}</td>
                        {(['R', 'G', 'B'] as const).map((c) => {
                          const v = r.lsb_analysis[c][key]
                          const hot = (key === 'chi_square_embedding_probability' && v > 0.95) || (key === 'spa_estimate' && v > 0.05)
                          return <td key={c} className={cx('py-1.5 text-right font-mono text-xs tabular', hot ? 'text-serious' : 'text-ink')}>{fmt(v)}</td>
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-xs text-ink-3">Westfeld–Pfitzmann χ² attack and Dumitrescu–Wu–Wang Sample Pairs Analysis. Values above thresholds are highlighted (and labelled in findings).</p>
            </Panel>
            <Panel title="Visual attacks" index="F6" actions={<Segmented label="Visual attack" size="sm" value={visual} onChange={setVisual} options={[{ value: 'lsb_plane', label: 'LSB plane' }, { value: 'noise_residual', label: 'Noise residual' }]} />}>
              <ArtifactImage id={r.artifacts[visual]} alt={visual === 'lsb_plane' ? 'LSB bit-plane of R, G, B' : 'High-pass noise residual'} className="checker aspect-[4/3] w-full rounded-xs border border-line" pixelated />
              <p className="mt-2 text-xs text-ink-3">
                {visual === 'lsb_plane'
                  ? 'Bit 0 of each channel ×255. Natural smooth regions keep structure here; LSB embedding turns them into uniform noise.'
                  : 'KB high-pass residual (|r|, scaled to the 99.5th percentile): removes content to expose the noise layer where payloads live.'}
              </p>
            </Panel>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="Block-DCT statistics" index="F7" actions={<Segmented label="DCT coefficient" size="sm" value={dctPos} onChange={setDctPos} options={[{ value: '12', label: '(1,2)' }, { value: '22', label: '(2,2)' }]} />}>
              <p className="label-mono mb-2">Coefficient histogram, {r.dct_stats.blocks.toLocaleString()} blocks</p>
              <div className="h-40">
                <ResponsiveContainer>
                  <BarChart data={r.dct_stats.coefficient_histograms.positions[dctPos].map((count, i) => ({ v: i - 40, count }))} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap={1}>
                    <CartesianGrid stroke={VIZ.grid} vertical={false} />
                    <XAxis dataKey="v" {...axisProps} interval={9} />
                    <YAxis {...axisProps} width={36} />
                    <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }} content={<ChartTooltip />} labelFormatter={(v) => `coefficient ≈ ${v}`} />
                    <Bar dataKey="count" name="Blocks" fill={VIZ.measure} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-4">
                <p className="label-mono mb-2">Histogram periodicity by frequency (top 6)</p>
                <BarList
                  rows={Object.entries(r.dct_stats.periodicity)
                    .sort((a, b) => b[1].score - a[1].score)
                    .slice(0, 6)
                    .map(([pos, v]) => ({ label: `(${pos[0]},${pos[1]}) · period ${num(v.period, 1)}`, value: v.score }))}
                  max={Math.max(8, r.dct_stats.max_periodicity)}
                  format={(v) => num(v, 2)}
                />
                <p className="mt-2 font-mono text-[11px] text-ink-3">blockiness ratio {num(r.dct_stats.blockiness, 3)} · scores ≳ 6 indicate a quantisation lattice</p>
              </div>
            </Panel>
            <Panel title="Wavelet subbands (Haar)" index="F8">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left">
                    <th className="label-mono pb-2 font-normal">Band</th>
                    <th className="label-mono pb-2 text-right font-normal">mean |c|</th>
                    <th className="label-mono pb-2 text-right font-normal">std</th>
                    <th className="label-mono pb-2 text-right font-normal">periodicity</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(r.dwt_stats).map(([band, s]) => (
                    <tr key={band} className="border-t border-line">
                      <td className="py-1.5 font-mono text-xs text-ink-2">{band}</td>
                      <td className="py-1.5 text-right font-mono text-xs tabular">{num(s.mean_abs, 3)}</td>
                      <td className="py-1.5 text-right font-mono text-xs tabular">{num(s.std, 3)}</td>
                      <td className={cx('py-1.5 text-right font-mono text-xs tabular', s.periodicity > 6 ? 'text-serious' : 'text-ink')}>{num(s.periodicity, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>

          <Explainability result={r.ai} artifacts={{ preview: r.artifacts.preview, heatmap: r.artifacts.heatmap, overlay: r.artifacts.overlay }} width={r.file.width} height={r.file.height} />
          <RiskBreakdown result={r.ai} />
        </motion.div>
      )}
    </div>
  )
}
