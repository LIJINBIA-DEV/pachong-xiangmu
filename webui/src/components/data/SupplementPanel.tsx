import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import axios from 'axios'
import { RefreshCw } from 'lucide-react'
import { dataApi } from '@/lib/api'
import { useCrawlerStore } from '@/store/crawlerStore'
import { Button } from '@/components/ui/button'

export function SupplementPanel({ file, completed, disabled, onFinished }: { file: string; completed: boolean; disabled: boolean; onFinished: () => void }) {
  const { t } = useTranslation('workspace')
  const client = useQueryClient()
  const config = useCrawlerStore((state) => state.config)
  const status = useCrawlerStore((state) => state.status)
  const setStatus = useCrawlerStore((state) => state.setStatus)
  const [setup, setSetup] = useState(false)
  const [target, setTarget] = useState(String(config.max_notes_count || 15))
  const [apiKey, setApiKey] = useState('')
  const [cookies, setCookies] = useState('')
  const lastRunning = useRef(false)
  const callback = useRef(onFinished)
  callback.current = onFinished
  const query = useQuery({ queryKey: ['supplement', file], queryFn: async () => (await dataApi.getSupplement(file)).data, enabled: !!file, retry: 1, refetchInterval: 4000 })
  const plan = query.data
  const busy = status === 'running' || status === 'stopping' || !!plan?.running
  const start = useMutation({
    mutationFn: async () => (await dataApi.supplement(file, plan?.needs_setup ? Number(target) : undefined, plan?.needs_setup ? config : undefined, apiKey.trim() || undefined, cookies.trim() || undefined)).data,
    onSuccess: (data) => {
      client.setQueryData(['supplement', file], data)
      setStatus('running')
      lastRunning.current = true
      setSetup(false)
      setApiKey('')
      setCookies('')
      void client.invalidateQueries({ queryKey: ['crawlerStatus'] })
    },
  })
  useEffect(() => { setSetup(false); setApiKey(''); setCookies(''); start.reset(); lastRunning.current = false }, [file]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (plan?.running) lastRunning.current = true
    if (lastRunning.current && plan && !plan.running && status !== 'running' && status !== 'stopping') {
      lastRunning.current = false
      void client.invalidateQueries({ queryKey: ['manualReview', file] })
      void client.invalidateQueries({ queryKey: ['dataBrowse', file] })
      void client.invalidateQueries({ queryKey: ['dataFiles'] })
      void client.invalidateQueries({ queryKey: ['collectionTasks'] })
      callback.current()
    }
  }, [plan, status, file, client])
  if (!file) return null
  if (query.isError) return <p className="shrink-0 text-xs leading-5 text-cyber-text-secondary" role="status">{t('supplement.backendUnavailable')}</p>
  if (!plan || !plan.supported) return null
  const canStart = completed && plan.review_complete && !plan.needs_qr_login && (plan.needs_setup || (plan.shortfall || 0) > 0)
  const invalidTarget = !Number.isInteger(Number(target)) || Number(target) < 1 || Number(target) > 10000
  const errorDetail = axios.isAxiosError(start.error) ? start.error.response?.data?.detail : null
  const reasons = Object.values(plan.last_results).filter((result) => result.reason !== 'target_reached')
  return <section className="shrink-0 space-y-2 rounded-lg border border-cyber-border-subtle bg-cyber-bg-panel p-3" aria-label={t('supplement.title')}>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm text-cyber-text-primary">{busy ? t('supplement.running') : plan.needs_setup ? t(completed ? 'supplement.legacyReady' : 'supplement.legacyPending') : t((plan.shortfall || 0) > 0 ? 'supplement.shortfall' : 'supplement.reached', { count: plan.shortfall ?? 0, rounds: plan.rounds })}</p>
      {canStart && !setup && <Button variant="outline" size="sm" disabled={disabled || busy || start.isPending} onClick={() => { start.reset(); if (plan.needs_setup || plan.needs_api_key || plan.needs_cookies) setSetup(true); else start.mutate() }}><RefreshCw className="h-4 w-4" />{t('supplement.button')}{plan.shortfall != null ? ` ${plan.shortfall}` : ''}</Button>}
    </div>
    <details className="text-xs text-cyber-text-secondary"><summary className="cursor-pointer py-1">{t('supplement.groupDetails')}</summary><div className="mt-2 max-h-32 overflow-auto"><table className="w-full text-left tabular-nums"><thead><tr>{['keyword', 'target', 'retained', 'pending', 'gap'].map((name) => <th key={name} className="p-1 font-medium">{t(`supplement.columns.${name}`)}</th>)}</tr></thead><tbody>{plan.groups.map((group) => <tr key={group.keyword}><td className="break-words p-1">{group.keyword}</td><td className="p-1">{group.target ?? '—'}</td><td className="p-1">{group.retained}</td><td className="p-1">{group.pending}</td><td className="p-1">{group.shortfall ?? '—'}</td></tr>)}</tbody></table></div></details>
    {!completed && <p className="text-xs leading-5 text-cyber-text-secondary">{t('supplement.finishReview')}</p>}
    {plan.needs_qr_login && <p className="text-xs leading-5 text-cyber-text-secondary"><a href="#/config" className="text-cyber-neon-cyan underline">{t('supplement.qrLoginRequired')}</a></p>}
    {!!reasons.length && !busy && <p className="text-xs leading-5 text-cyber-text-secondary">{t('supplement.lastStopped')}: {[...new Set(reasons.map((result) => t(`supplement.reasons.${result.reason}`, { defaultValue: result.reason })))].join('；')}</p>}
    {setup && <form className="space-y-3 border-t border-cyber-border-subtle pt-3" onSubmit={(event) => { event.preventDefault(); if (!invalidTarget && !busy && !disabled) start.mutate() }}>
      {plan.needs_setup && <><p className="text-xs leading-5 text-cyber-text-secondary">{t('supplement.legacyHint')}</p><p className="text-xs leading-5 text-cyber-text-primary">{t('supplement.settings', { model: config.semantic_filter ? config.semantic_model : t('supplement.semanticOff'), comments: config.max_comments_count ?? 10 })}</p><label className="block text-xs text-cyber-text-secondary">{t('supplement.target')}<input type="number" min="1" max="10000" step="1" value={target} onChange={(event) => setTarget(event.target.value)} required className="mt-1 block h-9 w-40 rounded-md border border-cyber-border bg-cyber-bg-panel px-3 text-sm text-cyber-text-primary focus:outline-none focus:ring-2 focus:ring-cyber-neon-cyan" /></label></>}
      {(plan.needs_api_key || (plan.needs_setup && config.semantic_filter && !config.semantic_model.startsWith('semif'))) && <label className="block text-xs text-cyber-text-secondary">{t('supplement.apiKey')}<input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} className="mt-1 block h-9 w-full max-w-md rounded-md border border-cyber-border bg-cyber-bg-panel px-3 text-sm text-cyber-text-primary focus:outline-none focus:ring-2 focus:ring-cyber-neon-cyan" /></label>}
      {plan.needs_cookies && <label className="block text-xs text-cyber-text-secondary">{t('supplement.cookies')}<input type="password" autoComplete="off" value={cookies} onChange={(event) => setCookies(event.target.value)} required className="mt-1 block h-9 w-full max-w-md rounded-md border border-cyber-border bg-cyber-bg-panel px-3 text-sm text-cyber-text-primary" /></label>}
      <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" type="submit" disabled={invalidTarget || disabled || busy || start.isPending}>{t(start.isPending ? 'supplement.starting' : 'supplement.confirm')}</Button><Button variant="ghost" size="sm" type="button" disabled={start.isPending} onClick={() => { setSetup(false); setApiKey(''); setCookies(''); start.reset() }}>{t('supplement.cancel')}</Button></div>
    </form>}
    {start.isError && <p role="alert" className="break-words text-xs leading-5 text-red-700 dark:text-red-300">{t(`supplement.errors.${errorDetail}`, { defaultValue: t('supplement.startFailed') })}</p>}
  </section>
}
