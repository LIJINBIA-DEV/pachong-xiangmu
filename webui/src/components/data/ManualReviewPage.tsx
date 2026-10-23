import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ImageOff, Download } from 'lucide-react'
import { ReviewIcon } from './ReviewIcon'
import './ManualReviewPage.css'
import { dataApi } from '@/lib/api'
import { reviewFileSelection } from '@/lib/reviewFiles'
import { applyReviewChange, withReviewOutcomes } from '@/lib/reviewOutcome'
import { reviewPostQueryOptions, savedImagePreviewUrl } from '@/lib/reviewLoading'
import { reviewSaveOptions } from '@/lib/reviewSave'
import type { SavedReviewChange } from '@/lib/reviewSave'
import { KeywordHighlight } from './KeywordHighlight'
import { PostAccountMetadata, PostLocationMetadata } from './PostMetadata'
import { SupplementPanel } from './SupplementPanel'
import { ImageSubjectPanel } from './ImageSubjectPanel'
import { Button } from '@/components/ui/button'
import type { ReviewDecision, ReviewImage } from '@/types/dataBrowser'

type Change = SavedReviewChange
const controlClass = 'review-field'

function readPreference(key: string) {
  try { return localStorage.getItem(key) || '' } catch { return '' }
}

function Choices({ value, positive, negative, disabled, onChange, canReset = true, resetLabel, iconOnly = false }: {
  value: string | null | undefined; positive: string; negative: string; disabled: boolean; onChange: (value: boolean | null) => void; canReset?: boolean; resetLabel?: string; iconOnly?: boolean
}) {
  const { t } = useTranslation('workspace')
  const yes = value === 'qualified' || value === 'non_marketing'
  const no = value === 'unqualified' || value === 'marketing'
  return <div className="review-choices">
    <button type="button" aria-label={positive} title={positive} aria-pressed={yes} disabled={disabled} onClick={() => onChange(true)} className={`review-choice review-choice-yes ${iconOnly ? 'review-choice-icon' : ''}`}><ReviewIcon name={yes ? 'yesSelected' : 'yes'} />{!iconOnly && positive}</button>
    <button type="button" aria-label={negative} title={negative} aria-pressed={no} disabled={disabled} onClick={() => onChange(false)} className={`review-choice review-choice-no ${iconOnly ? 'review-choice-icon' : ''}`}><ReviewIcon name={no ? 'noSelected' : 'no'} />{!iconOnly && negative}</button>
    {canReset && <button type="button" aria-label={resetLabel || t('reset')} title={resetLabel || t('reset')} disabled={disabled} onClick={() => onChange(null)} className="review-choice review-choice-icon"><ReviewIcon name="reset" /></button>}
  </div>
}

