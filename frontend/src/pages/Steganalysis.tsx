import { AnimatePresence, motion } from 'framer-motion'
import { FileText, ScanSearch } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Explainability, ProbabilityPanels, RiskBreakdown, Verdict } from '../components/AnalysisView'
import { Dropzone } from '../components/Dropzone'
import { TerminalLog } from '../components/TerminalLog'
import { Button, ErrorNotice, Hash, PageHeader, Panel, StatusBadge } from '../components/ui'
import { api, type ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { bytes } from '../lib/format'
import { useOperation } from '../lib/hooks'
import type { AnalysisResult } from '../lib/types'

/** Scan beam over the selected image, active only while the backend is actually working. */
function ScanPreview({ file, scanning }: { file: File; scanning: boolean }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    const u = URL.createObjectURL(file)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [file])
  if (!url) return null
  return (
    <div className="checker relative overflow-hidden rounded-xs border border-line">
      <img src={url} alt="Image under analysis" className="block max-h-80 w-full object-contain" />
      <AnimatePresence>
        {scanning && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="pointer-events-none absolute inset-0">
            <div className="absolute inset-0 bg-accent/5" />
            <div className="absolute inset-x-0 h-full animate-scan">
              <div className="h-20 bg-gradient-to-b from-transparent to-accent/25" />
              <div className="h-0.5 bg-accent shadow-[0_0_18px_var(--color-accent)]" />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default function Steganalysis() {
  const { can } = useAuth()
  const [file, setFile] = useState<File | null>(null)
  const [explain, setExplain] = useState(true)
  const op = useOperation<AnalysisResult>('/api/steganalysis/analyze')
  const [reportState, setReportState] = useState<'idle' | 'busy' | 'done'>('idle')
  const [reportError, setReportError] = useState<ApiError | null>(null)

  const run = () => {
    if (!file) return
    const form = new FormData()
    form.append('image', file)
    form.append('explain', String(explain))
    setReportState('idle')
    op.run(form)
  }

  const makeReport = async () => {
    if (!op.result) return
    setReportState('busy')
    setReportError(null)
    try {
      await api(`/api/reports/${op.result.analysis_id}`, { method: 'POST' })
      setReportState('done')
    } catch (err) {
      setReportError(err as ApiError)
      setReportState('idle')
    }
  }

  const r = op.result
  return (
    <div>
      <PageHeader
        index="04"
        kicker="Detection · AI steganalysis"
        title="Steganalysis"
        description="Classify an image as cover or stego and identify the likely technique (LSB / DCT / DWT) with the trained StegoNet CNN, corroborated by a Random Forest on handcrafted features and a statistical anomaly model."
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <Panel title="Evidence image" index="01" brackets>
          {file ? <ScanPreview file={file} scanning={op.status === 'running'} /> : null}
          <div className={file ? 'mt-4' : ''}>
            <Dropzone file={file} onFile={setFile} compact={Boolean(file)} label="Drop an image to analyse" />
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
              <input type="checkbox" checked={explain} onChange={(e) => setExplain(e.target.checked)} className="size-4 accent-[var(--color-accent)]" />
              Generate Grad-CAM explanation
            </label>
            <Button variant="primary" size="lg" icon={ScanSearch} onClick={run} disabled={!file || op.status === 'running'} loading={op.status === 'running'}>
              Analyse
            </Button>
          </div>
        </Panel>
        <div className="flex flex-col gap-4">
          <TerminalLog events={op.events} status={op.status} upload={op.upload} title="steganalysis.log" idleText="Every step (model load, tiling, inference, Grad-CAM) is logged here by the backend in real time." />
          <ErrorNotice error={op.error} title={op.error?.code === 'model_unavailable' ? 'Model unavailable' : 'Analysis failed'} />
        </div>
      </div>

      {r && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mt-8 flex flex-col gap-6">
          <Verdict result={r} />
          <ProbabilityPanels result={r} />
          <Explainability result={r} artifacts={{ preview: r.artifacts.image_preview, heatmap: r.artifacts.heatmap, overlay: r.artifacts.overlay }} width={r.image.width} height={r.image.height} />
          <RiskBreakdown result={r} />
          <Panel title="Evidence record" index="F" actions={<StatusBadge tone="info">Stored · {r.analysis_id.slice(0, 8)}</StatusBadge>}>
            <div className="grid gap-3 text-sm md:grid-cols-2">
              <Hash label="SHA-256" value={r.image.sha256} />
              <span className="font-mono text-xs text-ink-3">
                {r.image.filename} · {r.image.format.toUpperCase()} · {r.image.width}×{r.image.height} · {bytes(r.image.file_size)}
              </span>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {can('reports:generate') && (
                <Button icon={FileText} onClick={makeReport} loading={reportState === 'busy'} disabled={reportState === 'done'}>
                  {reportState === 'done' ? 'Report generated' : 'Generate PDF report'}
                </Button>
              )}
              {reportState === 'done' && (
                <Link to="/reports" className="self-center text-sm text-accent hover:underline">
                  Open reports →
                </Link>
              )}
            </div>
            {reportError && <div className="mt-3"><ErrorNotice error={reportError} title="Report failed" /></div>}
          </Panel>
        </motion.div>
      )}
    </div>
  )
}
