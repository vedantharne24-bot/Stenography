import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { authApi, refreshSession, setAccessToken, setSessionLostHandler } from './api'
import type { User } from './types'

interface AuthState {
  user: User | null
  ready: boolean
  can: (permission: string) => boolean
  login: (email: string, password: string) => Promise<User>
  register: (name: string, email: string, password: string) => Promise<User>
  logout: () => Promise<void>
  setUser: (user: User) => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    setSessionLostHandler(() => {
      setAccessToken(null)
      setUser(null)
    })
    // Restore the session from the httpOnly refresh cookie (if any).
    refreshSession()
      .then((data) => setUser(data?.user ?? null))
      .finally(() => setReady(true))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const data = await authApi.login(email, password)
    setAccessToken(data.access_token)
    setUser(data.user)
    return data.user
  }, [])

  const register = useCallback(async (name: string, email: string, password: string) => {
    const data = await authApi.register(name, email, password)
    setAccessToken(data.access_token)
    setUser(data.user)
    return data.user
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      setAccessToken(null)
      setUser(null)
    }
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      ready,
      can: (permission: string) => Boolean(user?.permissions.includes(permission)),
      login,
      register,
      logout,
      setUser,
    }),
    [user, ready, login, register, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
