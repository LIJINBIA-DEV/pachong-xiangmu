import { ImageRecognitionSettings } from '../config/ImageRecognitionSettings'
import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ScanEye } from 'lucide-react'
import axios from 'axios'
import { Button } from '@/components/ui/button'
import { dataApi } from '@/lib/api'
import { useCrawlerStore } from '@/store/crawlerStore'

const active = (status?: string) => ['queued', 'loading', 'running'].includes(status || '')

export function ImageSubjectPanel({ file }: { file: string }) {
  const { t } = useTranslation('workspace')
  const queryClient = useQueryClient()
  const crawlerStatus = useCrawlerStore((state) => state.status)
  const lastStatus = useRef('')
  const status = useQuery({
    queryKey: ['imageSubject', file], enabled: !!file, retry: 1,
    queryFn: async () => (await dataApi.getImageSubject(file)).data,
    refetchInterval: (query) => active(query.state.data?.status) || query.state.data?.busy || crawlerStatus === 'running' ? 2000 : false,
  })
  const start = useMutation({
    mutationFn: async () => (await dataApi.recognizeImages(file)).data,
    onSuccess: (data) => { queryClient.setQueryData(['imageSubject', file], data); void queryClient.invalidateQueries({ queryKey: ['manualReview', file] }) },
  })
  const data = status.data
  useEffect(() => {
    if (!data) return
    // Refresh automatic image marks while a batch runs and once it finishes.
    // The backend preserves human overrides during cache synchronization.
    if (active(data.status) || lastStatus.current !== data.status) {
      void queryClient.invalidateQueries({ queryKey: ['manualReview', file] })
      void queryClient.invalidateQueries({ queryKey: ['supplement', file] })
    }
    lastStatus.current = data.status
  }, [data?.status, data?.completed, file, queryClient])
  const error = start.error || status.error
  const code = axios.isAxiosError(error) ? error.response?.data?.detail : undefined
  const isRunning = active(data?.status) && data?.busy
  return <section className="shrink-0 space-y-2 rounded-lg border border-cyber-border-subtle bg-cyber-bg-panel p-3" aria-label={t('imageSubject.title')}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="space-y-1"><p className="flex items-center gap-2 text-xs font-semibold text-cyber-text-primary"><ScanEye className="h-4 w-4" />{t('imageSubject.title')} · {t(data?.provider === 'siliconflow' ? 'imageSettings.cloud' : 'imageSettings.local')}</p><p role="status" className="text-xs text-cyber-text-secondary">{data ? t('imageSubject.progress', { done: data.completed, total: data.total, missing: data.not_downloaded, failed: data.failed }) : t('imageSubject.loading')}</p></div>
      <Button variant="outline" size="sm" disabled={!file || !data?.ready || !data.total || data.busy || crawlerStatus === 'running' || crawlerStatus === 'stopping' || start.isPending} onClick={() => start.mutate()}>{t(isRunning || start.isPending ? 'imageSubject.running' : 'imageSubject.start')}</Button>
    </div>
    <p className="text-xs leading-5 text-cyber-text-secondary">{t('imageSubject.hint')}</p>
    <ImageRecognitionSettings disabled={!!data?.busy || crawlerStatus === 'running' || crawlerStatus === 'stopping'} />
    {data && !data.ready && <p role="alert" className="text-xs text-cyber-neon-orange">{t(data.provider === 'siliconflow' ? 'imageSubject.keyMissing' : 'imageSubject.modelMissing')}</p>}
    {(error || data?.status === 'error' || data?.status === 'interrupted') && <p role="alert" className="text-xs text-cyber-neon-orange">{t(`imageSubject.errors.${code || data?.error || 'generic'}`, { defaultValue: t('imageSubject.errors.generic') })}</p>}
  </section>
}
