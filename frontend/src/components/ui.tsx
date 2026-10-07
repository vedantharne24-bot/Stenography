import { animate, motion, useInView, useMotionValue, useReducedMotion } from 'framer-motion'
import {
  AlertTriangle,
  Check,
  CircleAlert,
  Copy,
  Info,
  Loader2,
  OctagonAlert,
  ShieldAlert,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react'
import { forwardRef, useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import type { ApiError } from '../lib/api'
import type { RiskLevel } from '../lib/types'

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}

/* ---------------------------------------------------------------- Button */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: 'sm' | 'md' | 'lg'
  loading?: boolean
  icon?: LucideIcon
}

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-accent-ink hover:bg-[#7fe9ed] border border-accent',
  secondary: 'bg-transparent text-ink border border-line-strong hover:border-ink-3 hover:bg-raised',
  ghost: 'bg-transparent text-ink-2 border border-transparent hover:text-ink hover:bg-raised',
  danger: 'bg-transparent text-critical-ink border border-critical/60 hover:bg-critical/15',
}

const BUTTON_SIZES = { sm: 'h-8 px-3 text-xs gap-1.5', md: 'h-10 px-4 text-sm gap-2', lg: 'h-12 px-6 text-[15px] gap-2.5' }

/** Button styling for non-button elements (e.g. router links) - avoids nesting <button> in <a>. */
export function buttonClasses(variant: ButtonVariant = 'secondary', size: 'sm' | 'md' | 'lg' = 'md', className?: string): string {
  return cx(
    'inline-flex select-none items-center justify-center rounded-xs font-medium tracking-wide transition-[background,border,color,transform] duration-150 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-45',
    BUTTON_VARIANTS[variant],
    BUTTON_SIZES[size],
    className,
  )
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading = false, icon: Icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={buttonClasses(variant, size, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : Icon ? <Icon className="size-4" aria-hidden /> : null}
      {children}
    </button>
  )
})

/* ---------------------------------------------------------------- Panel */

interface PanelProps {
  title?: ReactNode
  index?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
  brackets?: boolean
  as?: 'section' | 'div' | 'article'
}

export function Panel({ title, index, actions, children, className, bodyClassName, brackets = false, as: Tag = 'section' }: PanelProps) {
  return (
    <Tag className={cx('relative min-w-0 rounded-xs border border-line bg-surface', brackets && 'bracket', className)}>
      {(title || actions) && (
        <header className="flex min-h-11 items-center justify-between gap-3 border-b border-line px-4 py-2">
          <div className="flex min-w-0 items-baseline gap-3">
            {index && <span className="font-mono text-[11px] text-ink-4">{index}</span>}
            {title && <h2 className="truncate font-mono text-[11px] tracking-[0.12em] text-ink-2 uppercase">{title}</h2>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx('p-4', bodyClassName)}>{children}</div>
    </Tag>
  )
}

/* ---------------------------------------------------------------- Page header */

export function PageHeader({ index, title, kicker, description, actions }: { index: string; title: string; kicker?: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-col gap-4 border-b border-line pb-5 md:flex-row md:items-end md:justify-between">
      <div className="max-w-3xl">
        <p className="label-mono mb-2">
          <span className="text-accent">{index}</span> <span className="text-ink-4">/</span> {kicker ?? 'Module'}
        </p>
        <h1 className="font-display text-4xl font-bold tracking-wide text-ink uppercase md:text-5xl">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  )
}

/* ---------------------------------------------------------------- Form fields */

export function Field({ label, hint, error, children, htmlFor }: { label: string; hint?: ReactNode; error?: string | null; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="label-mono">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-critical-ink" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-ink-3">{hint}</p>
      ) : null}
    </div>
  )
}

const INPUT = 'w-full rounded-xs border border-line-strong bg-bg px-3 text-sm text-ink placeholder:text-ink-4 transition-colors hover:border-ink-4 focus:border-accent focus:outline-none'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cx(INPUT, 'h-10', className)} {...rest} />
})

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cx(INPUT, 'min-h-28 py-2.5 font-mono text-[13px] leading-relaxed', className)} {...rest} />
})

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx(INPUT, 'h-10 appearance-none bg-[length:12px] bg-[right_12px_center] bg-no-repeat pr-8', className)} {...rest}>
      {children}
    </select>
  )
}

