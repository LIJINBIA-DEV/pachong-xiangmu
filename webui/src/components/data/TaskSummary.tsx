import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as Dialog from '@radix-ui/react-dialog'
import { useTranslation } from 'react-i18next'
import axios from 'axios'
import { Download, Loader2, Sparkles, X } from 'lucide-react'
import { dataApi, type CollectionTask } from '@/lib/api'
import { useCrawlerStore } from '@/store/crawlerStore'
import { formatDateTime } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import type { ContentSummaryJob, SummaryStance } from '@/types/contentSummary'
import './TaskSummary.css'

const stances: SummaryStance[] = ['positive', 'negative', 'neutral', 'mixed', 'unclear']
const active = (job?: ContentSummaryJob | null) => job?.status === 'queued' || job?.status === 'running'

function Report({ report, file, stale }: { report: ContentSummaryJob; file: string; stale: boolean }) {
  const { t } = useTranslation('data')
  const result = report.result
  if (!result) return null
  const sources = new Map(result.posts.map(post => [post.ref, post]))
  return <section className="summary-report" aria-label={t('summary.result')}>
    <header className="summary-report-heading"><div><h3>{t('summary.result')}</h3><p>{t(`summary.modes.${report.mode}`)} · {report.options.model} · {formatDateTime(report.finished_at || report.created_at)}</p></div>
      <a href={dataApi.getContentSummaryDownloadUrl(file, report.id)} className="summary-download" download><Download size={14} />{t('summary.download')}</a>
    </header>
    {stale && <p className="summary-notice" role="status">{t('summary.stale')}</p>}
    <p className="summary-coverage">{t('summary.coverage', report.stats)} {t('summary.reportScope', { scope: t(`summary.scopes.${report.options.scope}`) })}</p>
    <p className="summary-coverage">{t('summary.detailCoverage', report.stats)}</p>
    {!!report.stats.omitted && <p className="summary-notice">{t('summary.omitted', { count: report.stats.omitted })}</p>}
    {(report.stats.truncated > 0 || report.stats.comments_omitted > 0 || report.stats.skipped_empty > 0) && <p className="summary-notice">{t('summary.clipped', report.stats)}</p>}
    <p className="summary-overview">{result.overview}</p>
    {report.mode === 'evaluation' && <div className="summary-stances" aria-label={t('summary.stanceTitle')}>{stances.map(stance => <div key={stance} data-stance={stance}><span>{t(`summary.stances.${stance}`)}</span><strong>{result.stance_counts[stance] || 0}</strong></div>)}</div>}
    <div className="summary-themes">{result.themes.map((theme, index) => <section key={index}><h4>{theme.title}</h4><p>{theme.summary}</p><nav aria-label={t('summary.references')} className="summary-references">{theme.refs.map(ref => {
      const post = sources.get(ref)
      return post?.url ? <a key={ref} href={post.url} title={post.title || post.query} target="_blank" rel="noopener noreferrer">{t('summary.sourcePost', { ref })}</a> : <span key={ref}>{t('summary.sourceNoLink', { ref })}</span>
    })}</nav></section>)}</div>
    <details className="summary-posts"><summary>{t('summary.postDetails', { count: result.posts.length })}</summary><div>{result.posts.map(post => <details key={post.ref}>
      <summary>{post.ref} · {post.title || post.query || post.post_id}{report.mode === 'evaluation' && ` · ${t(`summary.stances.${post.stance}`)}`}</summary>
      <div className="summary-post-body"><p className="summary-meta">{t('summary.sourceTopic')}: {post.query || '—'} · {t(`browse.status.${post.status}`, { defaultValue: post.status })}</p><p>{post.summary}</p>
        {post.evidence.map((evidence, index) => <blockquote key={index}><small>{t(evidence.source.startsWith('comment:') ? 'summary.commentEvidence' : evidence.source === 'title' ? 'summary.titleEvidence' : 'summary.bodyEvidence')}</small><p>{evidence.quote}</p></blockquote>)}
        {post.url && <a href={post.url} target="_blank" rel="noopener noreferrer">{t('tasks.openOriginal')}</a>}
      </div>
    </details>)}</div></details>
    <p className="summary-coverage">{t('summary.interpretation')}</p>
  </section>
}

