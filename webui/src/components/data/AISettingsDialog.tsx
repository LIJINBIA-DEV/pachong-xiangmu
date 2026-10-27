import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as Dialog from '@radix-ui/react-dialog'
import { useTranslation } from 'react-i18next'
import { Settings2, X } from 'lucide-react'
import axios from 'axios'
import { dataApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import type { AISettingsInput, SummaryScope } from '@/types/contentSummary'
import './TaskSummary.css'

export function AISettingsDialog() {
  const { t } = useTranslation('data')
  const [open, setOpen] = useState(false)
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [scope, setScope] = useState<SummaryScope>('retained')
  const [maxPosts, setMaxPosts] = useState<number | ''>(100)
  const [comments, setComments] = useState(false)
  const [key, setKey] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['aiSettings'], enabled: open, queryFn: async () => (await dataApi.getAISettings()).data, retry: 1, refetchOnWindowFocus: false })
  const save = useMutation({
    mutationFn: async (value: AISettingsInput) => (await dataApi.saveAISettings(value)).data,
    onSuccess: data => {
      setKey(''); setClearKey(false)
      client.setQueryData(['aiSettings'], data)
      void client.invalidateQueries({ queryKey: ['contentSummary'] })
    },
  })
  useEffect(() => {
    if (!open || !settings.data) return
    const data = settings.data
    setBaseUrl(data.base_url); setModel(data.model); setScope(data.scope); setMaxPosts(data.max_posts); setComments(data.include_comments)
  }, [open, settings.data])
  function changeOpen(value: boolean) { setOpen(value); setKey(''); setClearKey(false); save.reset() }
  const invalid = !baseUrl.trim() || !model.trim() || !Number.isInteger(maxPosts) || Number(maxPosts) < 1 || Number(maxPosts) > 500
  const error = save.error || settings.error
  const code = axios.isAxiosError(error) ? error.response?.data?.detail : undefined
  const endpointChanged = !!settings.data?.base_url && settings.data.base_url !== baseUrl.trim().replace(/\/$/, '')
  return <Dialog.Root open={open} onOpenChange={changeOpen}>
    <Dialog.Trigger asChild><Button variant="outline" className="ai-settings-trigger"><Settings2 aria-hidden="true" />{t('aiSettings.title')}</Button></Dialog.Trigger>
    <Dialog.Portal><Dialog.Overlay className="content-summary-overlay" /><Dialog.Content className="content-summary-dialog ai-settings-dialog" aria-describedby="ai-settings-description">
      <header className="content-summary-header"><Dialog.Title>{t('aiSettings.title')}</Dialog.Title><Dialog.Close aria-label={t('aiSettings.close')}><X size={20} /></Dialog.Close></header>
      <div className="content-summary-body">
        <Dialog.Description id="ai-settings-description">{t('aiSettings.description')}</Dialog.Description>
        {settings.isLoading ? <p>{t('summary.loading')}</p> : settings.isError ? <p className="summary-error" role="alert">{t('aiSettings.readFailed')} <button onClick={() => { void settings.refetch() }}>{t('summary.refresh')}</button></p> : <form className="summary-form ai-settings-form" onSubmit={event => {
          event.preventDefault()
          if (!invalid && !save.isPending) save.mutate({ base_url: baseUrl.trim(), model: model.trim(), scope, max_posts: Number(maxPosts), include_comments: comments, api_key: key.trim() || undefined, clear_key: clearKey })
        }}>
          <label>{t('aiSettings.endpoint')}<input type="url" value={baseUrl} maxLength={1000} required placeholder={t('aiSettings.endpointPlaceholder')} disabled={save.isPending} onChange={event => { setBaseUrl(event.target.value); save.reset() }} /><span>{t('aiSettings.endpointHint')}</span></label>
          <label>{t('summary.model')}<input value={model} maxLength={120} required placeholder={t('aiSettings.modelPlaceholder')} disabled={save.isPending} onChange={event => { setModel(event.target.value); save.reset() }} /></label>
          <label>{t('summary.key')}<input type="password" value={key} autoComplete="off" spellCheck={false} maxLength={512} disabled={save.isPending} placeholder={t(settings.data?.key_configured ? 'summary.keyConfigured' : 'summary.keyPlaceholder')} onChange={event => { setKey(event.target.value); save.reset() }} /></label>
          <div className="summary-options"><span className="summary-hint">{t(settings.data?.key_configured ? 'aiSettings.keySaved' : 'aiSettings.keyMissing')}</span>{settings.data?.key_configured && <label className="summary-comments"><input type="checkbox" checked={clearKey} disabled={save.isPending} onChange={event => { setClearKey(event.target.checked); save.reset() }} />{t('aiSettings.clearKey')}</label>}</div>
          {endpointChanged && settings.data?.key_configured && <p className="summary-hint">{t('aiSettings.endpointChanged')}</p>}
          <div className="summary-form-grid ai-settings-options"><label>{t('summary.scope')}<select value={scope} disabled={save.isPending} onChange={event => { setScope(event.target.value as SummaryScope); save.reset() }}>{(['retained', 'available'] as const).map(value => <option key={value} value={value}>{t(`summary.scopes.${value}`)}</option>)}</select></label><label>{t('summary.limit')}<input type="number" min={1} max={500} value={maxPosts} disabled={save.isPending} onChange={event => { setMaxPosts(event.target.value === '' ? '' : Number(event.target.value)); save.reset() }} /></label></div>
          <label className="summary-comments"><input type="checkbox" checked={comments} disabled={save.isPending} onChange={event => { setComments(event.target.checked); save.reset() }} />{t('summary.includeComments')}</label>
          {error && <p className="summary-error" role="alert">{t(`summary.errors.${typeof code === 'string' ? code : 'summary_settings_storage_failed'}`, { defaultValue: t('aiSettings.saveFailed') })}</p>}
          {save.isSuccess && <p className="ai-settings-saved" role="status">{t(save.data.ready ? 'aiSettings.saved' : 'aiSettings.savedIncomplete')}</p>}
          <div className="summary-actions"><Button type="submit" disabled={invalid || save.isPending}>{t(save.isPending ? 'aiSettings.saving' : 'aiSettings.save')}</Button><Dialog.Close asChild><Button variant="outline" type="button">{t('aiSettings.done')}</Button></Dialog.Close></div>
        </form>}
      </div>
    </Dialog.Content></Dialog.Portal>
  </Dialog.Root>
}
