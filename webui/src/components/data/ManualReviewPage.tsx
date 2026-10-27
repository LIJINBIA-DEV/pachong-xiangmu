import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Download } from 'lucide-react'
import { ReviewIcon } from './ReviewIcon'
import './ManualReviewPage.css'
import { dataApi } from '@/lib/api'
import { taskLabel } from '@/lib/fileLabels'
import { reviewFileSelection } from '@/lib/reviewFiles'
import { applyReviewChange, withReviewOutcomes } from '@/lib/reviewOutcome'
import { reviewPostQueryOptions } from '@/lib/reviewLoading'
import { reviewSaveOptions } from '@/lib/reviewSave'
import type { SavedReviewChange } from '@/lib/reviewSave'
import { KeywordHighlight } from './KeywordHighlight'
import { PostPicture } from './PostPicture'
import { PostLocationMetadata } from './PostMetadata'
import { SupplementPanel } from './SupplementPanel'
import { Button } from '@/components/ui/button'

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

export function ManualReviewPage({ fileRequest }: { fileRequest?: { file: string; id: number; postKey?: string } }) {
  const { t } = useTranslation('workspace')
  const { t: td } = useTranslation('data')
  const queryClient = useQueryClient()
  const [chosenFile, setChosenFile] = useState(() => readPreference('mediacrawler_review_file'))
  const [selectedKey, setSelectedKey] = useState(() => readPreference('mediacrawler_review_post'))
  const [filter, setFilter] = useState('all')
  useEffect(() => { if (fileRequest) { setChosenFile(fileRequest.file); setSelectedKey(fileRequest.postKey || ''); setFilter('all') } }, [fileRequest])
  const contentRef = useRef<HTMLElement>(null)
  const contextRef = useRef<HTMLDivElement>(null)
  const [lastChange, setLastChange] = useState<Change | null>(null)
  const filesQuery = useQuery({ queryKey: ['collectionTasks'], queryFn: async () => (await dataApi.getTasks()).data.tasks })
  const tasks = filesQuery.data || []
  const chosenTask = tasks.find((task) => task.files.some((file) => file.path === chosenFile))
  const { currentFile, missingMain } = reviewFileSelection(tasks.flatMap((task) => task.files), chosenTask?.primary_file || chosenFile)
  const reviewTasks = tasks.filter((task) => task.files.some((file) => file.path === task.primary_file && file.type === 'xlsx' && file.file_kind !== 'semantic'))
  const reviewQuery = useQuery({ queryKey: ['manualReview', currentFile], queryFn: async () => withReviewOutcomes((await dataApi.getReview(currentFile)).data), enabled: !!currentFile, retry: 1 })
  const save = useMutation(reviewSaveOptions(queryClient,
    async (change) => (await dataApi.saveReview(change.file, change.key, change.kind, change.decision, change.imageKey)).data,
    (change) => {
      if (change.file === currentFile && change.key === currentKey && keys[index + 1]) setSelectedKey(keys[index + 1])
    }))
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
  // A background refetch must not replace the click preview while
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
  useEffect(() => { contentRef.current?.scrollTo({ top: 0 }); contextRef.current?.scrollTo({ top: 0 }) }, [currentFile, currentKey])
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
        {!!(exportJob.counts.pending || exportJob.counts.missing) && <span className="text-amber-700">{t('reviewExport.partial')}</span>}
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
      <label>{t('batch')}<select aria-label={t('batch')} className={controlClass} value={currentFile} disabled={save.isPending} onChange={(event) => { setChosenFile(event.target.value); setSelectedKey(''); save.reset() }}><option value="" disabled>{t('chooseBatch')}</option>{reviewTasks.map((task) => <option key={task.id} value={task.primary_file}>{taskLabel(task, td)}</option>)}</select></label>
      <label>{t('reviewFilter')}<select aria-label={t('reviewFilter')} className={controlClass} value={filter} disabled={save.isPending} onChange={(event) => setFilter(event.target.value)}>{['all', 'unmarked', 'qualified', 'unqualified'].map((item) => <option key={item} value={item}>{t(`filters.${item}`)}</option>)}</select></label>
      <Button variant="outline" onClick={refreshReview} disabled={save.isPending || !currentFile}><ReviewIcon name="refresh" />{t('rescan')}</Button>
    </div>
    <SupplementPanel file={currentFile} completed={reviewComplete} disabled={save.isPending} onFinished={() => { setFilter('unmarked'); setSelectedKey('') }} />
    {save.isError && <div role="alert" className="flex shrink-0 flex-wrap items-center justify-between gap-3 rounded-lg border border-red-400/50 p-3 text-sm text-cyber-text-primary"><span>{t(backendOutdated ? 'reviewBackendOutdated' : 'saveFailed')}</span><Button variant="outline" size="sm" onClick={() => lastChange && save.mutate(lastChange)}>{t('retry')}</Button></div>}
    {loading ? <div role="status" className="flex-1 space-y-4 rounded-xl bg-cyber-bg-panel p-6"><div className="h-6 w-2/3 animate-pulse rounded bg-cyber-bg-tertiary" /><div className="h-48 animate-pulse rounded bg-cyber-bg-tertiary" /><p className="text-sm text-cyber-text-secondary">{t('loading')}</p></div>
      : error ? <div role="alert" className="space-y-4 p-6 text-sm text-cyber-text-primary"><p>{t('loadFailed')}</p><Button variant="outline" onClick={refreshReview}>{t('retry')}</Button></div>
      : !currentFile || !post || !entry ? <div className="flex flex-1 items-center justify-center p-6 text-center text-sm leading-7 text-cyber-text-secondary">{t(!currentFile ? 'noData' : 'noMatches')}</div>
      : <>
        <article ref={contentRef} className="review-work-area" aria-label={t('postPreview')}>
          <div ref={contextRef} className="review-context">
            <section className="review-post-panel" aria-label={t('keywordContent')}>
              <div className="review-panel-heading"><h2>{t('postContent')}</h2>{post.url && <a href={post.url} target="_blank" rel="noopener noreferrer" className="review-link"><ReviewIcon name="external" />{t('openOriginal')}</a>}</div>
              <div className="review-keyword-row"><span>{t('matchedKeywords')}</span><span className="review-keyword-tag">{post.source_keyword}</span></div>
              <PostLocationMetadata post={post} />
              <p className="review-body-label">{t('bodySource')}</p><p className="review-body"><KeywordHighlight value={post.content || td('browse.noContent')} query={post.source_keyword} /></p>
              <section className="review-post-images" aria-label={td('browse.images')}>
                <div className="review-panel-heading"><h2>{td('browse.images')}（{post.images.length}）</h2>{post.url && <a href={post.url} target="_blank" rel="noopener noreferrer" className="review-link">{td('browse.viewOriginalImages')}</a>}</div>
                {post.images.length ? <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">{post.images.map((image, i) => <PostPicture key={`${currentKey}:${image.url}`} image={image} index={i} />)}</div> : <p className="text-sm text-cyber-text-secondary">{td('browse.noImages')}</p>}
              </section>
              {!!post.hit_comments.length && <ul className="mt-4 space-y-4">{post.hit_comments.map((comment) => <li key={comment.id + comment.content}><p className="review-body-label">{t('commentSource')} · {comment.nickname} · {td(comment.kind === 'semantic' ? 'browse.semanticHit' : 'browse.keywordHit')}</p><p className="review-comments"><KeywordHighlight value={comment.content} query={post.source_keyword} /></p></li>)}</ul>}
              {!!post.comments.length && <details className="review-post-details"><summary>{td('browse.allComments', { count: post.comments.length })}</summary><ul className="mt-2 space-y-3">{post.comments.map((comment) => <li key={comment.id + comment.content} className="review-comments"><KeywordHighlight value={comment.content} query={post.source_keyword} /></li>)}</ul></details>}
              <details className="review-post-details"><summary>{t('postDetails')}</summary>{post.title && <p><KeywordHighlight value={post.title} query={post.source_keyword} /></p>}<p>{td(`browse.status.${post.status}`, { defaultValue: post.status })} · {post.published_at}</p><p>{td('browse.postId')}: {post.id}</p>{entry.account_identity_evidence && <p>{t('accountIdentityEvidence')} {entry.account_identity_evidence}</p>}</details>
              {post.evidence && <details className="review-post-details"><summary>{td('browse.evidence')}</summary><p><KeywordHighlight value={post.evidence} query={post.source_keyword} /></p></details>}
            </section>
          </div>
        </article>
        <footer className="review-footer">
          <div className="review-footer-label"><span>{t('postDecision')}</span><span className={`review-state ${entry.decision === 'qualified' ? 'review-state-positive' : entry.decision === 'unqualified' ? 'review-state-negative' : ''}`}>{t(`outcomes.${entry.decision || 'pending'}`)}</span></div>
          <div role="group" aria-label={t('postDecision')}><Choices value={entry.decision} positive={t('postQualified')} negative={t('postUnqualified')} disabled={save.isPending || !!entry.semantic_rejection_reason || !!entry.account_rejection_reason} onChange={(value) => change('post', value)} canReset={entry.decision_source === 'manual'} resetLabel={t('resetPostDecision')} /></div>
          <p role="status" className="review-footer-reason">{entry.semantic_rejection_reason || entry.account_rejection_reason ? t(`outcomeReasons.${entry.decision_reason}`) : t('postReviewInstructions')}</p>
          <div className="review-pagination"><Button variant="outline" size="sm" disabled={save.isPending || index <= 0} onClick={() => setSelectedKey(keys[index - 1])} aria-label={t('previous')}><ReviewIcon name="previous" /></Button><span>{index + 1} / {keys.length}</span><Button variant="outline" size="sm" disabled={save.isPending || index >= keys.length - 1} onClick={() => setSelectedKey(keys[index + 1])} aria-label={t('next')}><ReviewIcon name="next" /></Button></div>
        </footer>
      </>}
  </div>
}
