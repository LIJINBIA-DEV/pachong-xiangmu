import type { DataFile } from './api'

export function reviewFileSelection(all: DataFile[], chosen: string) {
  const files = all.filter(file => file.type.toLowerCase() === 'xlsx' &&
    !/(_semantic\.xlsx$|comment|creator|guard_replay|semantic_checkpoint)/i.test(file.name))
  const selected = all.find(file => file.path === chosen)
  const main = selected?.review_main === null ? '' : selected?.review_main ?? chosen.replace(/_semantic\.xlsx$/i, '.xlsx')
  const missingMain = /_semantic\.xlsx$/i.test(chosen) && !files.some(file => file.path === main)
  const currentFile = missingMain ? '' : files.some(file => file.path === main) ? main : files[0]?.path || ''
  return { files, currentFile, missingMain }
}
