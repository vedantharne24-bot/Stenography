import { Check, UserPlus, X } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { Button, ErrorNotice, Field, Input, cx } from '../components/ui'
import type { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { AuthLayout } from './AuthLayout'

/** Mirrors the server policy (app/core/security.py) for instant feedback; the server is authoritative. */
function passwordChecks(password: string, email: string) {
  const local = email.split('@')[0]?.toLowerCase() ?? ''
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length
  return [
    { label: 'At least 10 characters', ok: password.length >= 10 },
    { label: 'Three of: lower, upper, digit, symbol', ok: classes >= 3 },
    { label: 'Does not contain your email name', ok: !(local.length >= 4 && password.toLowerCase().includes(local)) },
  ]
}

export default function Register() {
  const { register, user, ready } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const checks = useMemo(() => passwordChecks(password, email), [password, email])
  const valid = name.trim() && email.includes('@') && checks.every((c) => c.ok) && password === confirm

  if (ready && user) return <Navigate to="/dashboard" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await register(name, email, password)
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setError(err as ApiError)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      kicker="New operator"
      title="Register"
      footer={
        <>
          Already registered?{' '}
          <Link to="/login" className="text-accent hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Field label="Name" htmlFor="name">
          <Input id="name" autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
        </Field>
        <Field label="Email" htmlFor="email">
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="password">
          <Input id="password" type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <ul className="flex flex-col gap-1" aria-label="Password requirements">
          {checks.map((c) => (
            <li key={c.label} className={cx('flex items-center gap-2 font-mono text-[11px]', c.ok ? 'text-ok-ink' : 'text-ink-3')}>
              {c.ok ? <Check className="size-3.5" aria-hidden /> : <X className="size-3.5" aria-hidden />}
              {c.label}
              <span className="sr-only">{c.ok ? 'met' : 'not met'}</span>
            </li>
          ))}
        </ul>
        <Field label="Confirm password" htmlFor="confirm" error={confirm && confirm !== password ? 'Passwords do not match' : null}>
          <Input id="confirm" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
        <ErrorNotice error={error} title="Registration failed" />
        <Button type="submit" variant="primary" size="lg" loading={busy} icon={UserPlus} disabled={!valid}>
          Create account
        </Button>
        <p className="text-xs text-ink-3">New accounts receive the USER role. An administrator can grant ANALYST or ADMIN.</p>
      </form>
    </AuthLayout>
  )
}
