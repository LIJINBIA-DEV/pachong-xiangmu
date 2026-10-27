import { useTranslation } from 'react-i18next'
import type { CollectionTask } from '@/lib/api'
import { FileCard } from './FileCard'
import { FileTrash } from './FileDeletion'

export function TaskDetails({ task }: { task: CollectionTask }) {
  const { t } = useTranslation('data')
  return <details className="shrink-0 rounded-lg border border-cyber-border-subtle bg-cyber-bg-panel text-sm">
    <summary className="cursor-pointer rounded-lg px-4 py-3 text-cyber-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-neon-cyan">{t('tasks.details')}</summary>
    <div className="max-h-[45dvh] space-y-4 overflow-y-auto border-t border-cyber-border-subtle p-4">
      <p className="text-xs leading-6 text-cyber-text-secondary">{t('tasks.filesHint')}</p>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">{task.files.map((file) => <div key={file.path} className="min-w-0 space-y-2"><p className="text-xs leading-6 text-cyber-text-secondary">{t(file.file_kind === 'semantic' ? 'tasks.semanticHint' : 'tasks.collectionHint')}</p><FileCard file={file} /></div>)}</div>
      <FileTrash />
    </div>
  </details>
}
