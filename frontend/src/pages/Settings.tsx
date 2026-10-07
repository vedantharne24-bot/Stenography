import { KeyRound, Save, ShieldAlert, Trash2, UserCog } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, ErrorNotice, Field, Input, KeyValue, PageHeader, Panel, Select, Skeleton, StatusBadge } from '../components/ui'
import { api, type ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime } from '../lib/format'
import { useApi } from '../lib/hooks'
import type { Role, User } from '../lib/types'

function Profile() {
  const { user, setUser } = useAuth()
  const [name, setName] = useState(user?.name ?? '')
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  if (!user) return null
  const save = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      setUser(await api<User>('/api/auth/me', { method: 'PATCH', json: { name } }))
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch (err) {
      setError(err as ApiError)
    }
  }
  return (
    <Panel title="Profile" index="01">
      <form onSubmit={save} className="flex flex-col gap-4">
        <Field label="Display name" htmlFor="name"><Input id="name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
        <KeyValue rows={[['Email', user.email], ['Role', <StatusBadge tone="info" icon={null}>{user.role}</StatusBadge>], ['Member since', dateTime(user.created_at)], ['Last login', dateTime(user.last_login)]]} />
        <details>
          <summary className="label-mono cursor-pointer">Effective permissions ({user.permissions.length})</summary>
          <p className="mt-2 font-mono text-xs leading-relaxed text-ink-2">{user.permissions.join(' · ')}</p>
        </details>
        <ErrorNotice error={error} />
        <Button type="submit" icon={Save} className="self-start">{saved ? 'Saved' : 'Save profile'}</Button>
      </form>
    </Panel>
  )
}

function PasswordChange() {
  const navigate = useNavigate()
  const { logout } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api('/api/auth/change-password', { method: 'POST', json: { current_password: current, new_password: next } })
      await logout().catch(() => undefined)
      navigate('/login')
    } catch (err) {
      setError(err as ApiError)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Panel title="Change password" index="02">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Current password" htmlFor="cur"><Input id="cur" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
        <Field label="New password" htmlFor="new" hint="≥ 10 characters, three character classes. All sessions are revoked after the change."><Input id="new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></Field>
        <ErrorNotice error={error} title="Password not changed" />
        <Button type="submit" icon={KeyRound} loading={busy} disabled={!current || !next} className="self-start">Change password</Button>
      </form>
    </Panel>
  )
}