function ReviewPicture({ image, index, postUrl, value, disabled, onChange }: { image: ReviewImage; index: number; postUrl: string; value: ReviewDecision | undefined; disabled: boolean; onChange: (value: boolean | null) => void }) {
  const { t } = useTranslation('workspace')
  const [failed, setFailed] = useState(false)
  const subject = image.subject
  const recognized = subject?.status === 'recognized'
  const tone = subject?.suggestion === 'unqualified' ? 'negative' : subject?.suggestion === 'qualified' ? 'positive' : 'pending'
  return <figure className="review-picture">
    <div className="review-picture-media">
      {image.local && image.url && !image.download_problem && !failed ? <a href={image.url} target="_blank" rel="noopener noreferrer" aria-label={t('openImage', { count: index + 1 })}><img src={savedImagePreviewUrl(image)} alt={t('image', { count: index + 1 })} referrerPolicy="no-referrer" loading="lazy" decoding="async" onError={() => setFailed(true)} /></a>
        : <div className="review-picture-placeholder"><ImageOff className="h-6 w-6" /><p>{t(image.decision_source === 'download' ? 'imageSubject.downloadRejected' : image.local ? 'imageFailed' : 'imageNotDownloaded')}</p>{postUrl && <a href={postUrl} target="_blank" rel="noopener noreferrer" className="review-link">{t('openOriginal')}</a>}</div>}
      <span className={`review-state ${value === 'qualified' ? 'review-state-positive' : value === 'unqualified' ? 'review-state-negative' : ''}`}>{t(value || 'unmarked')}</span>
    </div>
    <figcaption className="review-picture-info">
      <p className="review-picture-name" title={`${image.name} · ${t(image.local ? 'downloaded' : 'notDownloaded')}`}>{image.name}</p>
      <Choices value={value} positive={t('imageQualified')} negative={t('imageUnqualified')} disabled={disabled} onChange={onChange} iconOnly />
      <p className={`review-picture-subject review-picture-subject-${tone}`} aria-label={t('imageSubject.result')}>{recognized ? subject.label === '二者都不是' ? t('imageSubject.labels.二者都不是') : `${t('imageSubject.result')}: ${t(`imageSubject.labels.${subject.label}`)}` : t(`imageSubject.imageStatuses.${subject?.status || 'unrecognized'}`)}</p>
      <details className="review-picture-evidence"><summary>{t('imageSubject.reason')}</summary>
        {image.download_problem && <p>{t('imageSubject.downloadRejected')}</p>}
        <p>{t('imageSubject.type')}: {subject?.image_type ? t(`imageSubject.types.${subject.image_type}`) : t('imageSubject.typePending')}</p>
        <p>{subject?.reason}</p><p>{subject?.type_reason}</p>
        {recognized && <p>{image.decision_source === 'manual' ? t('imageSubject.manualOverride', { decision: t(value || 'unmarked') }) : image.decision_source === 'model' ? t('imageSubject.autoMarked', { decision: t(value || 'unmarked') }) : t(subject.policy_status === 'pending' ? 'imageSubject.policyPending' : 'imageSubject.manualRequired')}</p>}
        {subject?.model && <p>{subject.model} · {t(subject.provider === 'siliconflow' ? 'imageSettings.cloud' : 'imageSettings.local')}</p>}
      </details>
    </figcaption>
  </figure>
}

