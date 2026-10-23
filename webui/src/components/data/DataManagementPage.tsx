import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { DataExplorer } from './DataExplorer'
import { DataBrowser } from './DataBrowser'

export function DataManagementPage() {
  const { t } = useTranslation('data')
  const [mode, setMode] = useState<'files' | 'browse'>('files')
  const [file, setFile] = useState('')
  return <div className="flex min-h-0 flex-1 flex-col gap-4">
    <div className="flex shrink-0 gap-2 border-b border-cyber-border-subtle pb-3">
      <Button size="sm" variant={mode === 'files' ? 'default' : 'ghost'} aria-pressed={mode === 'files'} onClick={() => setMode('files')}>{t('browse.files')}</Button>
      <Button size="sm" variant={mode === 'browse' ? 'default' : 'ghost'} aria-pressed={mode === 'browse'} onClick={() => setMode('browse')}>{t('browse.title')}</Button>
    </div>
    {mode === 'files' ? <div className="min-h-0 flex-1 overflow-y-auto"><DataExplorer onBrowse={(path) => { setFile(path); setMode('browse') }} /></div>
      : <DataBrowser key={file} initialFile={file} />}
  </div>
}
