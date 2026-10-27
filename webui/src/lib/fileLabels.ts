import type { TFunction } from 'i18next'
import type { CollectionTask, DataFile } from './api'
import { formatDateTime } from './utils'

export function taskLabel(task: CollectionTask, t: TFunction<'data'>): string {
  return `${task.title || t('tasks.untitled')} · ${t(`file.platforms.${task.platform}`, { defaultValue: task.platform })} · ${formatDateTime(task.modified_at)}`
}

export function fileLabel(file: DataFile, t: TFunction<'data'>): string {
  const kind = file.file_kind || (file.name.endsWith('_semantic.xlsx') ? 'semantic' : null)
  if (!kind) return file.name
  const platform = file.path.split('/')[0]
  const knownPlatforms = ['xhs', 'wb', 'weibo', 'dy', 'ks', 'bili', 'bilibili', 'zhihu', 'tieba']
  const label = t(kind === 'semantic' ? 'file.semanticRecord' : 'file.collectionResult')
  return knownPlatforms.includes(platform) ? `${t(`file.platforms.${platform}`)} · ${label}` : label
}
