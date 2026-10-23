import { useEffect, useId, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import axios from 'axios'
import { jevProxyApi, type JevProxyStatus, type SemanticKeyCheckResult } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

type Action = 'save' | 'refresh' | 'select' | 'clear' | 'test'

export function JevProxySettings({ apiKey, disabled = false, onRoutingChange }: {
  apiKey: string
  disabled?: boolean
  onRoutingChange?: () => void
}) {
  const { t } = useTranslation('config')
  const id = useId()
  const client = useQueryClient()
  const settings = useQuery({
    queryKey: ['jevProxy'],
    queryFn: async () => (await jevProxyApi.get()).data,
    retry: false,
    refetchOnWindowFocus: false,
  })
  // Subscription URLs can contain credentials: retain only the unsaved draft in memory.
  const [subscription, setSubscription] = useState('')
  const [draftEnabled, setDraftEnabled] = useState<boolean | null>(null)
  const [pending, setPending] = useState<Action | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<SemanticKeyCheckResult | null>(null)
  const currentKey = useRef(apiKey.trim())
  currentKey.current = apiKey.trim()
  useEffect(() => { setTestResult(null) }, [apiKey])
  const data = settings.data
  const enabled = draftEnabled ?? data?.enabled ?? false
  const dirty = !!subscription.trim() || (draftEnabled !== null && draftEnabled !== data?.enabled)
  const locked = disabled || pending !== null || settings.isFetching
  const canTest = !!data?.enabled && !!data.selected_node && data.nodes.includes(data.selected_node)

  function resetFeedback() {
    setError(null)
    setNotice(null)
    setTestResult(null)
  }
  function showError(cause: unknown) {
    const detail = axios.isAxiosError(cause) ? cause.response?.data?.detail : undefined
    // Never render provider errors, which might include a private subscription URL.
    setError(typeof detail === 'string' && /^[a-z_]+$/.test(detail) ? detail : 'generic')
  }
  async function update(action: Exclude<Action, 'test'>, request: () => Promise<{ data: JevProxyStatus }>) {
    if (locked) return
    setPending(action)
    resetFeedback()
    try {
      const result = (await request()).data
      client.setQueryData(['jevProxy'], result)
      if (action === 'save' || action === 'clear') {
        setSubscription('')
        setDraftEnabled(null)
      }
      setNotice(action === 'refresh' ? 'refreshed' : action === 'select' ? 'nodeSelected' : action === 'clear' ? 'cleared' : 'saved')
      onRoutingChange?.()
    } catch (cause) {
      showError(cause)
      // A failed refresh may change readiness; retrieve the current sanitized state.
      await client.invalidateQueries({ queryKey: ['jevProxy'] })
    } finally {
      setPending(null)
    }
  }
  async function test() {
    if (locked || dirty || !canTest) return
    setPending('test')
    resetFeedback()
    const testedKey = apiKey.trim()
    try {
      const result = (await jevProxyApi.test(testedKey)).data
      if (currentKey.current === testedKey) setTestResult(result)
    } catch (cause) {
      if (currentKey.current === testedKey) showError(cause)
    } finally {
      setPending(null)
    }
  }

  // Older servers and native installs retain the existing configuration UI.
  if (!data?.available) return null
  return <section className="config-jev-proxy" aria-labelledby={`${id}-heading`}>
    <div className="config-jev-heading">
      <h3 id={`${id}-heading`}>{t('jevProxy.title')}</h3>
      <label className="config-choice config-jev-toggle" htmlFor={`${id}-enabled`}>
        <input id={`${id}-enabled`} type="checkbox" checked={enabled} disabled={locked}
          onChange={(event) => { setDraftEnabled(event.target.checked); resetFeedback() }} />
        <span>{t('jevProxy.enabled')}</span>
      </label>
    </div>
    <p className="config-jev-hint">{t('jevProxy.scope')}</p>
    <div className="config-jev-subscription">
      <label className="config-field" htmlFor={`${id}-subscription`}>
        <span>{t('jevProxy.subscription')}</span>
        <Input id={`${id}-subscription`} type="password" autoComplete="new-password" spellCheck={false}
          value={subscription} disabled={locked} maxLength={4096}
          placeholder={t(data.subscription_configured ? 'jevProxy.subscriptionSaved' : 'jevProxy.subscriptionPlaceholder')}
          onChange={(event) => { setSubscription(event.target.value); resetFeedback() }} />
      </label>
      <Button type="button" variant="outline" disabled={locked || !dirty || (enabled && !data.subscription_configured && !subscription.trim())}
        onClick={() => { void update('save', () => jevProxyApi.save({ enabled, subscription_url: subscription.trim() || undefined })) }}>
        {t(pending === 'save' ? 'jevProxy.saving' : 'jevProxy.save')}
      </Button>
    </div>
    <div className="config-jev-node">
      <label className="config-field" htmlFor={`${id}-node`}>
        <span>{t('jevProxy.node')}</span>
        <select id={`${id}-node`} value={data.selected_node || ''} disabled={locked || dirty || !data.enabled || !data.nodes.length}
          onChange={(event) => { const name = event.target.value; void update('select', () => jevProxyApi.selectNode(name)) }}>
          {!data.selected_node && <option value="">{t('jevProxy.noNode')}</option>}
          {data.nodes.map((node) => <option key={node} value={node}>{node}</option>)}
        </select>
      </label>
      <Button type="button" variant="outline" disabled={locked || dirty || !data.subscription_configured}
        onClick={() => { void update('refresh', jevProxyApi.refresh) }}>
        {t(pending === 'refresh' ? 'jevProxy.refreshing' : 'jevProxy.refresh')}
      </Button>
      <Button type="button" variant="outline" disabled={locked || dirty || !canTest} onClick={() => { void test() }}>
        {t(pending === 'test' ? 'jevProxy.testing' : 'jevProxy.test')}
      </Button>
    </div>
    <p className="config-jev-hint">{t('jevProxy.testHint')}</p>
    <div className="config-jev-footer">
      <p>{t(`jevProxy.status.${data.status}`, { defaultValue: t(data.enabled ? 'jevProxy.status.unknown' : 'jevProxy.status.disabled') })}</p>
      <Button type="button" variant="ghost" disabled={locked || dirty || !data.subscription_configured}
        onClick={() => { void update('clear', () => jevProxyApi.save({ enabled: false, clear_subscription: true })) }}>
        {t(pending === 'clear' ? 'jevProxy.clearing' : 'jevProxy.clear')}
      </Button>
    </div>
    <div className="config-jev-feedback" aria-live="polite">
      {dirty && <p>{t('jevProxy.unsaved')}</p>}
      {notice && !dirty && <p role="status" className="config-success">{t(`jevProxy.${notice}`)}</p>}
      {error && <p role="alert" className="config-error">{t(`jevProxy.errors.${error}`, { defaultValue: t('jevProxy.errors.generic') })}</p>}
      {settings.isError && <p role="alert" className="config-error">{t('jevProxy.errors.status_unavailable')}</p>}
      {testResult && <p role="status" className={testResult.ok ? 'config-success' : 'config-error'}>
        {testResult.http_status === 451 ? t('jevProxy.regionRejected') : t(`field.semanticKeyCheckResult.${testResult.reason}`, { status: testResult.http_status ?? '' })}
      </p>}
    </div>
  </section>
}
