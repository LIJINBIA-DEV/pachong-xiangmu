import { create } from 'zustand'
import type { LogEntry, CrawlerConfig } from '@/types/crawler'
import { keywordSearchConfig } from '@/lib/keywordSearches'
import { loadConfig, saveConfig } from './configStorage'

interface CrawlerState {
  // Status
  status: 'idle' | 'running' | 'stopping' | 'error'
  platform: string | null
  crawlerType: string | null
  startedAt: string | null

  // Logs
  logs: LogEntry[]
  clearedAfterLogId: number | null  // 清除日志后，只显示 id 大于此值的日志

  // Config
  config: CrawlerConfig
  keywordText: string

  // Actions
  setStatus: (status: CrawlerState['status']) => void
  setRunningInfo: (platform: string | null, crawlerType: string | null, startedAt: string | null) => void
  addLog: (log: LogEntry) => void
  setLogs: (logs: LogEntry[]) => void
  clearLogs: () => void
  restoreLogs: () => void
  updateConfig: (config: Partial<CrawlerConfig>) => void
  updateKeywordText: (value: string) => void
  reset: () => void
}

// 持久化相关的 localStorage key
const CLEARED_LOG_ID_KEY = 'mediacrawler_cleared_log_id'

// 从 localStorage 读取清除标记
function getClearedLogIdFromStorage(): number | null {
  try {
  const stored = localStorage.getItem(CLEARED_LOG_ID_KEY)
  if (stored === null) return null
  const value = parseInt(stored, 10)
  return isNaN(value) ? null : value
  } catch { return null }
}

// 保存清除标记到 localStorage
function saveClearedLogIdToStorage(id: number | null): void {
  try {
  if (id === null) {
    localStorage.removeItem(CLEARED_LOG_ID_KEY)
  } else {
    localStorage.setItem(CLEARED_LOG_ID_KEY, id.toString())
  }
  } catch { /* The app still works without browser storage. */ }
}

const defaultConfig: CrawlerConfig = {
  platform: 'wb',
  login_type: 'qrcode',
  login_environment: 'auto',
  crawler_type: 'search',
  keywords: '',
  specified_ids: '',
  creator_ids: '',
  start_page: 1,
  max_notes_count: 15,
  max_comments_count: 50,
  enable_comments: true,
  enable_sub_comments: false,
  enable_media: false,
  image_subject_recognition: true,
  save_option: 'excel',
  cookies: '',
  headless: false,
  semantic_filter: false,
  semantic_model: 'jev-1.13.0',
  keyword_pairs: [],
}

export const useCrawlerStore = create<CrawlerState>((set, get) => ({
  status: 'idle',
  platform: null,
  crawlerType: null,
  startedAt: null,
  logs: [],
  clearedAfterLogId: getClearedLogIdFromStorage(), // 从 localStorage 初始化
  ...loadConfig(defaultConfig),

  setStatus: (status) => {
    set({ status })
    // 当开始新的爬虫任务时，清除之前的清除标记
    if (status === 'running') {
      const currentClearedId = get().clearedAfterLogId
      if (currentClearedId !== null) {
        set({ clearedAfterLogId: null })
        saveClearedLogIdToStorage(null)
      }
    }
  },

  setRunningInfo: (platform, crawlerType, startedAt) => {
    set({ platform, crawlerType, startedAt })
    // 当设置新的运行信息时，也清除之前的清除标记
    if (startedAt !== null) {
      const currentClearedId = get().clearedAfterLogId
      if (currentClearedId !== null) {
        set({ clearedAfterLogId: null })
        saveClearedLogIdToStorage(null)
      }
    }
  },

  addLog: (log) => {
    const { clearedAfterLogId, logs } = get()
    // 如果有清除标记，过滤掉 id 小于等于该标记的日志
    if (clearedAfterLogId !== null && log.id <= clearedAfterLogId) {
      return
    }
    // 防止 WebSocket 重连/重复连接导致的重复日志
    if (logs.length > 0 && logs[logs.length - 1].id === log.id) {
      return
    }
    if (logs.some((existing) => existing.id === log.id)) {
      return
    }
    set((state) => ({
      logs: [...state.logs.slice(-499), log], // Keep last 500 logs
    }))
  },

  setLogs: (logs) => {
    const { clearedAfterLogId } = get()
    // 如果有清除标记，过滤掉 id 小于等于该标记的日志
    const filteredLogs = clearedAfterLogId !== null
      ? logs.filter((log) => log.id > clearedAfterLogId)
      : logs
    set({ logs: filteredLogs })
  },

  clearLogs: () => {
    const { logs } = get()
    // 记录当前最大的 log id，清除后只显示比这个 id 大的日志
    const maxLogId = logs.length > 0 ? Math.max(...logs.map(l => l.id)) : 0
    set({ logs: [], clearedAfterLogId: maxLogId })
    // 持久化到 localStorage
    saveClearedLogIdToStorage(maxLogId)
  },

  restoreLogs: () => {
    // 清除清除标记，这样下次重新加载日志时就会显示所有日志
    set({ clearedAfterLogId: null })
    saveClearedLogIdToStorage(null)
  },

  updateKeywordText: (keywordText) => set((state) => ({
    keywordText,
    config: { ...state.config, ...keywordSearchConfig(keywordText) },
  })),

  updateConfig: (config) =>
    set((state) => ({
      config: { ...state.config, ...config },
    })),

  reset: () =>
    set({
      status: 'idle',
      platform: null,
      crawlerType: null,
      startedAt: null,
    }),
}))

useCrawlerStore.subscribe((state, previous) => {
  if (state.config !== previous.config || state.keywordText !== previous.keywordText) {
    saveConfig(state.config, state.keywordText)
  }
})
