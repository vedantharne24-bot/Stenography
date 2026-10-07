import { motion } from 'framer-motion'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Logo } from '../components/Logo'

/** Split layout for login/registration: form on the left, live "cipher field" on the right. */
export function AuthLayout({ title, kicker, children, footer }: { title: string; kicker: string; children: ReactNode; footer: ReactNode }) {
  return (
    <div className="grid min-h-dvh bg-bg lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="flex flex-col px-6 py-8 sm:px-12">
        <Link to="/" className="self-start">
          <Logo />
        </Link>
        <div className="flex flex-1 items-center">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="w-full max-w-sm">
            <p className="label-mono mb-3 text-accent">{kicker}</p>
            <h1 className="mb-8 font-display text-5xl font-bold tracking-wide uppercase">{title}</h1>
            {children}
            <div className="mt-8 text-sm text-ink-2">{footer}</div>
          </motion.div>
        </div>
        <p className="font-mono text-[10px] text-ink-4">Passwords are hashed with Argon2id · sessions use rotating httpOnly refresh tokens</p>
      </div>
      <CipherField />
    </div>
  )
}

const GLYPHS = '0123456789abcdef'

/** Decorative panel: rows of ciphertext that resolve into plaintext on a scan line. Static under reduced motion. */
function CipherField() {
  const rows = Array.from({ length: 22 }, (_, r) =>
    Array.from({ length: 48 }, (_, c) => GLYPHS[(r * 7 + c * 13 + ((r * c) % 5)) % 16]).join(''),
  )
  return (
    <div className="relative hidden overflow-hidden border-l border-line bg-surface lg:block" aria-hidden>
      <div className="grid-bg absolute inset-0 opacity-60" />
      <div className="absolute inset-0 flex flex-col justify-center gap-1 px-12 font-mono text-[13px] tracking-[0.3em] text-ink-4/70">
        {rows.map((row, i) => (
          <motion.p key={i} initial={{ opacity: 0 }} animate={{ opacity: [0.25, 0.7, 0.25] }} transition={{ duration: 4, delay: i * 0.12, repeat: Infinity }}>
            {row}
          </motion.p>
        ))}
      </div>
      <div className="absolute inset-x-0 top-0 h-full animate-scan">
        <div className="h-24 bg-gradient-to-b from-transparent via-accent/10 to-transparent" />
        <div className="h-px bg-accent/70 shadow-[0_0_16px_var(--color-accent)]" />
      </div>
      <div className="absolute right-10 bottom-10 left-12 border-t border-line pt-4">
        <p className="font-serif text-3xl text-ink italic">“The best place to hide is in plain sight.”</p>
        <p className="label-mono mt-2">AES-256-GCM sealed · embedded in pixels · detected by AI</p>
      </div>
    </div>
  )
}