export function TaskSummary({ task }: { task: CollectionTask }) {
  const { t } = useTranslation('data')
  const [open, setOpen] = useState(false)
  const client = useQueryClient()
  const status = useCrawlerStore(state => state.status)
  const info = useQuery({ queryKey: ['contentSummary', task.primary_file], enabled: open,
    queryFn: async () => (await dataApi.getContentSummary(task.primary_file)).data,
    refetchInterval: query => open && (query.state.data?.busy || active(query.state.data?.job)) ? 2000 : false, retry: 1 })
  const generate = useMutation({
    mutationFn: async () => (await dataApi.generateContentSummary({ file: task.primary_file })).data,
    onSuccess: job => {
      client.setQueryData(['contentSummary', task.primary_file], (previous: typeof info.data) => previous ? { ...previous, job, busy: true } : previous)
      void client.invalidateQueries({ queryKey: ['contentSummary', task.primary_file] })
    },
  })
  const data = info.data
  const scope = data?.settings.scope || 'retained'
  const maxPosts = data?.settings.max_posts || 100
  const eligible = (data?.counts.matched || 0) + (scope === 'available' ? (data?.counts.review || 0) + (data?.counts.unfiltered || 0) : 0)
  const busy = generate.isPending || !!data?.busy || active(data?.job)
  const collecting = status === 'running' || status === 'stopping'
  const error = generate.error || info.error
  const errorCode = axios.isAxiosError(error) ? error.response?.data?.detail : undefined
  const disabled = busy || collecting || !data?.settings_ready || eligible === 0
  return <Dialog.Root open={open} onOpenChange={setOpen}>
    <Dialog.Trigger asChild><Button className="task-summary-trigger"><Sparkles aria-hidden="true" />{t('summary.title')}</Button></Dialog.Trigger>
    <Dialog.Portal><Dialog.Overlay className="content-summary-overlay" /><Dialog.Content className="content-summary-dialog" aria-describedby="content-summary-description">
      <header className="content-summary-header"><div><Dialog.Title>{t('summary.title')}</Dialog.Title><p>{task.title || t('tasks.untitled')}</p></div><Dialog.Close aria-label={t('summary.close')}><X size={20} /></Dialog.Close></header>
      <div className="content-summary-body">
        <Dialog.Description id="content-summary-description">{t('summary.description')}</Dialog.Description>
        <div className="summary-actions">
          <Button disabled={disabled} onClick={() => { if (!disabled) generate.mutate() }}>{busy && <Loader2 size={15} className="mr-2 animate-spin" />}{t(busy ? 'summary.working' : data?.report ? 'summary.regenerate' : 'summary.generate')}</Button>
          <button type="button" className="summary-text-button" disabled={generate.isPending} onClick={() => { void info.refetch() }}>{t('summary.refresh')}</button>
        </div>
        {data && <p className="summary-hint">{t('summary.preview', { total: eligible, count: Math.min(maxPosts, eligible) })}</p>}
        {data && !data.settings_ready && <p className="summary-hint">{t('aiSettings.configureFirst')}</p>}
        {collecting && <p className="summary-notice">{t('summary.collecting')}</p>}
        {data && !eligible && <p className="summary-hint">{t('summary.empty')}</p>}
        {(info.isLoading || error) && <p role={error ? 'alert' : 'status'} className={error ? 'summary-error' : 'summary-hint'}>{t(error ? `summary.errors.${typeof errorCode === 'string' ? errorCode : 'summary_read_failed'}` : 'summary.loading', { defaultValue: t('summary.errors.summary_failed') })}</p>}
        {data?.job && active(data.job) && <section className="summary-progress" role="status"><p>{t(data.job.processed === data.job.total ? 'summary.synthesizing' : 'summary.progress', { done: data.job.processed, total: data.job.total })}</p><progress max={data.job.total || 1} value={data.job.processed} /><p>{t('summary.requests', { done: data.job.calls, total: data.job.estimated_calls })} · {t('summary.background')}</p></section>}
        {data?.job && ['failed','interrupted'].includes(data.job.status) && <p role="alert" className="summary-error">{t(`summary.errors.${data.job.error || 'summary_interrupted'}`, { defaultValue: t('summary.errors.summary_failed') })}{data.report && ` ${t('summary.previousSaved')}`}</p>}
        {data?.report && <Report report={data.report} file={task.primary_file} stale={data.stale} />}
        {!data?.report && !active(data?.job) && <p className="summary-empty">{t('summary.noReport')}</p>}
      </div>
    </Dialog.Content></Dialog.Portal>
  </Dialog.Root>
}
