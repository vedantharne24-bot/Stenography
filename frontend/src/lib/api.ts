/*
 * API client.
 * - The access token lives only in memory (never localStorage); the refresh token is an
 *   httpOnly SameSite=Strict cookie the browser sends to /api/auth/refresh.
 * - A 401 with an expired/invalid token triggers one silent refresh + retry.
 * - Long operations are read as NDJSON streams so the console shows real backend events.
 */
import type { ApiErrorBody, TokenResponse, TraceEvent } from './types'

let accessToken: string | null = null
let refreshing: Promise<TokenResponse | null> | null = null
let onSessionLost: (() => void) | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function setSessionLostHandler(handler: () => void): void {
  onSessionLost = handler
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

const CSRF_HEADERS = { 'X-Requested-With': 'stegolab' }

async function parseError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as ApiErrorBody
    if (body?.error) return new ApiError(response.status, body.error.code, body.error.message, body.error.details ?? {})
  } catch {
    /* non-JSON error */
  }
  const fallback = response.status === 0 ? 'Network error - is the API running?' : `Request failed (${response.status})`
  return new ApiError(response.status, 'http_error', fallback)
}

export async function refreshSession(): Promise<TokenResponse | null> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const response = await fetch('/api/auth/refresh', { method: 'POST', headers: CSRF_HEADERS, credentials: 'same-origin' })
        if (!response.ok) return null
        const data = (await response.json()) as TokenResponse
        accessToken = data.access_token
        return data
      } catch {
        return null
      } finally {
        setTimeout(() => {
          refreshing = null
        }, 0)
      }
    })()
  }
  return refreshing
}

async function rawFetch(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  let response: Response
  try {
    response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'network_error', 'Network error - the StegoLab API is unreachable.')
  }
  if (response.status === 401 && retry && !path.startsWith('/api/auth/')) {
    const refreshed = await refreshSession()
    if (refreshed) return rawFetch(path, init, false)
    onSessionLost?.()
  }
  return response
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init
  const options: RequestInit = { ...rest }
  if (json !== undefined) {
    options.body = JSON.stringify(json)
    options.headers = { 'Content-Type': 'application/json', ...(rest.headers ?? {}) }
  }
  const response = await rawFetch(path, options)
  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function apiBlob(path: string): Promise<Blob> {
  const response = await rawFetch(path)
  if (!response.ok) throw await parseError(response)
  return response.blob()
}

export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return rawFetch(path, init)
}

export const authApi = {
  login: (email: string, password: string) =>
    api<TokenResponse>('/api/auth/login', { method: 'POST', json: { email, password } }),
  register: (name: string, email: string, password: string) =>
    api<TokenResponse>('/api/auth/register', { method: 'POST', json: { name, email, password } }),
  logout: () => api<void>('/api/auth/logout', { method: 'POST', headers: CSRF_HEADERS }),
}

type StreamLine<T> = { type: string; data?: T; error?: ApiErrorBody['error']; status?: number } & TraceEvent

/** Parse complete NDJSON lines from ``buffer``; returns the unconsumed remainder. */
function consumeLines<T>(buffer: string, onEvent: (event: TraceEvent) => void, sink: { result?: T }): string {
  let newline = buffer.indexOf('\n')
  while (newline >= 0) {
    const line = buffer.slice(0, newline).trim()
    buffer = buffer.slice(newline + 1)
    newline = buffer.indexOf('\n')
    if (!line) continue
    const event = JSON.parse(line) as StreamLine<T>
    if (event.type === 'log') onEvent(event)
    else if (event.type === 'result') sink.result = event.data
    else if (event.type === 'error' && event.error) {
      throw new ApiError(event.status ?? 500, event.error.code, event.error.message, event.error.details ?? {})
    }
  }
  return buffer
}

/** XHR transport for multipart uploads: same NDJSON protocol, plus upload progress (fetch cannot report it). */
function xhrStream<T>(path: string, body: FormData, onEvent: (e: TraceEvent) => void, onUpload: (fraction: number) => void, signal?: AbortSignal, retry = true): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const sink: { result?: T } = {}
    let consumed = 0
    let buffer = ''
    let failed = false
    xhr.open('POST', path)
    xhr.withCredentials = true
    xhr.setRequestHeader('Accept', 'application/x-ndjson')
    if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`)
    xhr.upload.onprogress = (e) => e.lengthComputable && onUpload(e.loaded / e.total)
    xhr.upload.onload = () => onUpload(1)
    const pump = () => {
      if (xhr.status !== 200 || failed) return
      buffer += xhr.responseText.slice(consumed)
      consumed = xhr.responseText.length
      try {
        buffer = consumeLines(buffer, onEvent, sink)
      } catch (err) {
        failed = true
        xhr.abort()
        reject(err)
      }
    }
    xhr.onprogress = pump
    xhr.onload = async () => {
      if (failed) return
      if (xhr.status === 401 && retry) {
        const refreshed = await refreshSession()
        if (refreshed) return xhrStream<T>(path, body, onEvent, onUpload, signal, false).then(resolve, reject)
        onSessionLost?.()
      }
      if (xhr.status !== 200) {
        try {
          const parsed = JSON.parse(xhr.responseText) as ApiErrorBody
          reject(new ApiError(xhr.status, parsed.error.code, parsed.error.message, parsed.error.details ?? {}))
        } catch {
          reject(new ApiError(xhr.status, 'http_error', `Request failed (${xhr.status})`))
        }
        return
      }
      pump()
      if (failed) return
      if (sink.result === undefined) reject(new ApiError(500, 'stream_incomplete', 'The operation ended without a result'))
      else resolve(sink.result)
    }
    xhr.onerror = () => reject(new ApiError(0, 'network_error', 'Network error - the StegoLab API is unreachable.'))
    signal?.addEventListener('abort', () => {
      xhr.abort()
      reject(new DOMException('Aborted', 'AbortError'))
    })
    xhr.send(body)
  })
}

/** Run a streaming operation; ``onEvent`` receives each backend log event as it happens.
 *  Pass ``onUpload`` to receive upload progress for multipart bodies. */
export async function streamOperation<T>(
  path: string,
  body: FormData | object,
  onEvent: (event: TraceEvent) => void,
  signal?: AbortSignal,
  onUpload?: (fraction: number) => void,
): Promise<T> {
  if (onUpload && body instanceof FormData && typeof XMLHttpRequest !== 'undefined') {
    return xhrStream<T>(path, body, onEvent, onUpload, signal)
  }
  const isForm = body instanceof FormData
  const response = await rawFetch(path, {
    method: 'POST',
    body: isForm ? body : JSON.stringify(body),
    headers: { Accept: 'application/x-ndjson', ...(isForm ? {} : { 'Content-Type': 'application/json' }) },
    signal,
  })
  if (!response.ok) throw await parseError(response)
  if (!response.body) throw new ApiError(500, 'no_stream', 'Streaming not supported by this browser')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const sink: { result?: T } = {}
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (value) buffer += decoder.decode(value, { stream: !done })
    buffer = consumeLines(buffer, onEvent, sink)
    if (done) break
  }
  if (sink.result === undefined) throw new ApiError(500, 'stream_incomplete', 'The operation ended without a result')
  return sink.result
}
