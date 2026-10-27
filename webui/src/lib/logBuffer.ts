import type { LogEntry } from '@/types/crawler'

export function mergeLogBatch(current: LogEntry[], incoming: LogEntry[], cutoff: number | null): LogEntry[] {
  const ids = new Set(current.map(log => log.id))
  const additions = incoming.filter(log => {
    if ((cutoff !== null && log.id <= cutoff) || ids.has(log.id)) return false
    ids.add(log.id)
    return true
  })
  return additions.length ? [...current, ...additions].sort((a, b) => a.id - b.id).slice(-500) : current
}

export function createLogBuffer(receive: (logs: LogEntry[], session?: string) => void) {
  let pending: LogEntry[] = []
  let session: string | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  const flush = () => {
    clearTimeout(timer)
    timer = undefined
    const batch = pending
    pending = []
    receive(batch, session)
  }
  return {
    push(logs: LogEntry[], nextSession?: string) {
      if (nextSession && session && nextSession !== session) pending = []
      session = nextSession || session
      pending.push(...logs)
      timer ??= setTimeout(flush, 100)
    },
    flush,
  }
}
