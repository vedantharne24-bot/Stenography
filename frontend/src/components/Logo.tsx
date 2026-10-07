export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-6 shrink-0" aria-hidden>
        <path d="M6 6h7v2H8v5H6zM26 6h-7v2h5v5h2zM6 26h7v-2H8v-5H6zM26 26h-7v-2h5v-5h2z" fill="var(--color-ink)" />
        <rect x="11" y="15" width="10" height="2" fill="var(--color-accent)" />
        <rect x="15" y="11" width="2" height="10" fill="var(--color-accent)" opacity=".55" />
      </svg>
      {!compact && (
        <span className="leading-none">
          <span className="block font-display text-xl font-bold tracking-[0.12em] text-ink uppercase">StegoLab</span>
          <span className="block font-mono text-[9px] tracking-[0.18em] text-ink-3 uppercase">Covert-channel lab</span>
        </span>
      )}
      {compact && <span className="font-display text-lg font-bold tracking-[0.12em] uppercase">StegoLab</span>}
    </span>
  )
}
