import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, setAccessToken, streamOperation } from '../lib/api'
import type { TraceEvent } from '../lib/types'

function ndjsonResponse(lines: object[], status = 200): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      // Split mid-line on purpose to exercise the buffering logic.
      const text = lines.map((l) => JSON.stringify(l)).join('\n') + '\n'
      const cut = Math.floor(text.length / 2)
      controller.enqueue(encoder.encode(text.slice(0, cut)))
      controller.enqueue(encoder.encode(text.slice(cut)))
      controller.close()
    },
  })
  return new Response(body, { status, headers: { 'Content-Type': 'application/x-ndjson' } })
}

const log = (message: string): TraceEvent => ({ type: 'log', ts: '2026-01-01T00:00:00.000Z', elapsed_ms: 1, stage: 'test', level: 'info', message })

afterEach(() => {
  vi.restoreAllMocks()
  setAccessToken(null)
})

describe('streamOperation', () => {
  it('delivers each backend event in order and returns the result', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ndjsonResponse([log('one'), log('two'), { type: 'result', data: { ok: 42 } }]))
    const seen: string[] = []
    const result = await streamOperation<{ ok: number }>('/api/x', new FormData(), (e) => seen.push(e.message))
    expect(seen).toEqual(['one', 'two'])
    expect(result).toEqual({ ok: 42 })
  })

  it('turns an error event into an ApiError with the backend code', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      ndjsonResponse([log('validating'), { type: 'error', status: 422, error: { code: 'insufficient_capacity', message: 'too big', details: {} } }]),
    )
    await expect(streamOperation('/api/x', new FormData(), () => undefined)).rejects.toMatchObject({ status: 422, code: 'insufficient_capacity' })
  })

  it('sends the bearer token and NDJSON accept header', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(ndjsonResponse([{ type: 'result', data: 1 }]))
    setAccessToken('token-abc')
    await streamOperation('/api/x', { a: 1 }, () => undefined)
    const headers = new Headers((spy.mock.calls[0][1] as RequestInit).headers)
    expect(headers.get('Authorization')).toBe('Bearer token-abc')
    expect(headers.get('Accept')).toBe('application/x-ndjson')
    expect(headers.get('Content-Type')).toBe('application/json')
  })
})

describe('api', () => {
  it('refreshes once on 401 and retries the original request', async () => {
    const spy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: 'token_expired', message: 'expired' } }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'fresh', token_type: 'bearer', expires_in: 900, user: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ value: 7 }), { status: 200 }))
    const data = await api<{ value: number }>('/api/dashboard/stats')
    expect(data.value).toBe(7)
    expect(spy.mock.calls[1][0]).toBe('/api/auth/refresh')
    expect(new Headers((spy.mock.calls[1][1] as RequestInit).headers).get('X-Requested-With')).toBe('stegolab')
    expect(new Headers((spy.mock.calls[2][1] as RequestInit).headers).get('Authorization')).toBe('Bearer fresh')
  })

  it('maps structured error bodies to ApiError', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { code: 'forbidden', message: 'nope', details: { x: 1 } } }), { status: 403 }))
    const err = await api('/api/audit-logs').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 403, code: 'forbidden', message: 'nope' })
  })
})
