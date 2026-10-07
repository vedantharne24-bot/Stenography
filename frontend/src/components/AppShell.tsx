import { AnimatePresence, motion } from 'framer-motion'
import {
  BrainCircuit,
  Cpu,
  Database,
  FileText,
  FlaskConical,
  History,
  KeyRound,
  LayoutDashboard,
  Lock,
  LockKeyhole,
  LogOut,
  Menu,
  Microscope,
  ScanSearch,
  ScrollText,
  Settings,
  Swords,
  X,
  type LucideIcon,
} from 'lucide-react'
import { Suspense, useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { Health } from '../lib/types'
import { Logo } from './Logo'
import { Skeleton, cx } from './ui'

export interface NavItem {
  to: string
  label: string
  index: string
  icon: LucideIcon
  permission: string | null
  minRole?: string
}

export const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: 'Operate',
    items: [
      { to: '/dashboard', label: 'Dashboard', index: '01', icon: LayoutDashboard, permission: null },
      { to: '/secure-hide', label: 'Secure Hide', index: '02', icon: LockKeyhole, permission: 'stego:embed' },
      { to: '/extract', label: 'Extract', index: '03', icon: KeyRound, permission: 'stego:extract' },
      { to: '/steganalysis', label: 'Steganalysis', index: '04', icon: ScanSearch, permission: 'analysis:run' },
    ],
  },
  {
    group: 'Investigate',
    items: [
      { to: '/forensics', label: 'Forensics', index: '05', icon: Microscope, permission: 'forensics:run', minRole: 'Analyst' },
      { to: '/attack-lab', label: 'Attack Lab', index: '06', icon: Swords, permission: 'attacks:run', minRole: 'Analyst' },
      { to: '/experiments', label: 'Experiments', index: '07', icon: FlaskConical, permission: 'experiments:run', minRole: 'Analyst' },
      { to: '/reports', label: 'Reports', index: '08', icon: FileText, permission: 'reports:generate', minRole: 'Analyst' },
    ],
  },
  {
    group: 'Records',
    items: [
      { to: '/history', label: 'History', index: '09', icon: History, permission: 'history:own' },
      { to: '/models', label: 'Models', index: '10', icon: BrainCircuit, permission: 'models:read', minRole: 'Analyst' },
      { to: '/audit-logs', label: 'Audit Logs', index: '11', icon: ScrollText, permission: 'audit:read', minRole: 'Admin' },
    ],
  },
  { group: 'System', items: [{ to: '/settings', label: 'Settings', index: '12', icon: Settings, permission: null }] },
]

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const { can } = useAuth()
  return (
    <nav aria-label="Modules" className="flex flex-col gap-5">
      {NAV.map((group) => (
        <div key={group.group}>
          <p className="label-mono mb-1.5 px-3 text-ink-4">{group.group}</p>
          <ul className="flex flex-col">
            {group.items.map((item) => {
              const allowed = item.permission === null || can(item.permission)
              const Icon = item.icon
              if (!allowed)
                return (
                  <li key={item.to}>
                    <span className="flex cursor-not-allowed items-center gap-3 px-3 py-1.5 text-sm text-ink-4" title={`Requires ${item.minRole ?? 'elevated'} role`}>
                      <span className="w-5 font-mono text-[10px]">{item.index}</span>
                      <Lock className="size-3.5" aria-hidden />
                      <span>{item.label}</span>
                      <span className="sr-only">(requires {item.minRole} role)</span>
                    </span>
                  </li>
                )
              return (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      cx(
                        'group relative flex items-center gap-3 px-3 py-1.5 text-sm transition-colors',
                        isActive ? 'text-ink' : 'text-ink-2 hover:text-ink',
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {isActive && <motion.span layoutId="nav-active" className="absolute inset-y-0 left-0 w-0.5 bg-accent" />}
                        <span className={cx('w-5 font-mono text-[10px]', isActive ? 'text-accent' : 'text-ink-4')}>{item.index}</span>
                        <Icon className={cx('size-4', isActive ? 'text-accent' : 'text-ink-3 group-hover:text-ink-2')} aria-hidden />
                        <span>{item.label}</span>
                      </>
                    )}
                  </NavLink>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </nav>
  )
}

function Telemetry() {
  const [health, setHealth] = useState<Health | null>(null)
  const [offline, setOffline] = useState(false)
  useEffect(() => {
    let alive = true
    const load = () =>
      api<Health>('/api/health')
        .then((h) => {
          if (!alive) return
          setHealth(h)
          setOffline(false)
        })
        .catch(() => alive && setOffline(true))
    load()
    const timer = setInterval(load, 30_000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])
  if (offline)
    return (
      <span className="flex items-center gap-1.5 font-mono text-[11px] text-critical-ink">
        <span className="size-1.5 rounded-full bg-critical" /> API unreachable
      </span>
    )
  if (!health) return <Skeleton className="h-4 w-64" />
  const cnn = health.models['steganalysis-cnn']
  return (
    <div className="hidden items-center gap-4 font-mono text-[11px] text-ink-3 lg:flex">
      <span className="flex items-center gap-1.5" title="Database">
        <Database className="size-3.5" aria-hidden />
        <span className={health.database === 'ok' ? 'text-ok-ink' : 'text-critical-ink'}>{health.database === 'ok' ? 'DB online' : 'DB down'}</span>
      </span>
      <span className="flex items-center gap-1.5" title={health.compute.framework ?? ''}>
        <Cpu className="size-3.5" aria-hidden />
        {health.compute.device === 'cuda' ? `CUDA · ${health.compute.gpu_name ?? 'GPU'}` : 'CPU inference'}
      </span>
      <span className="flex items-center gap-1.5">
        <BrainCircuit className="size-3.5" aria-hidden />
        {cnn ? `StegoNet v${cnn}` : <span className="text-warn">model not trained</span>}
      </span>
    </div>
  )
}

function UserMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  if (!user) return null
  return (
    <div className="flex items-center gap-3">
      <div className="hidden text-right sm:block">
        <p className="text-sm leading-tight text-ink">{user.name}</p>
        <p className="font-mono text-[10px] tracking-wider text-accent uppercase">{user.role}</p>
      </div>
      <button
        type="button"
        onClick={async () => {
          await logout()
          navigate('/login')
        }}
        className="rounded-xs border border-line p-2 text-ink-3 transition-colors hover:border-ink-4 hover:text-ink"
        aria-label="Sign out"
        title="Sign out"
      >
        <LogOut className="size-4" />
      </button>
    </div>
  )
}

export function PageFallback() {
  return (
    <div className="space-y-4" aria-busy="true">
      <Skeleton className="h-10 w-72" />
      <Skeleton className="h-4 w-96" />
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    </div>
  )
}

export function AppShell() {
  const [open, setOpen] = useState(false)
  const location = useLocation()
  useEffect(() => setOpen(false), [location.pathname])

  return (
    <div className="min-h-dvh bg-bg">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:bg-accent focus:px-3 focus:py-2 focus:text-accent-ink">
        Skip to content
      </a>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-line bg-surface lg:flex">
        <Link to="/" className="flex h-14 items-center gap-2.5 border-b border-line px-4">
          <Logo />
        </Link>
        <div className="flex-1 overflow-y-auto py-5">
          <NavLinks />
        </div>
        <p className="border-t border-line px-4 py-3 font-mono text-[10px] leading-relaxed text-ink-4">AES-256-GCM · Argon2id · SHA-256</p>
      </aside>

      <AnimatePresence>
        {open && (
          <>
            <motion.div className="fixed inset-0 z-40 bg-bg/70 backdrop-blur-sm lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)} />
            <motion.aside
              className="fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-line bg-surface lg:hidden"
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', stiffness: 380, damping: 38 }}
              aria-label="Navigation"
            >
              <div className="flex h-14 items-center justify-between border-b border-line px-4">
                <Logo />
                <button type="button" onClick={() => setOpen(false)} className="p-2 text-ink-2" aria-label="Close navigation">
                  <X className="size-5" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto py-5">
                <NavLinks onNavigate={() => setOpen(false)} />
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-4 border-b border-line bg-bg/85 px-4 backdrop-blur md:px-6">
          <div className="flex items-center gap-3">
            <button type="button" onClick={() => setOpen(true)} className="rounded-xs p-2 text-ink-2 hover:text-ink lg:hidden" aria-label="Open navigation">
              <Menu className="size-5" />
            </button>
            <span className="lg:hidden">
              <Logo compact />
            </span>
            <Telemetry />
          </div>
          <UserMenu />
        </header>
        <main id="main" className="mx-auto w-full max-w-[1400px] px-4 py-6 md:px-6 md:py-8">
          <Suspense fallback={<PageFallback />}>
            <motion.div key={location.pathname} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, ease: 'easeOut' }}>
              <Outlet />
            </motion.div>
          </Suspense>
        </main>
      </div>
    </div>
  )
}

export function Restricted({ permission, children }: { permission: string | null; children: ReactNode }) {
  const { can, user } = useAuth()
  if (permission === null || can(permission)) return <>{children}</>
  return (
    <div className="mx-auto max-w-lg py-20 text-center">
      <Lock className="mx-auto size-8 text-ink-4" aria-hidden />
      <h1 className="mt-4 font-display text-3xl font-bold tracking-wide uppercase">Access restricted</h1>
      <p className="mt-2 text-sm text-ink-2">
        Your role <span className="font-mono text-accent">{user?.role}</span> lacks the <span className="font-mono">{permission}</span> permission. Access is
        enforced by the API as well — an administrator can change your role.
      </p>
    </div>
  )
}
