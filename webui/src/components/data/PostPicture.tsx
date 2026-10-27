import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ImageOff } from 'lucide-react'
import { savedImagePreviewUrl } from '@/lib/reviewLoading'
import type { BrowsePost } from '@/types/dataBrowser'

export function PostPicture({ image, index }: { image: BrowsePost['images'][number]; index: number }) {
  const { t } = useTranslation('data')
  const [failed, setFailed] = useState(false)
  return (
    <a href={image.url} target="_blank" rel="noopener noreferrer" className="group block overflow-hidden rounded-lg border border-cyber-border-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-neon-cyan" aria-label={t('browse.openImage', { count: index + 1 })}>
      {failed ? <div className="flex aspect-[4/3] flex-col items-center justify-center gap-2 bg-cyber-bg-tertiary p-4 text-center text-xs text-cyber-text-secondary"><ImageOff className="h-6 w-6" />{t('browse.imageFailed')}</div>
        : <img src={savedImagePreviewUrl(image)} alt={t('browse.picture', { count: index + 1 })} loading="lazy" decoding="async" referrerPolicy="no-referrer" className="aspect-[4/3] w-full bg-cyber-bg-tertiary object-contain transition-opacity group-hover:opacity-90" onError={() => setFailed(true)} />}
      <span className="block px-3 py-2 text-xs text-cyber-text-secondary">{t('browse.picture', { count: index + 1 })} · {t(image.local ? 'browse.downloaded' : 'browse.remote')}</span>
    </a>
  )
}

