import { useTranslation } from 'react-i18next'
import { useState } from 'react'
import { Database } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
} from '@/components/ui/dialog'
import { DataExplorer } from './DataExplorer'
import { DataBrowser } from './DataBrowser'

export function DataExplorerDialog() {
  const { t } = useTranslation('data')
  const [mode, setMode] = useState<'files' | 'browse'>('files')
  const [file, setFile] = useState('')

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="font-mono text-xs text-[#c9d1d9] border-[#30363d] bg-transparent hover:bg-[#21262d] hover:text-[#00ffff] hover:border-[#00ffff]/50"
        >
          <Database className="w-3.5 h-3.5" />
          {t('dialog.button')}
        </Button>
      </DialogTrigger>
      <DialogContent className={mode === 'browse' ? 'flex h-[90dvh] w-[calc(100%-1rem)] max-w-7xl flex-col overflow-hidden p-4 md:p-6' : 'w-[calc(100%-1rem)] max-w-5xl max-h-[85vh] overflow-hidden'}>
        <DialogHeader>
          <DialogTitle>{t('dialog.title')}</DialogTitle>
          <DialogDescription className="sr-only">{t('browse.description')}</DialogDescription>
        </DialogHeader>
        <div className="flex shrink-0 gap-2 border-b border-cyber-border-subtle pb-3">
          <Button variant={mode === 'files' ? 'default' : 'ghost'} size="sm" onClick={() => setMode('files')} aria-pressed={mode === 'files'}>{t('browse.files')}</Button>
          <Button variant={mode === 'browse' ? 'default' : 'ghost'} size="sm" onClick={() => setMode('browse')} aria-pressed={mode === 'browse'}>{t('browse.title')}</Button>
        </div>
        {mode === 'browse' ? <DataBrowser key={file} initialFile={file} /> : <div className="overflow-auto max-h-[calc(85vh-160px)] pr-2"><DataExplorer onBrowse={(path) => { setFile(path); setMode('browse') }} /></div>}
      </DialogContent>
    </Dialog>
  )
}
