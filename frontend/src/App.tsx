import { lazy, Suspense, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppShell, PageFallback, Restricted } from './components/AppShell'
import { AuthProvider, useAuth } from './lib/auth'

const Landing = lazy(() => import('./pages/Landing'))
const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const SecureHide = lazy(() => import('./pages/SecureHide'))
const Extract = lazy(() => import('./pages/Extract'))
const Steganalysis = lazy(() => import('./pages/Steganalysis'))
const Forensics = lazy(() => import('./pages/Forensics'))
const AttackLab = lazy(() => import('./pages/AttackLab'))
const Experiments = lazy(() => import('./pages/Experiments'))
const Reports = lazy(() => import('./pages/Reports'))
const HistoryPage = lazy(() => import('./pages/History'))
const Models = lazy(() => import('./pages/Models'))
const AuditLogs = lazy(() => import('./pages/AuditLogs'))
const SettingsPage = lazy(() => import('./pages/Settings'))

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth()
  const location = useLocation()
  if (!ready)
    return (
      <div className="grid min-h-dvh place-items-center font-mono text-xs tracking-widest text-ink-3 uppercase" aria-busy="true">
        Restoring secure session…
      </div>
    )
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

const guarded = (permission: string | null, node: ReactNode) => <Restricted permission={permission}>{node}</Restricted>

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Suspense fallback={<div className="min-h-dvh bg-bg" />}>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route
              element={
                <RequireAuth>
                  <AppShell />
                </RequireAuth>
              }
            >
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/secure-hide" element={guarded('stego:embed', <SecureHide />)} />
              <Route path="/extract" element={guarded('stego:extract', <Extract />)} />
              <Route path="/steganalysis" element={guarded('analysis:run', <Steganalysis />)} />
              <Route path="/forensics" element={guarded('forensics:run', <Forensics />)} />
              <Route path="/attack-lab" element={guarded('attacks:run', <AttackLab />)} />
              <Route path="/experiments" element={guarded('experiments:run', <Experiments />)} />
              <Route path="/reports" element={guarded('reports:generate', <Reports />)} />
              <Route path="/history" element={guarded('history:own', <HistoryPage />)} />
              <Route path="/models" element={guarded('models:read', <Models />)} />
              <Route path="/audit-logs" element={guarded('audit:read', <AuditLogs />)} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
            <Route
              path="*"
              element={
                <Suspense fallback={<PageFallback />}>
                  <div className="grid min-h-dvh place-items-center text-center">
                    <div>
                      <p className="font-display text-7xl font-bold text-ink-4">404</p>
                      <p className="mt-2 font-mono text-xs tracking-widest text-ink-3 uppercase">No such route</p>
                      <a href="/" className="mt-4 inline-block text-sm text-accent hover:underline">
                        Return to base
                      </a>
                    </div>
                  </div>
                </Suspense>
              }
            />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </AuthProvider>
  )
}
