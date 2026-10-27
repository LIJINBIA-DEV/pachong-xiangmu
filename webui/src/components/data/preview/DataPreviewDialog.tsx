import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { dataApi } from '@/lib/api'
import { fileLabel } from '@/lib/fileLabels'
import { DataPreviewTable } from './DataPreviewTable'
import type { DataFile } from '@/types/crawler'

interface DataPreviewDialogProps {
  file: DataFile
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function DataPreviewDialog({ file, open, onOpenChange }: DataPreviewDialogProps) {
  const { t } = useTranslation('data')
  const [sheet, setSheet] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['filePreview', file.path, sheet],
    queryFn: async () => {
      const { data } = await dataApi.getFileContent(file.path, 100, sheet || undefined)
      return data
    },
    enabled: open,
  })

  const handleDownload = () => {
    const url = dataApi.getDownloadUrl(file.path)
    window.open(url, '_blank')
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85dvh] w-[calc(100%-1rem)] max-w-6xl flex-col overflow-hidden p-4 md:p-6">
        <DialogHeader className="flex-shrink-0">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-3">
              <DialogTitle className="break-all font-mono text-cyber-neon-cyan">
                {fileLabel(file, t)}
              </DialogTitle>
              <Badge variant="outline" className="font-mono text-[10px]">
                .{file.type.toUpperCase()}
              </Badge>
              {data && (
                <Badge variant="default" className="font-mono text-[10px]">
                  {t('preview.records', { count: data.total })}
                </Badge>
              )}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleDownload}
              className="font-mono text-xs"
            >
              <Download className="w-3 h-3 mr-1" />
              {t('preview.download')}
            </Button>
          </div>
        </DialogHeader>
        {file.file_kind && <p className="shrink-0 break-all text-xs text-cyber-text-secondary">{file.name}</p>}

        {!!data?.sheets?.length && <label className="flex shrink-0 items-center gap-3 text-sm">
          <span>{t('preview.worksheet')}</span>
          <select aria-label={t('preview.worksheet')} value={sheet || data.sheet || ''} onChange={(event) => setSheet(event.target.value)}
            className="min-w-0 rounded border border-cyber-border-subtle bg-cyber-bg-panel px-3 py-2">
            {data.sheets.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>}

        {/* 内容区域 */}
        <div className="flex-1 overflow-hidden min-h-0 mt-4">
          {isLoading ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-cyber-text-muted font-mono animate-pulse">
                {t('preview.loading')}
              </div>
            </div>
          ) : error ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-cyber-neon-pink font-mono">
                {t('preview.error')}
              </div>
            </div>
          ) : data ? (
            <DataPreviewTable
              data={data.data}
              columns={data.columns}
            />
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}
