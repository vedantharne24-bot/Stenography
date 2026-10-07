import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ProbabilityBars } from '../components/charts'
import { CompareSlider } from '../components/CompareSlider'
import { TerminalLog } from '../components/TerminalLog'
import { RiskBadge } from '../components/ui'
import { AuthProvider } from '../lib/auth'
import { bytes, pct, shortHash } from '../lib/format'
import Register from '../pages/Register'

describe('format helpers', () => {
  it('formats percentages, bytes and hashes', () => {
    expect(pct(0.9171)).toBe('91.7%')
    expect(pct(null)).toBe('—')
    expect(bytes(512)).toBe('512 B')
    expect(bytes(2048)).toBe('2.0 KB')
    expect(shortHash('a'.repeat(60) + 'beef', 6)).toBe('aaaaaa…beef')
  })
})

describe('TerminalLog', () => {
  it('renders backend events with server timestamps and stage', () => {
    render(
      <TerminalLog
        status="success"
        events={[{ type: 'log', ts: '2026-10-07T21:41:03.000Z', elapsed_ms: 10, stage: 'inference', level: 'info', message: 'LSB probability: 0.917', data: { duration_ms: 42 } }]}
      />,
    )
    const logEl = screen.getByRole('log')
    expect(within(logEl).getByText(/LSB probability: 0.917/)).toBeInTheDocument()
    expect(within(logEl).getByText('inference')).toBeInTheDocument()
    expect(within(logEl).getByText('(42 ms)')).toBeInTheDocument()
  })
})

describe('ProbabilityBars', () => {
  it('labels every class with its probability (identity never colour-only)', () => {
    render(<ProbabilityBars probs={{ normal: 0.021, lsb: 0.917, dct: 0.042, dwt: 0.02 }} highlight="lsb" />)
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(4)
    expect(items[1]).toHaveTextContent('LSB')
    expect(items[1]).toHaveTextContent('91.7%')
  })
})

describe('RiskBadge', () => {
  it('shows the level as text, not colour alone', () => {
    render(<RiskBadge level="HIGH" score={72.4} />)
    expect(screen.getByText('HIGH')).toBeInTheDocument()
    expect(screen.getByText(/72.4/)).toBeInTheDocument()
  })
})

describe('CompareSlider', () => {
  it('is keyboard operable', () => {
    render(<CompareSlider before="data:image/png;base64,AA==" after="data:image/png;base64,AA==" />)
    const slider = screen.getByRole('slider')
    expect(slider).toHaveAttribute('aria-valuenow', '50')
    fireEvent.keyDown(slider, { key: 'ArrowRight' })
    expect(slider).toHaveAttribute('aria-valuenow', '52')
    fireEvent.keyDown(slider, { key: 'ArrowLeft', shiftKey: true })
    expect(slider).toHaveAttribute('aria-valuenow', '42')
  })
})

describe('Register', () => {
  it('mirrors the server password policy and blocks weak submissions', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
    render(
      <MemoryRouter>
        <AuthProvider>
          <Register />
        </AuthProvider>
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    const submit = await screen.findByRole('button', { name: /create account/i })
    await user.type(screen.getByLabelText('Name'), 'Ada')
    await user.type(screen.getByLabelText('Email'), 'ada@example.com')
    await user.type(screen.getByLabelText('Password'), 'short')
    expect(submit).toBeDisabled()
    expect(screen.getByText('At least 10 characters').parentElement).toHaveTextContent('not met')

    await user.clear(screen.getByLabelText('Password'))
    await user.type(screen.getByLabelText('Password'), 'Correct-Horse-42')
    await user.type(screen.getByLabelText('Confirm password'), 'Correct-Horse-42')
    expect(screen.getByText('At least 10 characters').parentElement).toHaveTextContent('met')
    expect(submit).toBeEnabled()
    vi.restoreAllMocks()
  })
})
