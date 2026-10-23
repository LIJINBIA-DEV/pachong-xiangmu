import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import axios from 'axios'
import { dataApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import type { ImageSubjectSettings } from '@/types/dataBrowser'

export function ImageRecognitionSettings({ disabled = false, compact = false }: { disabled?: boolean; compact?: boolean }) {
  const { t } = useTranslation('workspace')
  const client = useQueryClient()
  const settings = useQuery({ queryKey: ['imageSettings'], queryFn: async () => (await dataApi.getImageSettings()).data, retry: 1 })
  const [provider, setProvider] = useState<ImageSubjectSettings['provider']>('local')
  const [key, setKey] = useState('')
  const [dirty, setDirty] = useState(false)
  useEffect(() => { if (settings.data && !dirty) setProvider(settings.data.provider) }, [settings.data, dirty])
  const save = useMutation({
    mutationFn: async () => (await dataApi.saveImageSettings(provider, key.trim() || undefined)).data,
    onSuccess: (data) => {
      setKey(''); setDirty(false); client.setQueryData(['imageSettings'], data)
      void client.invalidateQueries({ queryKey: ['imageSubject'] })
    },
  })
  const error = save.error || settings.error
  const code = axios.isAxiosError(error) ? error.response?.data?.detail : undefined
  const locked = disabled || save.isPending || settings.isLoading || settings.isError
  return <section className={compact ? 'config-image-settings' : 'space-y-3 rounded-lg border border-cyber-border-subtle bg-cyber-bg-panel p-3'} aria-label={t('imageSettings.title')}>
    {!compact && <h3 className="text-xs font-semibold text-cyber-text-primary">{t('imageSettings.title')}</h3>}
    <div className={compact ? 'config-image-fields' : 'flex flex-wrap items-end gap-3'}>
      <label className="min-w-48 flex-1 space-y-1 text-xs text-cyber-text-secondary">{t('imageSettings.provider')}<select aria-label={t('imageSettings.provider')} value={provider} disabled={locked} onChange={(e) => { setProvider(e.target.value as ImageSubjectSettings['provider']); setDirty(true); save.reset() }} className="block h-10 w-full rounded-md border border-cyber-border-DEFAULT bg-cyber-bg-panel px-3 text-sm text-cyber-text-primary"><option value="local">{t('imageSettings.local')}</option><option value="siliconflow">{t('imageSettings.cloud')}</option></select></label>
      {provider === 'siliconflow' && <label className="min-w-48 flex-[2] space-y-1 text-xs text-cyber-text-secondary">{t('imageSettings.key')}<input type="password" autoComplete="new-password" spellCheck={false} aria-label={t('imageSettings.key')} value={key} disabled={locked} maxLength={512} onChange={(e) => { setKey(e.target.value); setDirty(true); save.reset() }} placeholder={t(settings.data?.key_configured ? 'imageSettings.keySaved' : 'imageSettings.keyPlaceholder')} className="block h-10 w-full rounded-md border border-cyber-border-DEFAULT bg-cyber-bg-panel px-3 text-sm text-cyber-text-primary" /></label>}
      <Button size="sm" variant="outline" disabled={locked || !dirty || (provider === 'siliconflow' && !settings.data?.key_configured && !key.trim())} onClick={() => save.mutate()}>{t(save.isPending ? 'saving' : 'imageSettings.save')}</Button>
    </div>
    {!compact && <p className="text-xs leading-5 text-cyber-text-secondary">{t(provider === 'siliconflow' ? 'imageSettings.cloudHint' : 'imageSettings.localHint')}</p>}
    {dirty && <p className="text-xs text-amber-600">{t('imageSettings.unsaved')}</p>}
    {save.isSuccess && !dirty && <p role="status" className="text-xs text-green-700">{t('imageSettings.saved')}</p>}
    {error && <p role="alert" className="text-xs text-red-500">{t(`imageSubject.errors.${code || 'generic'}`, { defaultValue: t('imageSettings.failed') })}</p>}
  </section>
}
