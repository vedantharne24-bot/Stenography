import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api, apiBlob, streamOperation } from './api'
import type { TraceEvent } from './types'

export type OperationStatus = 'idle' | 'running' | 'success' | 'error'

/** Drives a streaming backend operation: live log events, result, error, cancel. */
export function useOperation<T>(path: string) {
  const [status, setStatus] = useState<OperationStatus>('idle')
  const [events, setEvents] = useState<TraceEvent[]>([])
  const [result, setResult] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [upload, setUpload] = useState<number | null>(null)
  const controller = useRef<AbortController | null>(null)

  const run = useCallback(
    async (body: FormData | object): Promise<T | null> => {
      controller.current?.abort()
      const abort = new AbortController()
      controller.current = abort
      setStatus('running')
      setEvents([])
      setResult(null)
      setError(null)
      setUpload(body instanceof FormData ? 0 : null)
      try {
        const data = await streamOperation<T>(
          path,
          body,
          (event) => setEvents((prev) => [...prev, event]),
          abort.signal,
          body instanceof FormData ? setUpload : undefined,
        )
        setResult(data)
        setStatus('success')
        return data
      } catch (err) {
        if ((err as Error).name === 'AbortError') {
          setStatus('idle')
          return null
        }
        const apiErr = err instanceof ApiError ? err : new ApiError(0, 'unknown', (err as Error).message)
        setError(apiErr)
        setStatus('error')
        return null
      }
    },
    [path],
  )

  const reset = useCallback(() => {
    controller.current?.abort()
    setStatus('idle')
    setEvents([])
    setResult(null)
    setError(null)
    setUpload(null)
  }, [])

  useEffect(() => () => controller.current?.abort(), [])
  return { status, events, result, error, run, reset, upload }
}

/** Simple GET with loading/error state and manual reload. */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState<boolean>(path !== null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (path === null) {
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    api<T>(path)
      .then((value) => !cancelled && setData(value))
      .catch((err: ApiError) => !cancelled && setError(err))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps])

  return { data, error, loading, reload: () => setTick((t) => t + 1), setData }
}

/** Object URL for an owner-checked artifact (images need the Authorization header). */
export function useArtifactUrl(artifactId: string | null | undefined): { url: string | null; error: boolean } {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    if (!artifactId) {
      setUrl(null)
      return
    }
    let objectUrl: string | null = null
    let cancelled = false
    setError(false)
    apiBlob(`/api/artifacts/${artifactId}`)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch(() => !cancelled && setError(true))
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [artifactId])
  return { url, error }
}

export async function downloadArtifact(artifactId: string, fallbackName: string): Promise<void> {
  const blob = await apiBlob(`/api/artifacts/${artifactId}?download=true`)
  saveBlob(blob, fallbackName)
}

export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : false,
  )
  useEffect(() => {
    if (!window.matchMedia) return
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const handler = () => setReduced(mq.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  return reduced
}

/** Heuristic device tier for 3D quality: 'low' on small screens / few cores / save-data. */
export function useDeviceTier(): 'low' | 'high' {
  const [tier] = useState<'low' | 'high'>(() => {
    if (typeof window === 'undefined') return 'low'
    const nav = navigator as Navigator & { deviceMemory?: number; connection?: { saveData?: boolean } }
    const small = window.innerWidth < 768
    const weak = (nav.hardwareConcurrency ?? 4) <= 4 || (nav.deviceMemory ?? 8) <= 4
    return small || weak || nav.connection?.saveData ? 'low' : 'high'
  })
  return tier
}