/** Segmented control (radio group semantics). */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = 'md',
}: {
  value: T
  onChange: (value: T) => void
  options: { value: T; label: ReactNode; hint?: string; disabled?: boolean }[]
  label: string
  size?: 'sm' | 'md'
}) {
  const name = useId()
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap rounded-xs border border-line-strong bg-bg p-0.5">
      {options.map((opt) => {
        const active = opt.value === value
        return (
          <label
            key={opt.value}
            title={opt.hint}
            className={cx(
              'relative cursor-pointer rounded-[1px] font-medium transition-colors',
              size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3.5 py-1.5 text-sm',
              active ? 'text-accent-ink' : 'text-ink-2 hover:text-ink',
              opt.disabled && 'pointer-events-none opacity-40',
            )}
          >
            <input type="radio" name={name} className="sr-only" checked={active} onChange={() => onChange(opt.value)} disabled={opt.disabled} />
            {active && <motion.span layoutId={`seg-${name}`} className="absolute inset-0 rounded-[1px] bg-accent" transition={{ type: 'spring', stiffness: 500, damping: 40 }} />}
            <span className="relative">{opt.label}</span>
          </label>
        )
      })}
    </div>
  )
}

/* ---------------------------------------------------------------- Status & risk */

export type Tone = 'ok' | 'warn' | 'serious' | 'critical' | 'info' | 'neutral'

const TONES: Record<Tone, { cls: string; icon: LucideIcon }> = {
  ok: { cls: 'border-ok/50 bg-ok/12 text-ok-ink', icon: ShieldCheck },
  warn: { cls: 'border-warn/50 bg-warn/10 text-warn', icon: AlertTriangle },
  serious: { cls: 'border-serious/50 bg-serious/10 text-serious', icon: ShieldAlert },
  critical: { cls: 'border-critical/60 bg-critical/15 text-critical-ink', icon: OctagonAlert },
  info: { cls: 'border-accent/40 bg-accent/8 text-accent', icon: Info },
  neutral: { cls: 'border-line-strong bg-raised text-ink-2', icon: CircleAlert },
}

export function StatusBadge({ tone, children, icon, className }: { tone: Tone; children: ReactNode; icon?: LucideIcon | null; className?: string }) {
  const Icon = icon === null ? null : (icon ?? TONES[tone].icon)
  return (
    <span className={cx('inline-flex items-center gap-1.5 rounded-xs border px-2 py-0.5 font-mono text-[11px] font-medium tracking-wider uppercase', TONES[tone].cls, className)}>
      {Icon && <Icon className="size-3.5" aria-hidden />}
      {children}
    </span>
  )
}

export const RISK_TONE: Record<RiskLevel, Tone> = { LOW: 'ok', MEDIUM: 'warn', HIGH: 'serious', CRITICAL: 'critical' }

export function RiskBadge({ level, score }: { level: RiskLevel; score?: number }) {
  return (
    <StatusBadge tone={RISK_TONE[level]}>
      {level}
      {score !== undefined && <span className="tabular opacity-80">· {score.toFixed(1)}</span>}
    </StatusBadge>
  )
}

export function IntegrityBadge({ status }: { status: string }) {
  if (status === 'verified') return <StatusBadge tone="ok" icon={Check}>Verified</StatusBadge>
  if (status === 'failed') return <StatusBadge tone="critical">Failed</StatusBadge>
  if (status === 'not_found') return <StatusBadge tone="neutral">Not found</StatusBadge>
  return <StatusBadge tone="neutral">{status.replace('_', ' ')}</StatusBadge>
}

/* ---------------------------------------------------------------- Technique chip */

export const TECHNIQUE_COLOR: Record<string, string> = {
  normal: 'var(--color-normal)',
  lsb: 'var(--color-lsb)',
  dct: 'var(--color-dct)',
  dwt: 'var(--color-dwt)',
}

export function TechniqueChip({ technique }: { technique: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-xs tracking-wider text-ink uppercase">
      <span aria-hidden className="inline-block size-2 rounded-[1px]" style={{ background: TECHNIQUE_COLOR[technique] ?? 'var(--color-ink-3)' }} />
      {technique === 'normal' ? 'Normal' : technique}
    </span>
  )
}

/* ---------------------------------------------------------------- Stat / count-up */

export function CountUp({ value, format = (v) => Math.round(v).toLocaleString('en-US'), className }: { value: number; format?: (v: number) => string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true, margin: '-40px' })
  const reduced = useReducedMotion()
  const mv = useMotionValue(0)
  const [display, setDisplay] = useState(() => format(reduced ? value : 0))

  useEffect(() => {
    if (reduced) {
      setDisplay(format(value))
      return
    }
    if (!inView) return
    const controls = animate(mv, value, { duration: 1.1, ease: [0.16, 1, 0.3, 1], onUpdate: (v) => setDisplay(format(v)) })
    return () => controls.stop()
  }, [value, inView, reduced, format, mv])

  return (
    <span ref={ref} className={cx('tabular', className)}>
      <span aria-hidden>{display}</span>
      <span className="sr-only">{format(value)}</span>
    </span>
  )
}

