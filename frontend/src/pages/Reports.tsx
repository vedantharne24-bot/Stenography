import { Download, FileText, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, EmptyState, ErrorNotice, Hash, PageHeader, Panel, RiskBadge, Skeleton, TechniqueChip } from '../components/ui'
import { api, apiBlob, type ApiError } from '../lib/api'
import { dateTime } from '../lib/format'
import { saveBlob, useApi } from '../lib/hooks'
import type { Page, RiskLevel } from '../lib/types'

interface ReportRow {
  id: string
  title: string
  analysis_id: string | null
  sha256: string
  summary: { prediction: string; risk_score: number; risk_level: RiskLevel; technique: string; model_version: string; attacks_included: number; findings_included: number; filename: string }
  created_at: string
}

interface AnalysisRow {
  id: string
  filename: string
  prediction: string
  technique: string
  risk_score: number
  risk_level: RiskLevel
  source: string
  created_at: string
}

export default function Reports() {
  const reports = useApi<Page<ReportRow>>('/api/reports?page_size=50')
  const analyses = useApi<Page<AnalysisRow>>('/api/history?kind=analysis&page_size=8')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  const generate = async (analysisId: string) => {
    setBusy(analysisId)
    setError(null)
    try {
      await api(`/api/reports/${analysisId}`, { method: 'POST' })
      reports.reload()
    } catch (err) {
      setError(err as ApiError)
    } finally {
      setBusy(null)
    }
  }
  const download = async (r: ReportRow) => {
    const blob = await apiBlob(`/api/reports/${r.id}/download`)
    saveBlob(blob, `stegolab-report-${r.id.slice(0, 8)}.pdf`)
  }
  const remove = async (r: ReportRow) => {
    if (!window.confirm('Delete this report permanently?')) return
    await api(`/api/reports/${r.id}`, { method: 'DELETE' })
    reports.reload()
  }

  return (
    <div>
      <PageHeader index="08" kicker="Evidence · documentation" title="Reports" description="Downloadable PDF security reports assembled from stored analysis records, forensic findings, attack experiments on the same file hash and the model registry. Each report's SHA-256 is recorded for chain-of-custody." />
      <ErrorNotice error={error ?? reports.error} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Panel title="Generated reports" index="01">
          {reports.loading ? (
            <Skeleton className="h-40" />
          ) : reports.data?.items.length ? (
            <ul className="flex flex-col">
              {reports.data.items.map((r) => (
                <li key={r.id} className="flex flex-col gap-3 border-b border-line py-4 last:border-0 md:flex-row md:items-center">
                  <FileText className="hidden size-8 shrink-0 text-ink-4 md:block" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">{r.title}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-3">
                      <RiskBadge level={r.summary.risk_level} score={r.summary.risk_score} />
                      <TechniqueChip technique={r.summary.technique} />
                      <span className="font-mono text-[11px] text-ink-3">model v{r.summary.model_version} · {r.summary.findings_included} findings · {r.summary.attacks_included} attacks · {dateTime(r.created_at)}</span>
                    </div>
                    <div className="mt-2"><Hash label="PDF SHA-256" value={r.sha256} /></div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button size="sm" variant="primary" icon={Download} onClick={() => download(r)}>PDF</Button>
                    <Button size="sm" variant="danger" icon={Trash2} onClick={() => remove(r)} aria-label="Delete report" />
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState icon={FileText} title="No reports yet">Generate one from a recent analysis on the right, or from the Steganalysis result page.</EmptyState>
          )}
        </Panel>
        <Panel title="Recent analyses" index="02">
          {analyses.loading ? (
            <Skeleton className="h-40" />
          ) : analyses.data?.items.length ? (
            <ul className="flex flex-col">
              {analyses.data.items.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 border-b border-line py-2.5 last:border-0">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-ink" title={a.filename}>{a.filename}</p>
                    <p className="font-mono text-[11px] text-ink-3">{a.source} · {a.prediction} · {dateTime(a.created_at)}</p>
                  </div>
                  <Button size="sm" icon={FileText} loading={busy === a.id} onClick={() => generate(a.id)}>Report</Button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No analyses">Run <Link to="/steganalysis" className="text-accent">Steganalysis</Link> or <Link to="/forensics" className="text-accent">Forensics</Link> first.</EmptyState>
          )}
        </Panel>
      </div>
    </div>
  )
}
