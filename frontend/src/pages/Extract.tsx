import { motion } from 'framer-motion'
import { Check, Download, Eye, EyeOff, FileDown, KeyRound, Loader2, Minus, ScanLine, X } from 'lucide-react'
import { useState } from 'react'
import { Dropzone } from '../components/Dropzone'
import { TerminalLog } from '../components/TerminalLog'
import { Button, ErrorNotice, Field, Hash, Input, IntegrityBadge, KeyValue, PageHeader, Panel, Segmented, StatusBadge, cx } from '../components/ui'
import { bytes, ms } from '../lib/format'
import { saveBlob, useOperation } from '../lib/hooks'
import type { ExtractResult, TraceEvent } from '../lib/types'

type StepState = 'pending' | 'active' | 'ok' | 'fail' | 'skip'

function stepStates(events: TraceEvent[], result: ExtractResult | null, running: boolean): StepState[] {
  if (result) {
    const found = result.integrity.status !== 'not_found'
    const verified = result.integrity.status === 'verified'
    const dec = result.decryption.status
    return [
      found ? 'ok' : 'fail',
      found ? 'ok' : 'skip',
      found ? (verified ? 'ok' : 'fail') : 'skip',
      dec === 'success' ? 'ok' : dec === 'failed' ? 'fail' : 'skip',
      dec === 'success' ? 'ok' : 'skip',
    ]
  }
  if (!running) return ['pending', 'pending', 'pending', 'pending', 'pending']
  const stages = new Set(events.map((e) => e.stage))
  if (stages.has('crypto')) return ['ok', 'ok', 'ok', 'active', 'pending']
  if (stages.has('integrity')) return ['ok', 'ok', 'active', 'pending', 'pending']
  if (stages.has('detect')) return ['active', 'pending', 'pending', 'pending', 'pending']
  return ['pending', 'pending', 'pending', 'pending', 'pending']
}

const STEPS = ['Detect format', 'Extract payload', 'Verify integrity', 'Decrypt', 'Recover']

function Pipeline({ states }: { states: StepState[] }) {
  return (
    <ol className="grid grid-cols-5 gap-1" aria-label="Extraction pipeline">
      {STEPS.map((label, i) => {
        const s = states[i]
        const Icon = s === 'ok' ? Check : s === 'fail' ? X : s === 'active' ? Loader2 : s === 'skip' ? Minus : ScanLine
        return (
          <li key={label} className="flex flex-col items-center gap-2 text-center">
            <div className="relative flex w-full items-center">
              <div className={cx('h-px flex-1', i === 0 ? 'bg-transparent' : s === 'pending' || s === 'skip' ? 'bg-line' : 'bg-accent/60')} />
              <motion.span
                animate={{ scale: s === 'active' ? [1, 1.08, 1] : 1 }}
                transition={{ repeat: s === 'active' ? Infinity : 0, duration: 1.2 }}
                className={cx(
                  'grid size-9 shrink-0 place-items-center rounded-full border',
                  s === 'ok' && 'border-ok bg-ok/15 text-ok-ink',
                  s === 'fail' && 'border-critical bg-critical/15 text-critical-ink',
                  s === 'active' && 'border-accent text-accent',
                  (s === 'pending' || s === 'skip') && 'border-line-strong text-ink-4',
                )}
              >
                <Icon className={cx('size-4', s === 'active' && 'animate-spin')} aria-hidden />
              </motion.span>
              <div className={cx('h-px flex-1', i === STEPS.length - 1 ? 'bg-transparent' : 'bg-line')} />
            </div>
            <span className={cx('font-mono text-[10px] leading-tight tracking-wider uppercase', s === 'pending' || s === 'skip' ? 'text-ink-4' : 'text-ink-2')}>
              {label}
              <span className="sr-only"> — {s}</span>
            </span>
          </li>
        )
      })}
    </ol>
  )
}

