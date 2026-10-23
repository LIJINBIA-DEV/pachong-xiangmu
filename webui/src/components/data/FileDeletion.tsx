import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { RotateCcw, Trash2 } from 'lucide-react'
import { dataApi, type DataFile, type TrashFile } from '@/lib/api'
import { useCrawlerStore } from '@/store/crawlerStore'
import { formatFileSize, formatDateTime } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'

function errorKey(error: unknown) {
  const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  if (detail === 'collection_active') return 'trash.active'
  if (detail === 'restore_conflict') return 'trash.conflict'
  if (detail === 'file_in_use') return 'trash.inUse'
  return 'trash.error'
}

function useFileRefresh() {
  const client = useQueryClient()
  return async () => {
    await Promise.all(['dataFiles', 'dataTrash', 'dataBrowse', 'manualReview', 'supplement'].map((key) => client.invalidateQueries({ queryKey: [key] })))
  }
}

export function DeleteFileButton({ file }: { file: DataFile }) {
  const { t } = useTranslation('data')
  const [open, setOpen] = useState(false)
  const refresh = useFileRefresh()
  const status = useCrawlerStore((state) => state.status)
  const active = status === 'running' || status === 'stopping'
  const remove = useMutation({ mutationFn: () => dataApi.deleteFile(file.path), onSuccess: async () => { setOpen(false); await refresh() } })
  return <>
    <Button variant="ghost" size="sm" className="h-8 px-2 text-red-700 hover:bg-red-50 hover:text-red-800 dark:text-red-400 dark:hover:bg-red-950" disabled={active} title={active ? t('trash.active') : undefined} onClick={() => { remove.reset(); setOpen(true) }}><Trash2 className="h-3.5 w-3.5" />{t('trash.delete')}</Button>
    <Dialog open={open} onOpenChange={(value) => { if (!remove.isPending) setOpen(value) }}>
      <DialogContent className="max-w-[calc(100vw-2rem)] sm:max-w-lg">
        <DialogTitle>{t('trash.confirmTitle')}</DialogTitle>
        <DialogDescription>{t('trash.confirmHint')}</DialogDescription>
        <p className="break-all text-sm text-cyber-text-primary">{file.path}</p>
        {remove.isError && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{t(errorKey(remove.error))}</p>}
        <DialogFooter>
          <Button variant="outline" disabled={remove.isPending} onClick={() => setOpen(false)}>{t('trash.cancel')}</Button>
          <Button disabled={remove.isPending || active} className="bg-red-700 text-white hover:bg-red-800" onClick={() => remove.mutate()}><Trash2 className="h-4 w-4" />{t(remove.isPending ? 'trash.deleting' : 'trash.move')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>
}

export function FileTrash() {
  const { t } = useTranslation('data')
  const [open, setOpen] = useState(false)
  const [purgeTarget, setPurgeTarget] = useState<TrashFile | null>(null)
  const refresh = useFileRefresh()
  const status = useCrawlerStore((state) => state.status)
  const active = status === 'running' || status === 'stopping'
  const query = useQuery({ queryKey: ['dataTrash'], queryFn: async () => (await dataApi.getTrash()).data.files, enabled: open, retry: 1 })
  const restore = useMutation({ mutationFn: (id: string) => dataApi.restoreFile(id), onSuccess: refresh })
  const purge = useMutation({ mutationFn: (id: string) => dataApi.purgeFile(id), onSuccess: async () => { setPurgeTarget(null); await refresh() } })
  return <>
    <Button variant="outline" size="sm" onClick={() => { setOpen(!open); restore.reset(); purge.reset() }} disabled={purge.isPending} aria-expanded={open}><Trash2 className="h-4 w-4" />{t('trash.title')}</Button>
    {open && <section aria-label={t('trash.title')} className="basis-full space-y-3 rounded-lg border border-cyber-border-subtle bg-cyber-bg-panel p-4">
      <p className="text-sm text-cyber-text-secondary">{t('trash.hint')}</p>
      {query.isLoading ? <p className="text-sm text-cyber-text-secondary">{t('trash.loading')}</p>
        : query.isError ? <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-cyber-text-primary">{t('trash.loadError')}<Button variant="outline" size="sm" onClick={() => query.refetch()}>{t('browse.retry')}</Button></div>
        : !query.data?.length ? <p className="text-sm text-cyber-text-secondary">{t('trash.empty')}</p>
        : <ul className="divide-y divide-cyber-border-subtle">{query.data.map((file) => <li key={file.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
          <div className="min-w-0 flex-1"><p className="break-all text-sm text-cyber-text-primary">{file.path}</p><p className="mt-1 text-xs text-cyber-text-secondary">{formatFileSize(file.size)} · {formatDateTime(file.deleted_at)}</p></div>
          <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" disabled={restore.isPending || purge.isPending || active} title={active ? t('trash.active') : undefined} aria-label={t('trash.restoreFile', { name: file.name })} onClick={() => { restore.reset(); purge.reset(); restore.mutate(file.id) }}><RotateCcw className="h-4 w-4" />{t('trash.restore')}</Button>
            <Button variant="outline" size="sm" className="text-red-700 hover:bg-red-50 hover:text-red-800 dark:text-red-400 dark:hover:bg-red-950" disabled={restore.isPending || purge.isPending || active} title={active ? t('trash.active') : undefined} aria-label={t('trash.purgeFile', { name: file.name })} onClick={() => { restore.reset(); purge.reset(); setPurgeTarget(file) }}><Trash2 className="h-4 w-4" />{t('trash.purge')}</Button></div>
        </li>)}</ul>}
      {restore.isError && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{t(errorKey(restore.error))}</p>}
      {restore.isSuccess && <p role="status" className="text-sm text-cyber-text-primary">{t('trash.restored')}</p>}
      {purge.isSuccess && <p role="status" className="text-sm text-cyber-text-primary">{t('trash.purged')}</p>}
    </section>}
    <Dialog open={!!purgeTarget} onOpenChange={(value) => { if (!value && !purge.isPending) setPurgeTarget(null) }}>
      <DialogContent className="max-w-[calc(100vw-2rem)] sm:max-w-lg">
        <DialogTitle>{t('trash.purgeTitle')}</DialogTitle>
        <DialogDescription>{t('trash.purgeHint')}</DialogDescription>
        <p className="break-all text-sm text-cyber-text-primary">{purgeTarget?.path}</p>
        {purge.isError && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{t(errorKey(purge.error))}</p>}
        <DialogFooter><Button variant="outline" disabled={purge.isPending} onClick={() => setPurgeTarget(null)}>{t('trash.cancel')}</Button><Button disabled={purge.isPending || active} className="bg-red-700 text-white hover:bg-red-800" onClick={() => { if (purgeTarget) purge.mutate(purgeTarget.id) }}><Trash2 className="h-4 w-4" />{t(purge.isPending ? 'trash.purging' : 'trash.purge')}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </>
}
