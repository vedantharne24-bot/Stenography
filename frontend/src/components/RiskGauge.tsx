import { motion } from 'framer-motion'
import type { RiskLevel } from '../lib/types'
import { RiskBadge } from './ui'

const LEVEL_COLOR: Record<RiskLevel, string> = {
  LOW: 'var(--color-ok)',
  MEDIUM: 'var(--color-warn)',
  HIGH: 'var(--color-serious)',
  CRITICAL: 'var(--color-critical)',
}

/** Semicircular 0–100 risk gauge; level is always also shown as icon + label. */
export function RiskGauge({ score, level, size = 220 }: { score: number; level: RiskLevel; size?: number }) {
  const r = 80
  const circumference = Math.PI * r
  const fraction = Math.max(0, Math.min(1, score / 100))
  return (
    <div className="flex flex-col items-center" role="img" aria-label={`Risk score ${score.toFixed(1)} of 100, level ${level}`}>
      <svg viewBox="0 0 200 116" width={size} height={(size * 116) / 200}>
        <path d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke="var(--color-raised)" strokeWidth="12" strokeLinecap="butt" />
        {[0.35, 0.65, 0.85].map((t) => {
          const angle = Math.PI * (1 - t)
          const x1 = 100 + Math.cos(angle) * 70
          const y1 = 100 - Math.sin(angle) * 70
          const x2 = 100 + Math.cos(angle) * 92
          const y2 = 100 - Math.sin(angle) * 92
          return <line key={t} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--color-line-strong)" strokeWidth="1" />
        })}
        <motion.path
          d="M20 100 A80 80 0 0 1 180 100"
          fill="none"
          stroke={LEVEL_COLOR[level]}
          strokeWidth="12"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference * (1 - fraction) }}
          transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1] }}
        />
        <text x="100" y="92" textAnchor="middle" fill="var(--color-ink)" style={{ font: '700 40px var(--font-display)' }}>
          {score.toFixed(1)}
        </text>
        <text x="100" y="110" textAnchor="middle" fill="var(--color-ink-3)" style={{ font: '400 9px var(--font-mono)', letterSpacing: '0.12em' }}>
          RISK / 100
        </text>
      </svg>
      <RiskBadge level={level} />
    </div>
  )
}