export function Stat({ label, value, sub, tone, children }: { label: string; value: ReactNode; sub?: ReactNode; tone?: Tone; children?: ReactNode }) {
  const toneText = tone === 'ok' ? 'text-ok-ink' : tone === 'critical' ? 'text-critical-ink' : tone === 'warn' ? 'text-warn' : tone === 'serious' ? 'text-serious' : 'text-ink'
  return (
    <div className="flex min-w-0 flex-col gap-1 border-l border-line pl-4">
      <span className="label-mono truncate">{label}</span>
      <span className={cx('font-display text-3xl leading-none font-bold tracking-wide md:text-[34px]', toneText)}>{value}</span>
      {sub && <span className="truncate text-xs text-ink-3">{sub}</span>}
      {children}
    </div>
  )
}

/* ---------------------------------------------------------------- Hash / copy */

export function Hash({ value, label, truncate = true }: { value: string | null | undefined; label?: string; truncate?: boolean }) {
  const [copied, setCopied] = useState(false)
  if (!value) return <span className="font-mono text-xs text-ink-4">—</span>
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1400)
    } catch {
      /* clipboard unavailable */
    }
  }
  return (
    <span className="group inline-flex max-w-full min-w-0 items-center gap-1.5">
      {label && <span className="label-mono shrink-0">{label}</span>}
      <code className={cx('min-w-0 font-mono text-xs text-ink-2', truncate ? 'truncate' : 'break-all')} title={value}>
        {value}
      </code>
      <button type="button" onClick={copy} className="shrink-0 rounded-xs p-1 text-ink-3 hover:bg-raised hover:text-ink" aria-label={`Copy ${label ?? 'value'}`}>
        {copied ? <Check className="size-3.5 text-ok-ink" /> : <Copy className="size-3.5" />}
      </button>
    </span>
  )
}

/* ---------------------------------------------------------------- States */

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('animate-pulse-soft rounded-xs bg-raised', className)} aria-hidden />
}

export function ErrorNotice({ error, title = 'Operation failed' }: { error: ApiError | Error | string | null; title?: string }) {
  if (!error) return null
  const message = typeof error === 'string' ? error : error.message
  const code = typeof error === 'object' && 'code' in error ? (error as ApiError).code : null
  const details = typeof error === 'object' && 'details' in error ? (error as ApiError).details : null
  const fields = (details?.fields as { field: string; message: string }[] | undefined) ?? null
  const requirements = (details?.requirements as string[] | undefined) ?? null
  return (
    <div role="alert" className="flex gap-3 rounded-xs border border-critical/50 bg-critical/10 p-3 text-sm">
      <OctagonAlert className="mt-0.5 size-4 shrink-0 text-critical-ink" aria-hidden />
      <div className="min-w-0">
        <p className="font-medium text-ink">
          {title}
          {code && <span className="ml-2 font-mono text-[11px] text-ink-3">[{code}]</span>}
        </p>
        <p className="mt-0.5 text-ink-2">{message}</p>
        {fields && (
          <ul className="mt-1 list-inside list-disc text-xs text-ink-3">
            {fields.map((f) => (
              <li key={f.field}>
                {f.field}: {f.message}
              </li>
            ))}
          </ul>
        )}
        {requirements && <p className="mt-1 text-xs text-ink-3">Requires: {requirements.join('; ')}</p>}
      </div>
    </div>
  )
}

export function EmptyState({ icon: Icon = Info, title, children }: { icon?: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <Icon className="size-6 text-ink-4" aria-hidden />
      <p className="font-mono text-xs tracking-wider text-ink-2 uppercase">{title}</p>
      {children && <div className="max-w-md text-sm text-ink-3">{children}</div>}
    </div>
  )
}

/* ---------------------------------------------------------------- Meter */

export function Meter({ value, color = 'var(--color-accent)', label }: { value: number; color?: string; label: string }) {
  const clamped = Math.max(0, Math.min(1, value))
  return (
    <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={1} aria-valuenow={Number(clamped.toFixed(3))} className="h-1.5 w-full overflow-hidden rounded-[1px] bg-raised">
      <motion.div className="h-full rounded-[1px]" style={{ background: color }} initial={{ width: 0 }} animate={{ width: `${clamped * 100}%` }} transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }} />
    </div>
  )
}

export function KeyValue({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="label-mono self-center">{k}</dt>
          <dd className="min-w-0 text-right text-ink tabular">{v}</dd>
        </div>
      ))}
    </dl>
  )
}
