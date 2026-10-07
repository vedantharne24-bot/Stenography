import { Minus, Move, Plus, RotateCcw } from 'lucide-react'
import { useCallback, useRef, useState, type KeyboardEvent, type PointerEvent, type WheelEvent } from 'react'
import { cx } from './ui'

interface CompareSliderProps {
  before: string
  after: string
  beforeLabel?: string
  afterLabel?: string
  className?: string
}

/** Before/after comparison: draggable divider (pointer, touch, keyboard) + zoom & pan for pixel inspection. */
export function CompareSlider({ before, after, beforeLabel = 'Original', afterLabel = 'Stego', className }: CompareSliderProps) {
  const frame = useRef<HTMLDivElement>(null)
  const [split, setSplit] = useState(50)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [mode, setMode] = useState<'split' | 'pan'>('split')
  const drag = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null)

  const clampPan = useCallback((p: { x: number; y: number }, z: number) => {
    const el = frame.current
    if (!el) return p
    const maxX = ((z - 1) * el.clientWidth) / 2
    const maxY = ((z - 1) * el.clientHeight) / 2
    return { x: Math.max(-maxX, Math.min(maxX, p.x)), y: Math.max(-maxY, Math.min(maxY, p.y)) }
  }, [])

  const setZoomTo = (z: number) => {
    const next = Math.max(1, Math.min(12, z))
    setZoom(next)
    setPan((p) => clampPan(p, next))
  }

  const updateSplit = (clientX: number) => {
    const rect = frame.current?.getBoundingClientRect()
    if (!rect) return
    setSplit(Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100)))
  }

  const onPointerDown = (e: PointerEvent) => {
    ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
    if (mode === 'pan' && zoom > 1) drag.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y }
    else updateSplit(e.clientX)
  }
  const onPointerMove = (e: PointerEvent) => {
    if (e.buttons !== 1) return
    if (drag.current) setPan(clampPan({ x: drag.current.panX + e.clientX - drag.current.x, y: drag.current.panY + e.clientY - drag.current.y }, zoom))
    else if (mode === 'split') updateSplit(e.clientX)
  }
  const onWheel = (e: WheelEvent) => {
    if (!e.ctrlKey && !e.metaKey && zoom === 1 && e.deltaY > 0) return
    setZoomTo(zoom * (e.deltaY < 0 ? 1.25 : 0.8))
  }
  const onKey = (e: KeyboardEvent) => {
    const step = e.shiftKey ? 10 : 2
    if (e.key === 'ArrowLeft') setSplit((s) => Math.max(0, s - step))
    else if (e.key === 'ArrowRight') setSplit((s) => Math.min(100, s + step))
    else if (e.key === '+' || e.key === '=') setZoomTo(zoom * 1.25)
    else if (e.key === '-') setZoomTo(zoom * 0.8)
    else return
    e.preventDefault()
  }

  const transform = { transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transformOrigin: 'center' }
  const imgClass = cx('absolute inset-0 h-full w-full object-contain select-none', zoom >= 3 && 'pixelated')

  return (
    <div className={cx('flex flex-col gap-2', className)}>
      <div
        ref={frame}
        className={cx('checker relative aspect-square w-full touch-none overflow-hidden rounded-xs border border-line sm:aspect-[4/3]', mode === 'pan' && zoom > 1 ? 'cursor-grab' : 'cursor-ew-resize')}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={() => (drag.current = null)}
        onWheel={onWheel}
        onKeyDown={onKey}
        tabIndex={0}
        role="slider"
        aria-label={`Comparison divider between ${beforeLabel} and ${afterLabel}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(split)}
      >
        <div className="absolute inset-0" style={transform}>
          <img src={after} alt={afterLabel} className={imgClass} draggable={false} />
        </div>
        <div className="absolute inset-0" style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}>
          <div className="absolute inset-0" style={transform}>
            <img src={before} alt={beforeLabel} className={imgClass} draggable={false} />
          </div>
        </div>
        <div className="pointer-events-none absolute inset-y-0 w-px bg-accent shadow-[0_0_12px_var(--color-accent)]" style={{ left: `${split}%` }}>
          <div className="absolute top-1/2 left-1/2 grid size-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-accent bg-bg/80 font-mono text-[10px] text-accent">⇆</div>
        </div>
        <span className="pointer-events-none absolute top-2 left-2 rounded-xs bg-bg/80 px-1.5 py-0.5 font-mono text-[10px] tracking-wider text-ink uppercase">{beforeLabel}</span>
        <span className="pointer-events-none absolute top-2 right-2 rounded-xs bg-bg/80 px-1.5 py-0.5 font-mono text-[10px] tracking-wider text-ink uppercase">{afterLabel}</span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <button type="button" className="rounded-xs border border-line p-1.5 text-ink-2 hover:text-ink" onClick={() => setZoomTo(zoom * 0.8)} aria-label="Zoom out">
            <Minus className="size-3.5" />
          </button>
          <span className="w-14 text-center font-mono text-xs text-ink-2 tabular">{zoom.toFixed(1)}×</span>
          <button type="button" className="rounded-xs border border-line p-1.5 text-ink-2 hover:text-ink" onClick={() => setZoomTo(zoom * 1.25)} aria-label="Zoom in">
            <Plus className="size-3.5" />
          </button>
          <button
            type="button"
            className={cx('ml-1 rounded-xs border p-1.5', mode === 'pan' ? 'border-accent text-accent' : 'border-line text-ink-2 hover:text-ink')}
            onClick={() => setMode((m) => (m === 'pan' ? 'split' : 'pan'))}
            aria-pressed={mode === 'pan'}
            aria-label="Toggle pan mode"
          >
            <Move className="size-3.5" />
          </button>
          <button
            type="button"
            className="rounded-xs border border-line p-1.5 text-ink-2 hover:text-ink"
            onClick={() => {
              setZoom(1)
              setPan({ x: 0, y: 0 })
              setSplit(50)
            }}
            aria-label="Reset view"
          >
            <RotateCcw className="size-3.5" />
          </button>
        </div>
        <span className="font-mono text-[10px] text-ink-4">drag divider · ctrl+wheel zoom · ← → keys</span>
      </div>
    </div>
  )
}
