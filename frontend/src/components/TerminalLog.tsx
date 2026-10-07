import { motion } from 'framer-motion'
import { Terminal } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { timeOfDay } from '../lib/format'
import type { OperationStatus } from '../lib/hooks'
import type { TraceEvent } from '../lib/types'
import { cx } from './ui'

const LEVEL_CLASS: Record<string, string> = {
  info: 'text-ink-2',
  warn: 'text-warn',
  error: 'text-critical-ink',
}

/** Console of *real* backend events (streamed as they happen, with server timestamps). */
export function TerminalLog({
  events,
  status,
  title = 'operation.log',
  idleText = 'Awaiting operation…',
  className,
  maxHeight = 'max-h-80',
  upload = null,
}: {
  events: TraceEvent[]
  status: OperationStatus
  title?: string
  idleText?: string
  className?: string
  maxHeight?: string
  /** Upload fraction (0..1) while the request body is being sent; null when not applicable. */
  upload?: number | null
}) {
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollTop = el.scrollHeight
  }, [events.length])

  return (
    <div className={cx('overflow-hidden rounded-xs border border-line bg-[#060708]', className)}>
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <span className="flex items-center gap-2 font-mono text-[11px] text-ink-3">
          <Terminal className="size-3.5" aria-hidden />
          {title}
        </span>
        <span className="flex items-center gap-1.5 font-mono text-[10px] tracking-wider uppercase">
          <span
            className={cx(
              'size-1.5 rounded-full',
              status === 'running' && 'animate-pulse-soft bg-accent',
              status === 'success' && 'bg-ok',
              status === 'error' && 'bg-critical',
              status === 'idle' && 'bg-ink-4',
            )}
          />
          <span className="text-ink-3">{status === 'running' ? 'streaming' : status}</span>
        </span>
      </div>
      {status === 'running' && upload !== null && upload < 1 && (
        <div className="relative h-0.5 bg-raised" role="progressbar" aria-label="Upload progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(upload * 100)}>
          <div className="absolute inset-y-0 left-0 bg-accent transition-[width] duration-150" style={{ width: `${upload * 100}%` }} />
        </div>
      )}
      <div ref={scroller} className={cx('overflow-y-auto px-3 py-2.5 font-mono text-[12px] leading-[1.7]', maxHeight)} role="log" aria-live="polite" aria-relevant="additions">
        {events.length === 0 && (
          <p className="text-ink-4">
            {status !== 'running' ? idleText : upload === null ? 'Connecting to backend…' : upload < 1 ? `Uploading… ${Math.round(upload * 100)}%` : 'Upload complete — waiting for the backend…'}
          </p>
        )}
        {events.map((event, i) => {
          const duration = typeof event.data?.duration_ms === 'number' ? (event.data.duration_ms as number) : null
          return (
            <motion.div key={i} initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.18 }} className="flex gap-2">
              <span className="shrink-0 text-ink-4">[{timeOfDay(event.ts)}]</span>
              <span className="w-16 shrink-0 truncate text-accent/70">{event.stage}</span>
              <span className={cx('min-w-0 break-words', LEVEL_CLASS[event.level] ?? 'text-ink-2')}>
                {event.message}
                {duration !== null && <span className="ml-2 text-ink-4">({duration.toFixed(0)} ms)</span>}
              </span>
            </motion.div>
          )
        })}
        {status === 'running' && <span className="inline-block h-3.5 w-2 animate-blink bg-accent align-middle" aria-hidden />}
      </div>
    </div>
  )
}
