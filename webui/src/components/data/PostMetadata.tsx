import { useTranslation } from 'react-i18next'
import type { BrowsePost } from '@/types/dataBrowser'

export function PostAccountMetadata({ post }: { post: BrowsePost }) {
  const { t } = useTranslation('data')
  const missing = t('metadata.missing')
  return <dl className="my-3 grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs leading-6 text-cyber-text-secondary" aria-label={t('metadata.account')}>
    <dt>{t('metadata.accountId')}</dt><dd className="break-all">{post.account_id || missing}</dd>
    <dt>{t('metadata.gender')}</dt><dd>{post.gender || missing}</dd>
    <dt>{t('metadata.verification')}</dt><dd className="max-h-24 overflow-y-auto break-words" tabIndex={0}>{post.verification || missing}</dd>
    <dt>{t('metadata.homepage')}</dt><dd>{post.profile_url
      ? <a href={post.profile_url} target="_blank" rel="noopener noreferrer" className="text-cyber-neon-cyan underline underline-offset-4 focus-visible:ring-2 focus-visible:ring-cyber-neon-cyan">{t('metadata.openHomepage')}</a>
      : missing}</dd>
  </dl>
}

export function PostLocationMetadata({ post }: { post: BrowsePost }) {
  const { t } = useTranslation('data')
  return <dl className="my-3 grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs leading-6 text-cyber-text-secondary" aria-label={t('metadata.location')}>
    <dt>{t('metadata.location')}</dt><dd className="break-words">{post.display_location || t('metadata.missing')}</dd>
    <dt>{t('metadata.source')}</dt><dd>{post.location_source || t('metadata.missing')}</dd>
    {post.post_ip_region && <><dt>{t('metadata.ipRegion')}</dt><dd className="break-words">{post.post_ip_region}</dd></>}
  </dl>
}