function Privacy() {
  const [result, setResult] = useState<Record<string, number> | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const erase = async () => {
    if (!window.confirm('Permanently delete ALL your analyses, operations, attack experiments, research runs, reports and stored files? Audit records are retained.')) return
    setBusy(true)
    try {
      setResult(await api<Record<string, number>>('/api/history', { method: 'DELETE' }))
    } catch (err) {
      setError(err as ApiError)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Panel title="Privacy & data" index="03">
      <div className="flex flex-col gap-3 text-sm text-ink-2">
        <p><span className="text-ink">Temporary files</span> — previews, stego images, heat-maps and attacked images expire automatically after the retention window set by the administrator.</p>
        <p><span className="text-ink">User-owned records</span> — analyses, operations, experiments and reports persist until you delete them.</p>
        <p><span className="text-ink">Audit records</span> — security events are retained for accountability and contain no secrets.</p>
        <p><span className="text-ink">Never stored</span> — passwords (only Argon2id hashes), encryption keys, secret messages and recovered plaintext.</p>
      </div>
      <ErrorNotice error={error} />
      {result && <p className="mt-3 font-mono text-xs text-ok-ink">Deleted: {Object.entries(result).map(([k, v]) => `${v} ${k}`).join(' · ')}</p>}
      <Button variant="danger" icon={Trash2} onClick={erase} loading={busy} className="mt-4">Delete all my analysis data</Button>
    </Panel>
  )
}

interface AdminUser extends User { analyses: number }

function UserManagement() {
  const { user: me } = useAuth()
  const { data, error, loading, reload } = useApi<{ items: AdminUser[]; total: number }>('/api/admin/users')
  const [actionError, setActionError] = useState<ApiError | null>(null)
  const update = async (id: string, body: { role?: Role; is_active?: boolean }) => {
    setActionError(null)
    try {
      await api(`/api/admin/users/${id}`, { method: 'PATCH', json: body })
      reload()
    } catch (err) {
      setActionError(err as ApiError)
    }
  }
  return (
    <Panel title="User management" index="A1" actions={<UserCog className="size-4 text-ink-4" aria-hidden />}>
      <ErrorNotice error={error ?? actionError} />
      {loading ? (
        <Skeleton className="h-40" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead><tr className="text-left">{['User', 'Role', 'Status', 'Analyses', 'Last login'].map((h) => <th key={h} className="label-mono pb-2 font-normal">{h}</th>)}</tr></thead>
            <tbody>
              {data?.items.map((u) => (
                <tr key={u.id} className="border-t border-line">
                  <td className="py-2"><p className="text-ink">{u.name}</p><p className="font-mono text-[11px] text-ink-3">{u.email}</p></td>
                  <td className="py-2">
                    <Select aria-label={`Role for ${u.email}`} value={u.role} disabled={u.id === me?.id} onChange={(e) => update(u.id, { role: e.target.value as Role })} className="h-8 w-32 text-xs">
                      <option value="USER">USER</option>
                      <option value="ANALYST">ANALYST</option>
                      <option value="ADMIN">ADMIN</option>
                    </Select>
                  </td>
                  <td className="py-2">
                    <button type="button" disabled={u.id === me?.id} onClick={() => update(u.id, { is_active: !u.is_active })} className="disabled:opacity-50" aria-label={u.is_active ? `Disable ${u.email}` : `Enable ${u.email}`}>
                      {u.is_active ? <StatusBadge tone="ok">active</StatusBadge> : <StatusBadge tone="critical">disabled</StatusBadge>}
                    </button>
                  </td>
                  <td className="py-2 font-mono tabular">{u.analyses}</td>
                  <td className="py-2 font-mono text-xs text-ink-3">{dateTime(u.last_login)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-xs text-ink-3">Role or status changes revoke the user's existing access tokens immediately. Every change is audited.</p>
        </div>
      )}
    </Panel>
  )
}

interface SettingsPayload { values: Record<string, number | boolean>; specs: Record<string, { type: string; description: string; min: number | null; max: number | null }> }

function SystemConfig() {
  const { data, error, loading, setData } = useApi<SettingsPayload>('/api/admin/settings')
  const [draft, setDraft] = useState<Record<string, number | boolean>>({})
  const [saveError, setSaveError] = useState<ApiError | null>(null)
  const [saved, setSaved] = useState(false)
  const [sweep, setSweep] = useState<number | null>(null)
  useEffect(() => {
    if (data) setDraft(data.values)
  }, [data])
  const save = async () => {
    setSaveError(null)
    const changes = Object.fromEntries(Object.entries(draft).filter(([k, v]) => data?.values[k] !== v))
    try {
      const res = await api<{ values: Record<string, number | boolean> }>('/api/admin/settings', { method: 'PATCH', json: changes })
      if (data) setData({ ...data, values: res.values })
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch (err) {
      setSaveError(err as ApiError)
    }
  }
  return (
    <Panel title="System configuration" index="A2" actions={<ShieldAlert className="size-4 text-ink-4" aria-hidden />}>
      <ErrorNotice error={error ?? saveError} />
      {loading || !data ? (
        <Skeleton className="h-48" />
      ) : (
        <div className="flex flex-col gap-4">
          {Object.entries(data.specs).map(([key, spec]) => (
            <Field key={key} label={key.replace(/_/g, ' ')} htmlFor={key} hint={spec.description}>
              {spec.type === 'bool' ? (
                <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
                  <input id={key} type="checkbox" checked={Boolean(draft[key])} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.checked }))} className="size-4 accent-[var(--color-accent)]" />
                  {draft[key] ? 'Enabled' : 'Disabled'}
                </label>
              ) : (
                <Input id={key} type="number" min={spec.min ?? undefined} max={spec.max ?? undefined} value={Number(draft[key] ?? 0)} onChange={(e) => setDraft((d) => ({ ...d, [key]: Number(e.target.value) }))} />
              )}
            </Field>
          ))}
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" icon={Save} onClick={save}>{saved ? 'Saved' : 'Save configuration'}</Button>
            <Button icon={Trash2} onClick={async () => setSweep((await api<{ removed: number }>('/api/admin/retention/sweep', { method: 'POST' })).removed)}>Run retention sweep now</Button>
          </div>
          {sweep !== null && <p className="font-mono text-xs text-ink-2">Retention sweep removed {sweep} expired artefact(s).</p>}
        </div>
      )}
    </Panel>
  )
}

export default function Settings() {
  const { can } = useAuth()
  return (
    <div>
      <PageHeader index="12" kicker="System · account & administration" title="Settings" description="Manage your profile, credentials and data. Administrators also manage users, roles and runtime configuration — enforced by the API, not just this page." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Profile />
        <PasswordChange />
        <Privacy />
        {can('settings:manage') && <SystemConfig />}
        {can("users:manage") && <div className="min-w-0 lg:col-span-2"><UserManagement /></div>}
      </div>
    </div>
  )
}
