import { ImageOff } from 'lucide-react'
import { useArtifactUrl } from '../lib/hooks'
import { Skeleton, cx } from './ui'

/** Renders an owner-checked artifact (fetched with the bearer token). */
export function ArtifactImage({ id, alt, className, pixelated = false }: { id: string | null | undefined; alt: string; className?: string; pixelated?: boolean }) {
  const { url, error } = useArtifactUrl(id)
  if (error)
    return (
      <div className={cx('grid place-items-center gap-1 bg-raised p-4 text-center', className)}>
        <ImageOff className="size-5 text-ink-4" aria-hidden />
        <span className="font-mono text-[10px] text-ink-4 uppercase">Artifact expired</span>
      </div>
    )
  if (!url) return <Skeleton className={className} />
  return <img src={url} alt={alt} className={cx('object-contain', pixelated && 'pixelated', className)} draggable={false} />
}
