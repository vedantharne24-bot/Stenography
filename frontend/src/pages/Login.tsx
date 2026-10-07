import { LogIn } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Button, ErrorNotice, Field, Input } from '../components/ui'
import type { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { AuthLayout } from './AuthLayout'

export default function Login() {
  const { login, user, ready } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const from = (location.state as { from?: string } | null)?.from ?? '/dashboard'

  if (ready && user) return <Navigate to={from} replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err as ApiError)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      kicker="Authenticate"
      title="Sign in"
      footer={
        <>
          No account?{' '}
          <Link to="/register" className="text-accent hover:underline">
            Register
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Field label="Email" htmlFor="email">
          <Input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="password">
          <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <ErrorNotice error={error} title="Sign-in failed" />
        <Button type="submit" variant="primary" size="lg" loading={busy} icon={LogIn} disabled={!email || !password}>
          Sign in
        </Button>
      </form>
    </AuthLayout>
  )
}