export default function Extract() {
  const [image, setImage] = useState<File | null>(null)
  const [algorithm, setAlgorithm] = useState<'auto' | 'lsb' | 'dct' | 'dwt'>('auto')
  const [secret, setSecret] = useState('')
  const [show, setShow] = useState(false)
  const op = useOperation<ExtractResult>('/api/steganography/extract')
  const states = stepStates(op.events, op.result, op.status === 'running')

  const run = () => {
    if (!image) return
    const form = new FormData()
    form.append('image', image)
    form.append('algorithm', algorithm)
    if (secret) form.append('secret', secret)
    op.run(form)
  }

  return (
    <div>
      <PageHeader
        index="03"
        kicker="Defence · recovery"
        title="Extract"
        description="Recover a hidden payload: the frame is located (format auto-detected), its SHA-256 digest is checked without the key, then AES-256-GCM authenticates and decrypts it. A wrong key fails safely and is audited."
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="flex flex-col gap-6">
          <Panel title="Stego image" index="01" brackets>
            <Dropzone file={image} onFile={setImage} label="Drop a stego image (lossless PNG recommended)" />
          </Panel>
          <Panel title="Decoder & key" index="02">
            <div className="flex flex-col gap-4">
              <Field label="Format">
                <Segmented
                  label="Decoder"
                  value={algorithm}
                  onChange={setAlgorithm}
                  options={[
                    { value: 'auto', label: 'Auto-detect' },
                    { value: 'lsb', label: 'LSB' },
                    { value: 'dct', label: 'DCT' },
                    { value: 'dwt', label: 'DWT' },
                  ]}
                  size="sm"
                />
              </Field>
              <Field label="Passphrase or generated key" htmlFor="secret" hint="Leave empty to only verify integrity. Keys look like slk1_…">
                <div className="relative">
                  <Input id="secret" type={show ? 'text' : 'password'} value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off" className="pr-10 font-mono" />
                  <button type="button" onClick={() => setShow((v) => !v)} className="absolute top-1/2 right-2 -translate-y-1/2 p-1 text-ink-3 hover:text-ink" aria-label={show ? 'Hide key' : 'Show key'}>
                    {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                </div>
              </Field>
              <Button variant="primary" size="lg" icon={KeyRound} onClick={run} disabled={!image || op.status === 'running'} loading={op.status === 'running'}>
                {secret ? 'Extract & decrypt' : 'Extract & verify'}
              </Button>
            </div>
          </Panel>
        </div>

        <div className="flex flex-col gap-6">
          <Panel title="Pipeline" index="03">
            <Pipeline states={states} />
          </Panel>
          <TerminalLog events={op.events} status={op.status} upload={op.upload} title="extract.log" />
          <ErrorNotice error={op.error} title="Extraction failed" />
          {op.result && <ExtractOutcome result={op.result} />}
        </div>
      </div>
    </div>
  )
}

function ExtractOutcome({ result }: { result: ExtractResult }) {
  const payload = result.payload
  const download = () => {
    if (!payload?.content_b64) return
    const raw = atob(payload.content_b64)
    const buf = new Uint8Array(raw.length)
    for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i)
    saveBlob(new Blob([buf]), payload.filename || 'recovered.bin')
  }
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-6">
      <Panel title="Verdict" index="04">
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="label-mono mb-1.5">Frame</p>
            {result.detected_algorithm ? <StatusBadge tone="info">{result.detected_algorithm} frame</StatusBadge> : <StatusBadge tone="neutral">none</StatusBadge>}
          </div>
          <div>
            <p className="label-mono mb-1.5">Integrity</p>
            <IntegrityBadge status={result.integrity.status} />
          </div>
          <div>
            <p className="label-mono mb-1.5">Decryption</p>
            {result.decryption.status === 'success' ? (
              <StatusBadge tone="ok" icon={Check}>Success</StatusBadge>
            ) : result.decryption.status === 'failed' ? (
              <StatusBadge tone="critical">Failed</StatusBadge>
            ) : (
              <StatusBadge tone="neutral">Not attempted</StatusBadge>
            )}
          </div>
        </div>
        {result.decryption.message && <p className="mt-3 text-sm text-ink-2">{result.decryption.message}</p>}
        {result.integrity.notes.map((n) => (
          <p key={n} className="mt-2 text-sm text-ink-3">
            {n}
          </p>
        ))}
      </Panel>

      {payload && (
        <Panel title="Recovered payload" index="05" actions={<StatusBadge tone="ok" icon={Check}>Inner SHA-256 verified</StatusBadge>}>
          {payload.kind === 'text' ? (
            <pre className="max-h-72 overflow-auto rounded-xs border border-line bg-bg p-3 font-mono text-[13px] leading-relaxed whitespace-pre-wrap text-ink">{payload.text}</pre>
          ) : (
            <div className="flex items-center justify-between gap-3 rounded-xs border border-line bg-bg p-3">
              <span className="flex items-center gap-2 text-sm">
                <FileDown className="size-4 text-ink-3" aria-hidden />
                {payload.filename || 'recovered.bin'} <span className="font-mono text-xs text-ink-3">{bytes(payload.size)}</span>
              </span>
              <Button size="sm" variant="primary" icon={Download} onClick={download}>
                Save file
              </Button>
            </div>
          )}
          <div className="mt-3">
            <Hash label="SHA-256" value={payload.content_sha256} />
          </div>
        </Panel>
      )}

      <Panel title="Frame diagnostics" index="06">
        <KeyValue
          rows={[
            ['Decoders tried', result.tried.map((t) => t.toUpperCase()).join(' → ')],
            ['Envelope size', bytes(result.envelope_bytes)],
            ['ECC parity / block', result.integrity.ecc_parity ? `${result.integrity.ecc_parity} symbols` : 'none'],
            ['Symbols corrected', `${result.integrity.header_symbols_corrected} header · ${result.integrity.body_symbols_corrected} body`],
            ['Extraction time', ms(result.timings_ms.extraction)],
          ]}
        />
        {result.integrity.expected_sha256 && (
          <div className="mt-4 flex flex-col gap-2 border-t border-line pt-4">
            <Hash label="Embedded digest" value={result.integrity.expected_sha256} />
            <Hash label="Recomputed" value={result.integrity.actual_sha256} />
          </div>
        )}
      </Panel>
    </motion.div>
  )
}
