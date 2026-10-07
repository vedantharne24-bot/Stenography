export const pct = (value: number | null | undefined, digits = 1): string =>
  value === null || value === undefined || Number.isNaN(value) ? '—' : `${(value * 100).toFixed(digits)}%`

export const num = (value: number | null | undefined, digits = 2): string =>
  value === null || value === undefined || Number.isNaN(value) ? '—' : value.toFixed(digits)

export const int = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : Math.round(value).toLocaleString('en-US')

export function bytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value < 1024) return `${Math.round(value)} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

export function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value.toFixed(0)} ms`
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-GB', { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export function timeOfDay(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-GB', { hour12: false })
}

export function shortHash(hash: string | null | undefined, n = 12): string {
  return hash ? `${hash.slice(0, n)}…${hash.slice(-4)}` : '—'
}

export function relative(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return `${Math.max(1, Math.round(diff))}s ago`
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  return `${Math.round(diff / 86400)}d ago`
}
