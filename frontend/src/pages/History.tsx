import { ChevronLeft, ChevronRight, History as HistoryIcon, Search, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button, EmptyState, ErrorNotice, Input, IntegrityBadge, PageHeader, Panel, RiskBadge, Segmented, Skeleton, StatusBadge, TechniqueChip } from '../components/ui'
import { api, type ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { bytes, dateTime, ms, num, pct, shortHash } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { Page, RiskLevel } from '../lib/types'

type Kind = 'analysis' | 'operation' | 'attack'
type Row = Record<string, unknown> & { id: string; created_at: string }

const PAGE_SIZE = 15

export default function History() {
  const { can } = useAuth()
  const [kind, setKind] = useState<Kind>('analysis')
  const [page, setPage] = useState(1)
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [allUsers, setAllUsers] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const params = new URLSearchParams({ kind, page: String(page), page_size: String(PAGE_SIZE), ...(search ? { q: search } : {}), ...(allUsers ? { all_users: 'true' } : {}) })
  const { data, loading, error: loadError, reload } = useApi<Page<Row>>(`/api/history?${params}`)
  useEffect(() => setPage(1), [kind, search, allUsers])
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  const remove = async (row: Row) => {
    if (!window.confirm('Delete this record and its stored artefacts?')) return
    try {
      await api(`/api/history/${kind}/${row.id}`, { method: 'DELETE' })
      reload()
    } catch (err) {
      setError(err as ApiError)
    }
  }

  return (
    <div>
      <PageHeader index="09" kicker="Records · personal history" title="History" description="Every analysis, embedding/extraction and attack you have run, straight from the database. Deleting a record removes its stored artefacts; audit entries are retained." />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented label="Record type" value={kind} onChange={setKind} options={[{ value: 'analysis', label: 'Analyses' }, { value: 'operation', label: 'Stego operations' }, { value: 'attack', label: 'Attacks' }]} />
        <form
          className="relative min-w-56 flex-1 md:max-w-sm"
          onSubmit={(e) => {
            e.preventDefault()
            setSearch(query.trim())
          }}
        >
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-4" aria-hidden />
          <Input aria-label="Search history" placeholder="Search filename, hash, algorithm…" value={query} onChange={(e) => setQuery(e.target.value)} className="pl-9" />
        </form>
        {can('history:all') && (
          <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" checked={allUsers} onChange={(e) => setAllUsers(e.target.checked)} className="size-4 accent-[var(--color-accent)]" />
            All users (admin)
          </label>
        )}
      </div>
      <ErrorNotice error={error ?? loadError} />
      <Panel bodyClassName="p-0">
        {loading && !data ? (
          <div className="p-4"><Skeleton className="h-64" /></div>
        ) : data?.items.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-sm">
              <thead className="border-b border-line">
                {kind === 'analysis' && (
                  <tr className="text-left">{['When', 'File', 'Source', 'Verdict', 'Technique', 'Confidence', 'Risk', 'Model', ''].map((h) => <th key={h} className="label-mono px-4 py-3 font-normal">{h}</th>)}</tr>
                )}
                {kind === 'operation' && (
                  <tr className="text-left">{['When', 'Operation', 'Algorithm', 'Payload', 'Image', 'Utilisation', 'PSNR / SSIM', 'Status', ''].map((h) => <th key={h} className="label-mono px-4 py-3 font-normal">{h}</th>)}</tr>
                )}
                {kind === 'attack' && (
                  <tr className="text-left">{['When', 'File', 'Attack', 'Params', 'P(stego) before→after', 'Integrity', 'BER', 'PSNR', ''].map((h) => <th key={h} className="label-mono px-4 py-3 font-normal">{h}</th>)}</tr>
                )}
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id} className="border-b border-line/70 hover:bg-raised/50">
                    <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap text-ink-3">{dateTime(row.created_at)}</td>
                    {kind === 'analysis' && (
                      <>
                        <td className="max-w-52 truncate px-4 py-2.5" title={String(row.filename)}>{String(row.filename)}<span className="block font-mono text-[10px] text-ink-4">{shortHash(row.file_hash as string, 10)}</span></td>
                        <td className="px-4 py-2.5 font-mono text-xs text-ink-2">{String(row.source)}</td>
                        <td className="px-4 py-2.5"><StatusBadge tone={row.prediction === 'stego' ? 'serious' : 'neutral'} icon={null}>{String(row.prediction)}</StatusBadge></td>
                        <td className="px-4 py-2.5"><TechniqueChip technique={String(row.technique)} /></td>
                        <td className="px-4 py-2.5 font-mono tabular">{pct(row.confidence as number)}</td>
                        <td className="px-4 py-2.5"><RiskBadge level={row.risk_level as RiskLevel} score={row.risk_score as number} /></td>
                        <td className="px-4 py-2.5 font-mono text-xs text-ink-3">v{String(row.model_version)}</td>
                      </>
                    )}
                    {kind === 'operation' && (
                      <>
                        <td className="px-4 py-2.5 font-mono text-xs uppercase">{String(row.operation)}</td>
                        <td className="px-4 py-2.5"><TechniqueChip technique={String(row.algorithm)} /></td>
                        <td className="px-4 py-2.5 font-mono text-xs">{bytes(row.payload_size as number)} {String(row.payload_kind)}</td>
                        <td className="px-4 py-2.5 font-mono text-xs">{String(row.image)}</td>
                        <td className="px-4 py-2.5 font-mono tabular">{pct(row.utilization as number | null)}</td>
                        <td className="px-4 py-2.5 font-mono text-xs tabular">{num(row.psnr as number | null, 2)} / {num(row.ssim as number | null, 4)}</td>
                        <td className="px-4 py-2.5">{row.success ? <StatusBadge tone="ok">ok · {ms(row.duration_ms as number)}</StatusBadge> : <StatusBadge tone="critical">{String(row.error_code ?? 'failed')}</StatusBadge>}</td>
                      </>
                    )}
                    {kind === 'attack' && (
                      <>
                        <td className="max-w-40 truncate px-4 py-2.5" title={String(row.filename)}>{String(row.filename)}</td>
                        <td className="px-4 py-2.5 font-mono text-xs">{String(row.attack)}</td>
                        <td className="px-4 py-2.5 font-mono text-xs text-ink-2">{Object.entries((row.params as Record<string, number>) ?? {}).map(([k, v]) => `${k}=${v}`).join(', ')}</td>
                        <td className="px-4 py-2.5 font-mono tabular">{pct(row.detection_before as number)} → {pct(row.detection_after as number)}</td>
                        <td className="px-4 py-2.5"><IntegrityBadge status={String(row.integrity)} /></td>
                        <td className="px-4 py-2.5 font-mono tabular">{row.ber === null ? '—' : pct(row.ber as number, 2)}</td>
                        <td className="px-4 py-2.5 font-mono tabular">{num(row.psnr as number | null, 2)}</td>
                      </>
                    )}
                    <td className="px-4 py-2.5 text-right">
                      {!allUsers && (
                        <button type="button" onClick={() => remove(row)} className="rounded-xs p-1.5 text-ink-4 hover:bg-critical/10 hover:text-critical-ink" aria-label="Delete record">
                          <Trash2 className="size-4" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon={HistoryIcon} title="No records">{search ? 'No match for this search.' : 'Records appear here as you use the modules.'}</EmptyState>
        )}
        {data && data.total > PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-line px-4 py-3">
            <span className="font-mono text-xs text-ink-3">{data.total} records · page {page} / {pages}</span>
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" icon={ChevronLeft} disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Prev</Button>
              <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Next <ChevronRight className="size-4" /></Button>
            </div>
          </div>
        )}
      </Panel>
    </div>
  )
}
