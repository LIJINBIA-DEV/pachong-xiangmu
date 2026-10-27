import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { AlertCircle, CheckCircle2, RefreshCw, Search, ScrollText } from 'lucide-react'
import { isAxiosError } from 'axios'
import { dataApi } from '@/lib/api'
import { taskLabel } from '@/lib/fileLabels'
import { CollectionLogDetails } from './CollectionLogDetails'
import { Button } from '@/components/ui/button'

const inputClass = 'h-10 min-w-0 rounded-md border border-cyber-border bg-cyber-bg-panel px-3 text-sm text-cyber-text-primary focus:outline-none focus:ring-2 focus:ring-cyber-neon-cyan'

export function CollectionLogsPage({ active }: { active: boolean }) {
  const { t } = useTranslation('workspace')
  const { t: td } = useTranslation('data')
  const [selected, setSelected] = useState(() => { try { return localStorage.getItem('mediacrawler_review_file') || '' } catch { return '' } })
  const [round, setRound] = useState('all')
  const [missingOnly, setMissingOnly] = useState(false)
  const [search, setSearch] = useState('')
  const filesQuery = useQuery({ queryKey: ['collectionTasks'], queryFn: async () => (await dataApi.getTasks()).data.tasks, enabled: active })
  const tasks = filesQuery.data || []
  const file = tasks.find((task) => task.files.some((item) => item.path === selected))?.primary_file || tasks[0]?.primary_file || ''
  useEffect(() => { if (file && !selected) setSelected(file) }, [file, selected])
  const logs = useQuery({ queryKey: ['collectionLogs', file], queryFn: async () => (await dataApi.getCollectionLogs(file)).data, enabled: active && !!file, retry: false, refetchInterval: active ? 10000 : false })
  const reviewPlan = useQuery({ queryKey: ['supplement', file], queryFn: async () => (await dataApi.getSupplement(file)).data, enabled: active && !!file, retry: false })
  const all = logs.data?.entries || []
  const entries = all.filter((item) => (round === 'all' || item.round === Number(round)) && (!missingOnly || item.missing > 0) && item.keyword.includes(search.trim()))
  const latestRound = logs.data?.rounds[logs.data.rounds.length - 1]?.number
  const latest = all.filter((item) => item.round === latestRound)
  const refreshing = filesQuery.isFetching || logs.isFetching
  const error = filesQuery.error || logs.error
  const outdated = isAxiosError(logs.error) && logs.error.response?.status === 404
  return <div className="flex min-h-0 flex-1 flex-col gap-4" aria-label={t('pages.logs')}>
    <div className="flex shrink-0 flex-wrap items-end gap-3">
      <label className="min-w-0 flex-1 space-y-1.5 text-xs text-cyber-text-secondary">{t('batch')}<select aria-label={t('batch')} value={file} onChange={(event) => { setSelected(event.target.value); setRound('all') }} className={`${inputClass} w-full`}><option value="" disabled>{t('chooseBatch')}</option>{tasks.map((task) => <option key={task.id} value={task.primary_file}>{taskLabel(task, td)}</option>)}</select></label>
      <label className="space-y-1.5 text-xs text-cyber-text-secondary">{t('logs.roundFilter')}<select aria-label={t('logs.roundFilter')} value={round} onChange={(event) => setRound(event.target.value)} className={`${inputClass} block`}><option value="all">{t('logs.allRounds')}</option>{logs.data?.rounds.map((item) => <option key={item.number} value={item.number}>{t('logs.round', { count: item.number })}</option>)}</select></label>
      <Button variant="outline" disabled={refreshing} onClick={() => { void filesQuery.refetch(); void logs.refetch(); void reviewPlan.refetch() }}><RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />{t('rescan')}</Button>
    </div>
    {!error && logs.data && <div className="shrink-0 rounded-xl border border-cyber-border-subtle bg-cyber-bg-panel p-4 text-sm leading-7 text-cyber-text-primary">
      <p>{t('logs.collectionSummary', { groups: latest.filter((item) => item.missing > 0).length, missing: latest.reduce((total, item) => total + item.missing, 0) })}</p>
      {reviewPlan.data && <p className="text-xs text-cyber-text-secondary">{t('logs.reviewSummary', { excluded: reviewPlan.data.groups.reduce((total, item) => total + item.excluded, 0), pending: reviewPlan.data.groups.reduce((total, item) => total + item.pending, 0), missing: reviewPlan.data.shortfall ?? '—' })}</p>}
      <p className="text-xs text-cyber-text-secondary">{t('logs.scope')}</p>
    </div>}
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
      <label className="flex items-center gap-2 text-sm text-cyber-text-secondary"><input type="checkbox" checked={missingOnly} onChange={(event) => setMissingOnly(event.target.checked)} className="accent-cyan-500" />{t('logs.missingOnly')}</label>
      <label className="relative min-w-0"><Search className="absolute left-3 top-3 h-4 w-4 text-cyber-text-secondary" /><input aria-label={t('logs.search')} placeholder={t('logs.search')} value={search} onChange={(event) => setSearch(event.target.value)} className={`${inputClass} w-56 max-w-full pl-9`} /></label>
    </div>
    <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-cyber-border-subtle bg-cyber-bg-panel">
      {logs.data && <CollectionLogDetails data={logs.data} />}
      {!!logs.data?.comment_events?.length && <section className="border-b border-cyber-border-subtle p-4 text-sm text-cyber-text-primary" aria-label={t('logs.commentTitle')}>
        <details open><summary className="cursor-pointer font-semibold">{t('logs.commentTitle')} · {logs.data.comment_events.length}</summary>
          <p className="my-3 text-xs text-cyber-text-secondary">{t('logs.commentScope')}</p>
          <ul className="divide-y divide-cyber-border-subtle">{logs.data.comment_events.map((item) => <li key={item.id} className="space-y-1 py-3">
            <p><a href={`https://m.weibo.cn/detail/${encodeURIComponent(item.note_id)}`} target="_blank" rel="noreferrer" className="text-cyber-neon-cyan underline">{item.note_id}</a> · {item.explanation}</p>
            {item.response_message && <p className="break-words text-xs text-cyber-text-secondary">{t('logs.commentMessage')}: {item.response_message}</p>}
            <p className="text-xs text-cyber-text-secondary">HTTP {item.http_status ?? '—'} · ok {item.api_ok ?? '—'} · {item.request_count == null ? t('logs.commentRequestsUnknown') : t('logs.commentRequests', { count: item.request_count })} · {item.exception_type || item.status} · {new Date(item.recorded_at).toLocaleString()}</p>
          </li>)}</ul>
        </details>
      </section>}
      {!!logs.data?.account_events?.length && <section className="border-b border-cyber-border-subtle p-4 text-sm text-cyber-text-primary" aria-label={t('logs.accountTitle')}>
        <details><summary className="cursor-pointer font-semibold">{t('logs.accountTitle')} · {t('logs.accountCount', { count: logs.data.account_events.length })}</summary>
          <p className="my-3 text-xs text-cyber-text-secondary">{t('logs.accountScope')}</p>
          <ul className="divide-y divide-cyber-border-subtle">{logs.data.account_events.slice(0, 200).map((item, index) => <li key={`${item.note_id}:${item.reason}:${index}`} className="space-y-1 py-3">
            <p>{item.nickname || t('unknownAccount')} · {t(item.status === 'excluded' ? 'filters.unqualified' : 'accountIdentityPending')}</p>
            <p className="text-xs text-cyber-text-secondary">{t(`outcomeReasons.${item.reason}`, { defaultValue: item.reason })} {item.evidence}</p>
            <p className="text-xs text-cyber-text-secondary">{item.keyword} · {item.note_id} · {t(item.stage === 'historical' ? 'logs.accountHistorical' : 'logs.accountCollection')} · {new Date(item.recorded_at).toLocaleString()}</p>
          </li>)}</ul>
        </details>
      </section>}
      {error ? <div role="alert" className="space-y-3 p-6 text-sm text-cyber-text-primary"><AlertCircle className="h-5 w-5 text-amber-500" /><p>{t(outdated ? 'logs.outdated' : 'logs.loadFailed')}</p></div>
        : !file ? <p className="p-6 text-sm text-cyber-text-secondary">{t('noData')}</p>
        : logs.isLoading ? <p role="status" className="p-6 text-sm text-cyber-text-secondary">{t('loading')}</p>
        : !logs.data?.task_id ? <p className="p-6 text-sm text-cyber-text-secondary">{t('logs.noHistory')}</p>
        : !entries.length ? <p className="p-6 text-sm text-cyber-text-secondary">{t('logs.noMatches')}</p>
        : <ul className="divide-y divide-cyber-border-subtle">{entries.map((item) => <li key={item.id} className="space-y-3 p-4 md:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3"><div className="flex items-center gap-2">{item.missing ? <AlertCircle className="h-4 w-4 shrink-0 text-amber-500" /> : <CheckCircle2 className="h-4 w-4 shrink-0 text-green-600" />}<h2 className="text-sm font-semibold text-cyber-text-primary">{item.keyword}</h2><span className="rounded bg-cyber-bg-secondary px-2 py-1 text-xs text-cyber-text-secondary">{t('logs.round', { count: item.round })}</span></div><span className="text-xs tabular-nums text-cyber-text-secondary">{t('logs.counts', { retained: item.retained, target: item.target, missing: item.missing })}</span></div>
          <p className="text-sm text-cyber-text-primary">{t(`logs.evidence.${item.evidence}`, { defaultValue: t('logs.evidence.not_recorded') })}</p>
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-cyber-text-secondary"><span>{item.page != null ? t('logs.page', { count: item.page }) : t('logs.unknownPage')}</span><span>{item.recorded_at ? new Date(item.recorded_at).toLocaleString() : t('logs.unknownTime')}</span></div>
          <details className="text-xs text-cyber-text-secondary"><summary className="flex cursor-pointer list-none items-center gap-2 py-1"><ScrollText className="h-3.5 w-3.5" />{t('logs.details')}</summary><dl className="mt-2 grid grid-cols-2 gap-x-5 gap-y-2 rounded-lg bg-cyber-bg-secondary p-3 sm:grid-cols-4">{Object.entries(item.diagnostics).filter(([key]) => key !== 'message_code').map(([key, value]) => <div key={key}><dt>{t(`logs.fields.${key}`)}</dt><dd className="mt-1 font-medium text-cyber-text-primary">{value}</dd></div>)}</dl><p className="mt-2 break-all">{t('logs.reasonCode')}: {item.reason}</p></details>
        </li>)}</ul>}
    </div>
  </div>
}
