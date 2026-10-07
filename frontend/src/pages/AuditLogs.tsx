import { ChevronLeft, ChevronRight, RefreshCw, ScrollText } from 'lucide-react'
import { Fragment, useEffect, useState } from 'react'
import { Button, EmptyState, ErrorNotice, Input, PageHeader, Panel, Select, Skeleton, StatusBadge } from '../components/ui'
import { dateTime } from '../lib/format'
import { useApi } from '../lib/hooks'

interface AuditRow {
  id: number
  timestamp: string
  user: string | null
  action: string
  result: 'success' | 'failure' | 'denied'
  ip: string | null
  metadata: Record<string, unknown>
}

const PAGE_SIZE = 40

export default function AuditLogs() {
  const [action, setAction] = useState('')
  const [result, setResult] = useState('')
  const [userQuery, setUserQuery] = useState('')
  const [applied, setApplied] = useState('')
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState<number | null>(null)
  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE), ...(action ? { action } : {}), ...(result ? { result } : {}), ...(applied ? { user_query: applied } : {}) })
  const { data, error, loading, reload } = useApi<{ items: AuditRow[]; total: number; actions: string[] }>(`/api/audit-logs?${params}`)
  useEffect(() => setPage(1), [action, result, applied])
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <div>
      <PageHeader
        index="11"
        kicker="Security · append-only trail"
        title="Audit Logs"
        description="Security-sensitive events recorded server-side. Metadata is scrubbed of secrets before it is written — passwords, keys and messages never appear here."
        actions={<Button variant="ghost" icon={RefreshCw} onClick={reload} loading={loading}>Refresh</Button>}
      />
      <div className="mb-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,180px)_minmax(0,1fr)_auto]">
        <Select aria-label="Filter by action" value={action} onChange={(e) => setAction(e.target.value)}>
          <option value="">All actions</option>
          {data?.actions.map((a) => <option key={a} value={a}>{a}</option>)}
        </Select>
        <Select aria-label="Filter by result" value={result} onChange={(e) => setResult(e.target.value)}>
          <option value="">Any result</option>
          <option value="success">success</option>
          <option value="failure">failure</option>
          <option value="denied">denied</option>
        </Select>
        <Input aria-label="Filter by user email" placeholder="User email contains…" value={userQuery} onChange={(e) => setUserQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && setApplied(userQuery.trim())} />
        <Button onClick={() => setApplied(userQuery.trim())}>Apply</Button>
      </div>
      <ErrorNotice error={error} />
      <Panel bodyClassName="p-0">
        {loading && !data ? (
          <div className="p-4"><Skeleton className="h-72" /></div>
        ) : data?.items.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="border-b border-line">
                <tr className="text-left">{['#', 'Timestamp', 'User', 'Action', 'Result', 'IP', 'Metadata'].map((h) => <th key={h} className="label-mono px-4 py-3 font-normal">{h}</th>)}</tr>
              </thead>
              <tbody className="font-mono text-xs">
                {data.items.map((row) => (
                  <Fragment key={row.id}>
                    <tr className="cursor-pointer border-b border-line/70 hover:bg-raised/50" onClick={() => setExpanded(expanded === row.id ? null : row.id)}>
                      <td className="px-4 py-2 text-ink-4">{row.id}</td>
                      <td className="px-4 py-2 whitespace-nowrap text-ink-3">{dateTime(row.timestamp)}</td>
                      <td className="max-w-48 truncate px-4 py-2 text-ink-2">{row.user ?? 'anonymous'}</td>
                      <td className="px-4 py-2 text-ink">{row.action}</td>
                      <td className="px-4 py-2"><StatusBadge tone={row.result === 'success' ? 'ok' : row.result === 'denied' ? 'serious' : 'critical'}>{row.result}</StatusBadge></td>
                      <td className="px-4 py-2 text-ink-3">{row.ip ?? '—'}</td>
                      <td className="max-w-72 truncate px-4 py-2 text-ink-3">{Object.keys(row.metadata ?? {}).length ? JSON.stringify(row.metadata) : '—'}</td>
                    </tr>
                    {expanded === row.id && (
                      <tr className="border-b border-line bg-bg">
                        <td colSpan={7} className="px-4 py-3">
                          <pre className="overflow-x-auto whitespace-pre-wrap text-ink-2">{JSON.stringify(row.metadata, null, 2)}</pre>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon={ScrollText} title="No matching events" />
        )}
        {data && data.total > PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-line px-4 py-3">
            <span className="font-mono text-xs text-ink-3">{data.total.toLocaleString()} events · page {page} / {pages}</span>
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
