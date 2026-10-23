import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, ChevronRight, ExternalLink, ImageOff, Search } from 'lucide-react'
import { dataApi } from '@/lib/api'
import { savedImagePreviewUrl } from '@/lib/reviewLoading'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { BrowsePost } from '@/types/dataBrowser'
import { PostAccountMetadata, PostLocationMetadata } from './PostMetadata'

function Highlight({ value, query }: { value: string; query: string }) {
  const terms = query.split(/\s+/).filter(Boolean).sort((a, b) => b.length - a.length)
  if (!terms.length) return <>{value}</>
  const pattern = terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
  return <>{value.split(new RegExp(`(${pattern})`, 'gi')).map((part, i) => terms.some((term) => term.toLowerCase() === part.toLowerCase())
    ? <mark key={i} className="rounded-sm bg-cyber-neon-cyan/15 px-0.5 text-inherit">{part}</mark>
    : part)}</>
}

function Picture({ image, index }: { image: BrowsePost['images'][number]; index: number }) {
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

function ImageStatus({ post }: { post: BrowsePost }) {
  const { t } = useTranslation('data')
  // Older running API instances may not yet return download metadata.
  const status = post.image_download_status || (post.images.length ? (post.images.every((image) => image.local) ? 'downloaded' : 'not_downloaded') : 'unknown')
  return <>{t(`browse.imageStatus.${status}`, {
    count: post.image_count ?? post.images.length,
    downloaded: post.downloaded_image_count ?? post.images.filter((image) => image.local).length,
  })}</>
}

function PostDetail({ post }: { post: BrowsePost }) {
  const { t } = useTranslation('data')
  return (
    <article className="min-w-0 space-y-7 p-4 md:p-6" aria-label={t('browse.detail')}>
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-cyber-text-secondary">
          <span className="rounded bg-cyber-bg-tertiary px-2 py-1">{t(post.status === 'matched' && post.selection_origin === 'user_confirmed' ? 'browse.userConfirmed' : post.status === 'matched' && post.selection_origin === 'review_policy' ? 'browse.reviewPolicyPassed' : post.status === 'matched' && post.selection_origin === 'jev_initial_screen' ? 'browse.jevPassed' : `browse.status.${post.status}`, { defaultValue: post.status })}</span>
          {post.source_keyword && <span>{post.source_keyword}</span>}
          {post.published_at && <span>{post.published_at}</span>}
          {post.nickname && <span>{post.nickname}</span>}
        </div>
        {post.status === 'matched' && <p className="text-xs leading-6 text-cyber-text-secondary">{t('browse.manualReviewHint')}{post.jev_original_choice && ` · ${t('browse.originalDecision', { choice: t(`browse.modelChoice.${post.jev_original_choice}`, { defaultValue: post.jev_original_choice }) })}`}</p>}
        <PostAccountMetadata post={post} />
        <PostLocationMetadata post={post} />
        <h3 className="break-words text-xl font-semibold leading-relaxed text-cyber-text-primary">{post.title || t('browse.noTitle')}</h3>
        {post.url ? <a href={post.url} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-full items-start gap-2 break-all text-sm text-cyber-neon-cyan underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-neon-cyan"><ExternalLink className="mt-0.5 h-4 w-4 shrink-0" />{post.url}</a>
          : <p className="text-sm text-cyber-text-secondary">{t('browse.noLink')}</p>}
        <p className="text-xs text-cyber-text-secondary">{t('browse.postId')}: <span className="font-mono">{post.id}</span></p>
        <nav aria-label={t('browse.jump')} className="flex flex-wrap gap-4 text-xs text-cyber-text-secondary">{[['browse-content', 'content'], ['browse-comments', 'hitComments'], ['browse-images', 'images']].map(([id, label]) => <a key={id} href={`#${id}`} onClick={(event) => { event.preventDefault(); event.currentTarget.closest('article')?.querySelector(`#${id}`)?.scrollIntoView({ block: 'start' }) }} className="rounded underline underline-offset-4 hover:text-cyber-neon-cyan focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-neon-cyan">{t(`browse.${label}`)}</a>)}</nav>
      </header>
      <section id="browse-content" className="scroll-mt-4 space-y-2">
        <h4 className="text-sm font-semibold text-cyber-text-primary">{t('browse.content')}</h4>
        <p className="max-w-[75ch] whitespace-pre-wrap break-words text-sm leading-7 text-cyber-text-primary"><Highlight value={post.content || t('browse.noContent')} query={post.source_keyword} /></p>
      </section>
      <section id="browse-comments" className="scroll-mt-4 space-y-3 border-t border-cyber-border-subtle pt-5">
        <h4 className="text-sm font-semibold text-cyber-text-primary">{t('browse.hitComments')} <span className="font-normal text-cyber-text-secondary">({post.hit_comments.length})</span></h4>
        {post.hit_comments.length ? <ul className="space-y-4">{post.hit_comments.map((comment) => <li key={`${comment.id}:${comment.content}`} className="space-y-1.5">
          <span className="text-xs text-cyber-text-secondary">{t(comment.kind === 'semantic' ? 'browse.semanticHit' : 'browse.keywordHit')}{comment.nickname && ` · ${comment.nickname}`}</span>
          <p className="max-w-[75ch] whitespace-pre-wrap break-words text-sm leading-7 text-cyber-text-primary"><Highlight value={comment.content} query={post.source_keyword} /></p>
        </li>)}</ul> : <p className="text-sm leading-6 text-cyber-text-secondary">{t('browse.noHitComments')}</p>}
        {!!post.comments.length && <details className="text-sm"><summary className="cursor-pointer rounded text-cyber-text-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-neon-cyan">{t('browse.allComments', { count: post.comments.length })}</summary><ul className="mt-3 space-y-3">{post.comments.map((comment) => <li key={`${comment.id}:${comment.content}`} className="whitespace-pre-wrap break-words leading-6 text-cyber-text-primary">{comment.content}</li>)}</ul></details>}
      </section>
      {!!post.evidence && <details className="border-t border-cyber-border-subtle pt-5 text-sm"><summary className="cursor-pointer rounded text-cyber-text-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-neon-cyan">{t('browse.evidence')}</summary><p className="mt-2 whitespace-pre-wrap break-words leading-6 text-cyber-text-primary">{post.evidence}</p></details>}
      <section id="browse-images" className="scroll-mt-4 space-y-3 border-t border-cyber-border-subtle pt-5">
        <h4 className="text-sm font-semibold text-cyber-text-primary">{t('browse.images')}</h4>
        <p className="text-sm leading-6 text-cyber-text-secondary"><ImageStatus post={post} /></p>
        {post.url && ['not_downloaded', 'partial'].includes(post.image_download_status) && <a href={post.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded text-sm text-cyber-neon-cyan underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-neon-cyan"><ExternalLink className="h-4 w-4" />{t('browse.viewOriginalImages')}</a>}
        {post.images.length ? <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">{post.images.map((image, index) => <Picture key={image.url} image={image} index={index} />)}</div>
          : !post.image_download_status && <p className="text-sm leading-6 text-cyber-text-secondary">{t('browse.noImages')}</p>}
      </section>
    </article>
  )
}

export function DataBrowser({ initialFile = '' }: { initialFile?: string }) {
  const { t } = useTranslation('data')
  const [chosenFile, setChosenFile] = useState(initialFile)
  const [draft, setDraft] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState(0)
  const [showList, setShowList] = useState(false)
  const { data: files, isLoading: loadingFiles, error: filesError, refetch: refetchFiles } = useQuery({ queryKey: ['dataFiles'], queryFn: async () => (await dataApi.getFiles()).data.files })
  const postFiles = (files || []).filter((file) => !/(comment|creator|guard_replay|semantic_checkpoint)/i.test(file.name))
  const currentFile = postFiles.some((file) => file.path === chosenFile) ? chosenFile : postFiles.find((file) => !file.name.includes('_semantic'))?.path || postFiles[0]?.path || ''
  useEffect(() => {
    if (draft === search) return
    const timer = setTimeout(() => { setSearch(draft); setOffset(0); setSelected(0) }, 250)
    return () => clearTimeout(timer)
  }, [draft, search])
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['dataBrowse', currentFile, offset, search, status],
    queryFn: async () => (await dataApi.browse(currentFile, offset, search, status)).data,
    enabled: !!currentFile,
  })
  const post = data?.posts[Math.min(selected, data.posts.length - 1)]
  const resetSelection = () => { setOffset(0); setSelected(0) }
  const selectClass = 'h-9 min-w-0 rounded-md border border-cyber-border-DEFAULT bg-cyber-bg-panel px-3 text-sm text-cyber-text-primary focus:outline-none focus:ring-2 focus:ring-cyber-neon-cyan'
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4" aria-label={t('browse.title')}>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto]">
        <label className="flex min-w-0 flex-col gap-1.5 text-xs text-cyber-text-secondary">{t('browse.batch')}<select aria-label={t('browse.batch')} value={currentFile} className={selectClass} onChange={(event) => { setChosenFile(event.target.value); resetSelection() }}><option value="" disabled>{t('browse.chooseBatch')}</option>{postFiles.map((file) => <option key={file.path} value={file.path}>{file.name}</option>)}</select></label>
        <label className="flex min-w-0 flex-col gap-1.5 text-xs text-cyber-text-secondary">{t('browse.search')}<div className="relative"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4" /><Input aria-label={t('browse.search')} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={t('browse.searchPlaceholder')} className="h-9 pl-9 text-sm" /></div></label>
        <label className="flex flex-col gap-1.5 text-xs text-cyber-text-secondary">{t('browse.filter')}<select aria-label={t('browse.filter')} value={status} className={selectClass} onChange={(event) => { setStatus(event.target.value); resetSelection() }}>{['all', 'matched', 'review', 'pending', 'duplicate', 'unfiltered'].map((value) => <option key={value} value={value}>{t(`browse.status.${value}`)}</option>)}</select></label>
      </div>
      {loadingFiles || isLoading ? <div role="status" aria-label={t('browse.loading')} className="flex-1 space-y-4 overflow-hidden rounded-lg border border-cyber-border-subtle p-6"><div className="h-5 w-2/3 animate-pulse rounded bg-cyber-bg-tertiary" /><div className="h-32 animate-pulse rounded bg-cyber-bg-tertiary" /><p className="text-sm text-cyber-text-secondary">{t('browse.loading')}</p></div>
        : filesError || error ? <div role="alert" className="space-y-3 rounded-lg border border-cyber-border-subtle p-6"><p className="text-sm text-cyber-text-primary">{t('browse.error')}</p><Button size="sm" variant="outline" onClick={() => { if (filesError) void refetchFiles(); else void refetch() }}>{t('browse.retry')}</Button></div>
        : !currentFile ? <div className="py-14 text-center text-sm leading-7 text-cyber-text-secondary">{t('browse.empty')}</div>
        : <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-cyber-text-secondary"><span aria-live="polite">{t('browse.resultCount', { count: data?.total || 0 })}{isFetching && ` · ${t('browse.updating')}`}</span><span>{t('browse.batchCounts', { matched: data?.counts.matched || 0, review: data?.counts.review || 0 })}</span></div>
          {!!post && <button type="button" className="rounded-md border border-cyber-border-subtle px-3 py-2 text-left text-sm text-cyber-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-neon-cyan md:hidden" aria-expanded={showList} onClick={() => setShowList(!showList)}>{t(showList ? 'browse.hideList' : 'browse.showList')}</button>}
          {post ? <div className="grid min-h-0 flex-1 overflow-hidden rounded-lg border border-cyber-border-subtle md:grid-cols-[17rem_minmax(0,1fr)]">
            <nav aria-label={t('browse.postList')} className={`${showList ? '' : 'hidden'} max-h-44 overflow-y-auto border-b border-cyber-border-subtle bg-cyber-bg-tertiary/40 md:block md:max-h-none md:border-b-0 md:border-r`}>
              {data?.posts.map((item, index) => <button type="button" key={item.key} onClick={() => { setSelected(index); setShowList(false) }} aria-current={post.key === item.key ? 'true' : undefined} className={`block w-full space-y-2 border-b border-cyber-border-subtle p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyber-neon-cyan ${post.key === item.key ? 'bg-cyber-neon-cyan/10' : 'hover:bg-cyber-bg-tertiary'}`}>
                <div className="flex flex-wrap justify-between gap-2 text-xs text-cyber-text-secondary"><span>{item.index} · {t(`browse.status.${item.status}`, { defaultValue: item.status })}</span><span><ImageStatus post={item} /></span></div><p className="line-clamp-2 break-words text-sm font-medium leading-6 text-cyber-text-primary">{item.title || item.content || item.id}</p><p className="truncate text-xs text-cyber-text-secondary">{item.source_keyword || item.id}</p>
              </button>)}
            </nav><div key={post.key} className="min-h-0 overflow-y-auto"><PostDetail post={post} /></div>
          </div> : <div className="flex-1 py-12 text-center text-sm text-cyber-text-secondary">{t('browse.noMatches')}</div>}
          <div className="flex items-center justify-between gap-3"><Button size="sm" variant="outline" disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - 20)); setSelected(0) }}><ChevronLeft />{t('browse.previous')}</Button><span className="text-xs text-cyber-text-secondary">{t('browse.page', { page: Math.floor(offset / 20) + 1, pages: Math.max(1, Math.ceil((data?.total || 0) / 20)) })}</span><Button size="sm" variant="outline" disabled={!data || offset + 20 >= data.total} onClick={() => { setOffset(offset + 20); setSelected(0) }}>{t('browse.next')}<ChevronRight /></Button></div>
        </>}
    </div>
  )
}
