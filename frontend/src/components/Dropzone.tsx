import { AnimatePresence, motion } from 'framer-motion'
import { FileImage, FileUp, X } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState, type DragEvent } from 'react'
import { bytes } from '../lib/format'
import { cx } from './ui'

const IMAGE_EXT = ['png', 'jpg', 'jpeg', 'bmp', 'webp', 'tif', 'tiff']

interface DropzoneProps {
  file: File | null
  onFile: (file: File | null) => void
  accept?: 'image' | 'any'
  maxBytes?: number
  label?: string
  hint?: string
  compact?: boolean
}

/** Drag-and-drop / click / keyboard file picker with client-side pre-validation.
 *  (The server re-validates everything; this only gives instant feedback.) */
export function Dropzone({ file, onFile, accept = 'image', maxBytes = 20 * 1024 * 1024, label = 'Drop an image', hint, compact = false }: DropzoneProps) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [dims, setDims] = useState<string | null>(null)

  useEffect(() => {
    if (!file || accept !== 'image') {
      setPreview(null)
      setDims(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreview(url)
    const img = new Image()
    img.onload = () => setDims(`${img.naturalWidth}×${img.naturalHeight}`)
    img.src = url
    return () => URL.revokeObjectURL(url)
  }, [file, accept])

  const take = useCallback(
    (candidate: File | undefined) => {
      if (!candidate) return
      const ext = candidate.name.split('.').pop()?.toLowerCase() ?? ''
      if (accept === 'image' && !IMAGE_EXT.includes(ext)) {
        setProblem(`.${ext || '?'} is not supported — use PNG, JPEG, BMP, WEBP or TIFF`)
        return
      }
      if (candidate.size > maxBytes) {
        setProblem(`File is ${bytes(candidate.size)}; the limit is ${bytes(maxBytes)}`)
        return
      }
      if (candidate.size === 0) {
        setProblem('File is empty')
        return
      }
      setProblem(null)
      onFile(candidate)
    },
    [accept, maxBytes, onFile],
  )

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    take(e.dataTransfer.files?.[0])
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cx(
          'bracket relative overflow-hidden rounded-xs border border-dashed transition-colors',
          dragging ? 'border-accent bg-accent/6' : 'border-line-strong bg-bg hover:border-ink-4',
          compact ? 'min-h-24' : 'min-h-44',
        )}
      >
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          className="sr-only"
          accept={accept === 'image' ? IMAGE_EXT.map((e) => `.${e}`).join(',') : undefined}
          onChange={(e) => {
            take(e.target.files?.[0])
            e.target.value = ''
          }}
        />
        <AnimatePresence mode="wait">
          {file ? (
            <motion.div key="file" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex h-full items-center gap-4 p-3">
              {preview ? (
                <img src={preview} alt="Selected file preview" className={cx('checker shrink-0 rounded-xs border border-line object-contain', compact ? 'size-16' : 'size-28')} />
              ) : (
                <div className="grid size-16 shrink-0 place-items-center rounded-xs border border-line bg-raised">
                  <FileImage className="size-6 text-ink-3" aria-hidden />
                </div>
              )}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">{file.name}</p>
                <p className="mt-1 font-mono text-xs text-ink-3">
                  {bytes(file.size)} · {file.type || 'unknown type'}
                  {dims && ` · ${dims}`}
                </p>
                <div className="mt-2 flex gap-2">
                  <label htmlFor={inputId} className="cursor-pointer font-mono text-[11px] tracking-wider text-accent uppercase hover:underline">
                    Replace
                  </label>
                </div>
              </div>
              <button type="button" onClick={() => onFile(null)} className="rounded-xs p-1.5 text-ink-3 hover:bg-raised hover:text-ink" aria-label="Remove file">
                <X className="size-4" />
              </button>
            </motion.div>
          ) : (
            <motion.label
              key="empty"
              htmlFor={inputId}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className={cx('flex h-full cursor-pointer flex-col items-center justify-center gap-2 p-4 text-center', compact ? 'min-h-24' : 'min-h-44')}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  inputRef.current?.click()
                }
              }}
              tabIndex={0}
            >
              <motion.div animate={dragging ? { y: -4, scale: 1.08 } : { y: 0, scale: 1 }}>
                <FileUp className={cx('size-6', dragging ? 'text-accent' : 'text-ink-3')} aria-hidden />
              </motion.div>
              <span className="text-sm text-ink">{dragging ? 'Release to load' : label}</span>
              <span className="font-mono text-[11px] text-ink-3">{hint ?? (accept === 'image' ? 'PNG · JPEG · BMP · WEBP · TIFF — or click to browse' : 'Any file — or click to browse')}</span>
            </motion.label>
          )}
        </AnimatePresence>
      </div>
      {problem && (
        <p role="alert" className="text-xs text-critical-ink">
          {problem}
        </p>
      )}
    </div>
  )
}
