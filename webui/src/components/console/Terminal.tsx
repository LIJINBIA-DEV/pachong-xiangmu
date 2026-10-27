import { useState, useEffect, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronUp, Trash2, History, Pause, Play } from 'lucide-react'
import { TerminalLine } from './TerminalLine'
import { useCrawlerStore } from '@/store/crawlerStore'
import { crawlerApi } from '@/lib/api'
import type { LogEntry } from '@/types/crawler'
import { Button } from '@/components/ui/button'
import { DataExplorerDialog } from '@/components/data/DataExplorerDialog'

export function Terminal({ fullHeight = false, active = true }: { fullHeight?: boolean; active?: boolean }) {
  const { t } = useTranslation('terminal')
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [pausedLogs, setPausedLogs] = useState<LogEntry[] | null>(null)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState(false)
  const logs = useCrawlerStore(state => state.logs)
  const totalLogCount = useCrawlerStore(state => state.totalLogCount)
  const session = useCrawlerStore(state => state.logSessionId)
  const status = useCrawlerStore(state => state.status)
  const scrollRef = useRef<HTMLDivElement>(null)
  const displayLogs = pausedLogs ?? logs.slice(historyLoaded ? -500 : -50)
  const paused = pausedLogs !== null
  const displayLogsRef = useRef(displayLogs)
  displayLogsRef.current = displayLogs
  const inspectLog = useCallback(() => setPausedLogs(displayLogsRef.current), [])

  useEffect(() => {
    setPausedLogs(null)
    setHistoryLoaded(false)
    setHistoryError(false)
  }, [session])

  useEffect(() => {
    if (active && scrollRef.current && !isCollapsed && !paused) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs, active, isCollapsed, paused, historyLoaded])

  const loadHistory = async () => {
    setHistoryLoading(true)
    setHistoryError(false)
    try {
      const { data } = await crawlerApi.getLogs(500)
      const store = useCrawlerStore.getState()
      if (store.logSessionId !== session) return
      store.restoreLogs()
      store.receiveLogs(data.logs)
      setHistoryLoaded(true)
      setPausedLogs(null)
    } catch {
      setHistoryError(true)
    } finally {
      setHistoryLoading(false)
    }
  }

  return (
    <div className={`flex flex-col rounded-lg overflow-hidden border border-cyber-border-subtle bg-[#0d1117] ${isCollapsed ? 'h-auto shrink-0' : fullHeight ? 'min-h-0 flex-1' : 'h-[45vh] min-h-[320px] max-h-[560px]'}`}>
      <div className="flex flex-wrap gap-2 items-center justify-between px-4 py-2.5 bg-[#161b22] border-b border-[#30363d] flex-shrink-0">
        <div className="flex items-center gap-3 text-xs text-[#8b949e]">
          <span>{t('header.title')}</span>
          <span>{t('header.entries', { count: totalLogCount, visible: displayLogs.length })}</span>
          <span className={paused ? 'text-amber-400' : 'text-emerald-400'}>{t(paused ? 'header.paused' : 'header.following')}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setPausedLogs(paused ? null : displayLogs)} className="h-7 px-2 text-[#c9d1d9]">
            {paused ? <Play className="w-3 h-3 mr-1" /> : <Pause className="w-3 h-3 mr-1" />}
            {t(paused ? 'header.follow' : 'header.pause')}
          </Button>
          <Button variant="ghost" size="sm" onClick={loadHistory} disabled={historyLoading} title={t('header.historyHint')} className="h-7 px-2 text-[#c9d1d9]">
            <History className="w-3 h-3 mr-1" />{t(historyLoading ? 'header.loading' : 'header.history')}
          </Button>
          <DataExplorerDialog />
          <Button variant="ghost" size="sm" onClick={() => {
            useCrawlerStore.getState().clearLogs()
            setPausedLogs(null)
          }} disabled={logs.length === 0 && displayLogs.length === 0} className="h-7 px-2 text-[#8b949e]" title={t('header.clear')} aria-label={t('header.clear')}>
            <Trash2 className="w-4 h-4" />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setIsCollapsed(!isCollapsed)} className="h-7 px-2 text-[#8b949e]" aria-label={t(isCollapsed ? 'header.expand' : 'header.collapse')}>
            {isCollapsed ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
          </Button>
        </div>
      </div>
      {!isCollapsed && <>
        <div ref={scrollRef} onScroll={event => {
          const element = event.currentTarget
          if (!paused && element.scrollHeight - element.scrollTop - element.clientHeight > 24) setPausedLogs(displayLogs)
        }} className="flex-1 overflow-auto p-4 font-mono text-sm terminal-scroll bg-[#0d1117] min-h-0" style={{ overflowAnchor: 'none' }}>
          {displayLogs.length === 0 ? <p className="text-xs text-[#8b949e]">{t('banner.configHint')}</p> : (
            <div className="space-y-0.5">
              {displayLogs.map(log => <TerminalLine key={`${log.session_id ?? session}:${log.id}`} log={log} onInspect={inspectLog} />)}
            </div>
          )}
        </div>
        <div className="px-4 py-2 border-t border-[#30363d] bg-[#161b22] flex gap-3 justify-between flex-shrink-0 text-xs text-[#8b949e]">
          <span role={historyError ? 'alert' : undefined} className={historyError ? 'text-red-400' : ''}>
            {t(historyError ? 'footer.historyError' : paused ? 'footer.paused' : historyLoaded ? 'header.historyHint' : 'footer.recent')}
          </span>
          <span>{status.toUpperCase()}</span>
        </div>
      </>}
    </div>
  )
}