export function ManualReviewPage({ fileRequest }: { fileRequest?: { file: string; id: number } }) {
  const { t } = useTranslation('workspace')
  const { t: td } = useTranslation('data')
  const queryClient = useQueryClient()
  const [chosenFile, setChosenFile] = useState(() => readPreference('mediacrawler_review_file'))
  const [selectedKey, setSelectedKey] = useState(() => readPreference('mediacrawler_review_post'))
  const [filter, setFilter] = useState('all')
  useEffect(() => { if (fileRequest) { setChosenFile(fileRequest.file); setSelectedKey(''); setFilter('all') } }, [fileRequest])
  const [toolsOpen, setToolsOpen] = useState(false)
  const contentRef = useRef<HTMLElement>(null)
  const imagesRef = useRef<HTMLDivElement>(null)
  const contextRef = useRef<HTMLDivElement>(null)
  const [lastChange, setLastChange] = useState<Change | null>(null)
  const filesQuery = useQuery({ queryKey: ['dataFiles'], queryFn: async () => (await dataApi.getFiles()).data.files })
  const { files, currentFile, missingMain } = reviewFileSelection(filesQuery.data || [], chosenFile)
  const reviewQuery = useQuery({ queryKey: ['manualReview', currentFile], queryFn: async () => withReviewOutcomes((await dataApi.getReview(currentFile)).data), enabled: !!currentFile, retry: 1 })
  const save = useMutation(reviewSaveOptions(queryClient,
    async (change) => (await dataApi.saveReview(change.file, change.key, change.kind, change.decision, change.imageKey)).data))
  const exportResult = useMutation({
    mutationFn: async (file: string) => {
      try { return await dataApi.exportReview(file) }
      catch (error) {
        if (axios.isAxiosError(error)) {
          throw new Error(error.response?.data?.detail || 'review_export_failed')
        }
        throw error
      }
    },
  })
  const exportId = exportResult.data?.data.id || ''
  const exportStatus = useQuery({
    queryKey: ['reviewExport', exportId], enabled: !!exportId,
    queryFn: async () => (await dataApi.getReviewExport(exportId)).data,
    refetchInterval: query => !query.state.data || ['queued', 'preparing'].includes(query.state.data.status) ? 1000 : false,
    retry: 1,
  })
  const exportJob = exportStatus.data || exportResult.data?.data
  const exportBusy = exportResult.isPending || (!!exportJob && ['queued', 'preparing'].includes(exportJob.status))
  const exportList = useQuery({
    queryKey: ['reviewExportList'], queryFn: async () => (await dataApi.listReviewExports()).data.jobs,
    refetchInterval: 5000,
  })
  const cancelExport = useMutation({
    mutationFn: (id: string) => dataApi.cancelReviewExport(id),
    onSuccess: response => {
      queryClient.setQueryData(['reviewExport', response.data.id], response.data)
      void queryClient.invalidateQueries({ queryKey: ['reviewExportList'] })
    },
  })
  const downloaded = useRef('')
  useEffect(() => {
    if (exportJob?.status === 'ready' && exportJob.download_url && downloaded.current !== exportJob.id) {
      downloaded.current = exportJob.id
      const link = document.createElement('a')
      link.href = exportJob.download_url
      link.download = exportJob.filename
      document.body.appendChild(link); link.click(); link.remove()
    }
  }, [exportJob])
  // A recognition-progress refetch must not replace the click preview while
  // persistence is still in flight. The same edit is safe to apply twice.
  const pendingChange = save.isPending && save.variables?.file === currentFile ? save.variables : undefined
  const review = reviewQuery.data && pendingChange ? applyReviewChange(reviewQuery.data, pendingChange) : reviewQuery.data
  const reviewComplete = !!review?.total && review.completed === review.total
  const allKeys = Object.keys(review?.entries || {})
  const keys = allKeys.filter((key) => key === pendingChange?.key || filter === 'all' || (filter === 'unmarked' ? !review?.entries[key].decision : review?.entries[key].decision === filter))
  const currentKey = keys.includes(selectedKey) ? selectedKey : keys[0] || ''
  const index = keys.indexOf(currentKey)
  const offset = allKeys.indexOf(currentKey)
  const postQuery = useQuery(reviewPostQueryOptions(currentFile, offset,
    async (file, index, signal) => (await dataApi.browse(file, index, '', 'all', 1, signal)).data))
  const refreshReview = () => {
    void filesQuery.refetch()
    if (currentFile) {
      void reviewQuery.refetch()
      // Disabled queries stay disabled until the refreshed review supplies a key.
      void queryClient.invalidateQueries({ queryKey: ['dataBrowse', currentFile] })
    }
  }
  const post = postQuery.data?.posts[0]
  const entry = review?.entries[currentKey]
  const change = (kind: Change['kind'], value: boolean | null, imageKey?: string) => {
    const decision = value === null ? null : kind === 'account' ? (value ? 'non_marketing' : 'marketing') : (value ? 'qualified' : 'unqualified')
    const command: Change = { file: currentFile, key: currentKey, kind, decision, imageKey }
    setLastChange(command)
    save.mutate(command)
  }
  useEffect(() => {
    if (!currentFile) return
    // Pin the initial fallback file so a new supplement output cannot replace
    // the selected task when the file list refreshes.
    if (chosenFile !== currentFile) setChosenFile(currentFile)
    try {
      localStorage.setItem('mediacrawler_review_file', currentFile)
      // Do not erase the saved position while an asynchronous query is loading.
      if (currentKey) localStorage.setItem('mediacrawler_review_post', currentKey)
    } catch { /* storage may be unavailable */ }
  }, [currentFile, currentKey, chosenFile])
  useEffect(() => { contentRef.current?.scrollTo({ top: 0 }); imagesRef.current?.scrollTo({ top: 0 }); contextRef.current?.scrollTo({ top: 0 }) }, [currentFile, currentKey])
  const nextUnmarked = () => {
    const next = allKeys.find((key, i) => i > offset && !review?.entries[key].decision) || allKeys.find((key) => key !== currentKey && !review?.entries[key].decision)
    if (next) { setFilter('all'); setSelectedKey(next) }
  }
  const error = filesQuery.error || reviewQuery.error || postQuery.error
  const details = axios.isAxiosError(save.error) ? save.error.response?.data?.detail : null
  const backendOutdated = save.variables?.kind === 'post' && Array.isArray(details) && details.some((item) => item.type === 'literal_error' && item.loc?.includes('kind'))
  const loading = filesQuery.isLoading || (!!currentFile && reviewQuery.isLoading) || (!!currentKey && postQuery.isLoading)
  return <div className="manual-review-page" aria-label={t('pages.review')}>
    <header className="review-page-heading">
      <div className="review-heading-progress"><h1>{t('pages.review')}</h1><p aria-live="polite">{t('progress', { completed: review?.completed || 0, total: review?.total || 0 })}</p></div>
      <span className="review-save-state" aria-live="polite">{save.isPending ? t('saving') : save.isError ? t('saveFailedShort') : save.isSuccess ? t('saved') : ''}</span>
      <Button variant="outline" size="sm" title={t('reviewExport.hint')} disabled={save.isPending || save.isError || exportBusy || !review || !Object.values(review.entries).some((item) => item.decision === 'qualified')} onClick={() => exportResult.mutate(currentFile)}><Download className="h-4 w-4" />{t(exportBusy ? 'reviewExport.running' : 'reviewExport.button')}</Button>
      <span>{t('currentPost', { index: index + 1, total: keys.length })}</span>
    </header>
    {exportResult.isError && <p role="alert" className="text-sm text-red-600">{t(exportResult.error instanceof Error && exportResult.error.message === 'review_export_empty' ? 'reviewExport.empty' : 'reviewExport.failed')}</p>}
    {missingMain && <p role="alert" className="text-sm text-red-600">{t('reviewExport.missingMain')}</p>}
    {(exportStatus.isError || cancelExport.isError) && <p role="alert" className="text-sm text-red-600">{t('reviewExport.statusFailed')} <Button size="sm" variant="outline" onClick={() => { cancelExport.reset(); void exportStatus.refetch() }}>{t('reviewExport.retryStatus')}</Button></p>}
    {exportJob && <div role="status" className="flex flex-wrap items-center gap-3 text-sm text-cyber-text-secondary">
      <span>{t(`reviewExport.status.${exportJob.status}`)} · {exportJob.filename}</span>
      {exportBusy && <><span>{t('reviewExport.progress', { done: exportJob.processed, total: exportJob.total })}</span><Button size="sm" variant="outline" disabled={cancelExport.isPending} onClick={() => cancelExport.mutate(exportId)}>{t('reviewExport.cancel')}</Button></>}
      {exportJob.status === 'failed' && <span className="text-red-600">{t(exportJob.error === 'review_export_empty' ? 'reviewExport.empty' : 'reviewExport.failed')}</span>}
      {exportJob.status === 'ready' && <>
        <span>{t('reviewExport.summary', { retained: exportJob.counts.retained, images: exportJob.counts.images, pending: exportJob.counts.pending, missing: exportJob.counts.missing, noImages: exportJob.counts.no_images })}</span>
        {!!(exportJob.counts.pending || exportJob.counts.missing || exportJob.counts.no_images) && <span className="text-amber-700">{t('reviewExport.partial')}</span>}
        <a className="review-link" href={exportJob.download_url || undefined} download={exportJob.filename}>{t('reviewExport.download')}</a>
        <Button size="sm" variant="outline" disabled={cancelExport.isPending} onClick={() => cancelExport.mutate(exportId)}>{t('reviewExport.removePackage')}</Button>
      </>}
    </div>}
    {!!exportList.data?.filter(job => job.id !== exportId && ['ready', 'preparing', 'queued'].includes(job.status)).length && <details className="text-sm text-cyber-text-secondary">
      <summary>{t('reviewExport.previousPackages')}</summary>
      {exportList.data.filter(job => job.id !== exportId && ['ready', 'preparing', 'queued'].includes(job.status)).map(job => <div key={job.id} className="mt-2 flex flex-wrap items-center gap-3">
        <span>{job.filename} · {t(`reviewExport.status.${job.status}`)}</span>
        {job.download_url && <a className="review-link" href={job.download_url} download={job.filename}>{t('reviewExport.download')}</a>}
        <Button size="sm" variant="outline" disabled={cancelExport.isPending} onClick={() => cancelExport.mutate(job.id)}>{t(job.status === 'ready' ? 'reviewExport.removePackage' : 'reviewExport.cancel')}</Button>
      </div>)}
    </details>}
    <div className="review-toolbar">
      <label>{t('batch')}<select aria-label={t('batch')} className={controlClass} value={currentFile} disabled={save.isPending} onChange={(event) => { setChosenFile(event.target.value); setSelectedKey(''); save.reset() }}><option value="" disabled>{t('chooseBatch')}</option>{files.map((file) => <option key={file.path} value={file.path}>{file.name}</option>)}</select></label>
      <label>{t('reviewFilter')}<select aria-label={t('reviewFilter')} className={controlClass} value={filter} disabled={save.isPending} onChange={(event) => setFilter(event.target.value)}>{['all', 'unmarked', 'qualified', 'unqualified'].map((item) => <option key={item} value={item}>{t(`filters.${item}`)}</option>)}</select></label>
      <Button variant="outline" onClick={refreshReview} disabled={save.isPending || !currentFile}><ReviewIcon name="refresh" />{t('rescan')}</Button>
    </div>
    <details open={toolsOpen} onToggle={(event) => setToolsOpen(event.currentTarget.open)} className="review-tools">
      <summary>{t('reviewTools')}{reviewComplete && <span className="ml-3 font-medium text-cyber-neon-cyan">{t('reviewToolsReady')}</span>}<a href="#/logs" className="float-right text-cyber-neon-cyan" onClick={(event) => { event.stopPropagation(); event.preventDefault(); window.location.hash = '/logs' }}>{t('logs.view')}</a></summary>
      <div className="max-h-[32vh] space-y-3 overflow-y-auto border-t border-cyber-border-subtle p-3">
        <SupplementPanel file={currentFile} completed={reviewComplete} disabled={save.isPending} onFinished={() => { setFilter('unmarked'); setSelectedKey('') }} />
        <ImageSubjectPanel file={currentFile} />
      </div>
    </details>
    {save.isError && <div role="alert" className="flex shrink-0 flex-wrap items-center justify-between gap-3 rounded-lg border border-red-400/50 p-3 text-sm text-cyber-text-primary"><span>{t(backendOutdated ? 'reviewBackendOutdated' : 'saveFailed')}</span><Button variant="outline" size="sm" onClick={() => lastChange && save.mutate(lastChange)}>{t('retry')}</Button></div>}
    {loading ? <div role="status" className="flex-1 space-y-4 rounded-xl bg-cyber-bg-panel p-6"><div className="h-6 w-2/3 animate-pulse rounded bg-cyber-bg-tertiary" /><div className="h-48 animate-pulse rounded bg-cyber-bg-tertiary" /><p className="text-sm text-cyber-text-secondary">{t('loading')}</p></div>
      : error ? <div role="alert" className="space-y-4 p-6 text-sm text-cyber-text-primary"><p>{t('loadFailed')}</p><Button variant="outline" onClick={refreshReview}>{t('retry')}</Button></div>
      : !currentFile || !post || !entry ? <div className="flex flex-1 items-center justify-center p-6 text-center text-sm leading-7 text-cyber-text-secondary">{t(!currentFile ? 'noData' : 'noMatches')}</div>
      : <>
        <article ref={contentRef} className="review-work-area" aria-label={t('postPreview')}>
          <div ref={contextRef} className="review-context">
            <section className="review-account-panel" aria-label={t('accountReview')}>
              <div className="review-panel-heading"><h2><ReviewIcon name="account" />{t('accountReview')}</h2><span title={entry.account_identity_evidence || undefined} className={`review-state ${entry.account === 'non_marketing' ? 'review-state-positive' : entry.account === 'marketing' ? 'review-state-negative' : ''}`}>{t(entry.account === 'non_marketing' ? 'accountPassed' : entry.account === 'marketing' ? 'accountRejected' : 'unmarked')}</span></div>
              <p className="review-account-name">{post.nickname || t('unknownAccount')}</p>
              <PostAccountMetadata post={post} />
              <Choices value={entry.account} positive={t('personalAccount')} negative={t('nonPersonalAccount')} disabled={save.isPending || !!entry.account_rejection_reason} onChange={(value) => change('account', value)} />
              <p className="review-account-hint">{t(entry.account_scope === 'batch_account' ? 'accountBatchScope' : 'accountPostScope')}</p>
            </section>
            <section className="review-post-panel" aria-label={t('keywordContent')}>
              <div className="review-panel-heading"><h2>{t('postContent')}</h2>{post.url && <a href={post.url} target="_blank" rel="noopener noreferrer" className="review-link"><ReviewIcon name="external" />{t('openOriginal')}</a>}</div>
              <div className="review-keyword-row"><span>{t('matchedKeywords')}</span><span className="review-keyword-tag">{post.source_keyword}</span></div>
              <PostLocationMetadata post={post} />
              <p className="review-body-label">{t('bodySource')}</p><p className="review-body"><KeywordHighlight value={post.content || td('browse.noContent')} query={post.source_keyword} /></p>
              {!!post.hit_comments.length && <ul className="mt-4 space-y-4">{post.hit_comments.map((comment) => <li key={comment.id + comment.content}><p className="review-body-label">{t('commentSource')} · {comment.nickname} · {td(comment.kind === 'semantic' ? 'browse.semanticHit' : 'browse.keywordHit')}</p><p className="review-comments"><KeywordHighlight value={comment.content} query={post.source_keyword} /></p></li>)}</ul>}
              {!!post.comments.length && <details className="review-post-details"><summary>{td('browse.allComments', { count: post.comments.length })}</summary><ul className="mt-2 space-y-3">{post.comments.map((comment) => <li key={comment.id + comment.content} className="review-comments"><KeywordHighlight value={comment.content} query={post.source_keyword} /></li>)}</ul></details>}
              <details className="review-post-details"><summary>{t('postDetails')}</summary>{post.title && <p><KeywordHighlight value={post.title} query={post.source_keyword} /></p>}<p>{td(`browse.status.${post.status}`, { defaultValue: post.status })} · {post.published_at}</p><p>{td('browse.postId')}: {post.id}</p>{entry.account_identity_evidence && <p>{entry.account_rejection_reason ? t(`outcomeReasons.${entry.account_rejection_reason}`) : entry.account_identity_status === 'review' && !entry.account ? t('accountIdentityPending') : t('accountIdentityEvidence')} {entry.account_identity_evidence}</p>}</details>
              {post.evidence && <details className="review-post-details"><summary>{td('browse.evidence')}</summary><p><KeywordHighlight value={post.evidence} query={post.source_keyword} /></p></details>}
            </section>
          </div>
          <section className="review-images-panel" aria-label={t('imageReview')}>
            <div className="review-panel-heading"><h2>{t('imageReview')}</h2><span className="text-xs text-cyber-text-secondary">{t('imageProgress', { completed: entry.review_images.filter((image) => entry.images[image.key]).length, total: entry.review_images.length })}</span></div>
            {entry.review_images.length ? <div ref={imagesRef} className="review-image-grid">{entry.review_images.map((image, i) => <ReviewPicture key={`${currentKey}:${image.key}`} image={image} index={i} postUrl={post.url} value={entry.images[image.key]} disabled={save.isPending} onChange={(value) => change('image', value, image.key)} />)}</div> : <p className="py-12 text-center text-sm text-cyber-text-secondary">{t('noImages')}</p>}
          </section>
        </article>
        <footer className="review-footer">
          <div className="review-footer-label"><span>{t('postDecision')}</span><span className={`review-state ${entry.decision === 'qualified' ? 'review-state-positive' : entry.decision === 'unqualified' ? 'review-state-negative' : ''}`}>{t(`outcomes.${entry.decision || 'pending'}`)}</span></div>
          <div role="group" aria-label={t('postDecision')}><Choices value={entry.decision} positive={t('postQualified')} negative={t('postUnqualified')} disabled={save.isPending || !!entry.semantic_rejection_reason || !!entry.account_rejection_reason || (entry.account_identity_status === 'review' && entry.account === null)} onChange={(value) => change('post', value)} canReset={entry.decision_source === 'manual'} resetLabel={t('resetPostDecision')} iconOnly /></div>
          <p role="status" className="review-footer-reason">{t('automaticDecision')}: {t(`outcomes.${entry.automatic_decision || 'pending'}`)} · {entry.decision_source === 'manual' && !entry.semantic_rejection_reason ? t('manualPostOverride') : t(`outcomeReasons.${entry.automatic_decision_reason}`)}</p>
          <div className="review-pagination"><Button variant="outline" size="sm" disabled={save.isPending || index <= 0} onClick={() => setSelectedKey(keys[index - 1])} aria-label={t('previous')}><ReviewIcon name="previous" /></Button><span>{index + 1} / {keys.length}</span><Button variant="outline" size="sm" disabled={save.isPending || index >= keys.length - 1} onClick={() => setSelectedKey(keys[index + 1])} aria-label={t('next')}><ReviewIcon name="next" /></Button><Button variant="outline" size="sm" className="review-next-unmarked" disabled={save.isPending || !allKeys.some((key) => key !== currentKey && !review?.entries[key].decision)} onClick={nextUnmarked}>{t('nextUnmarked')}</Button></div>
        </footer>
      </>}
  </div>
}
