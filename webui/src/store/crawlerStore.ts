import { create } from 'zustand'
import type { LogEntry, CrawlerConfig } from '@/types/crawler'
import { topicFromText, topicSearchConfig, type TopicCard } from '@/lib/topicCards'
import { loadConfig, saveConfig } from './configStorage'
import { mergeLogBatch } from '@/lib/logBuffer'

interface CrawlerState {
  // Status
  status: 'idle' | 'running' | 'stopping' | 'error'
  stage: 'idle' | 'waiting_login' | 'starting' | 'running'
  platform: string | null
  crawlerType: string | null
  startedAt: string | null

  // Logs
  logs: LogEntry[]
  totalLogCount: number
  logSessionId: string | null
  receiveLogs: (logs: LogEntry[], sessionId?: string) => void
  clearedAfterLogId: number | null  // 清除日志后，只显示 id 大于此值的日志

  // Config
  config: CrawlerConfig
  keywordText: string
  collectionTopics: TopicCard[]
  updateCollectionTopics: (cards: TopicCard[]) => void

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
  publish_time_range: 'all',
  publish_start_date: '',
  publish_end_date: '',
  max_notes_count: 15,
  max_comments_count: 50,
  enable_comments: true,
  enable_sub_comments: false,
  enable_media: false,
  save_option: 'excel',
  cookies: '',
  headless: false,
  semantic_filter: false,
  semantic_rule: 'topic',
  semantic_model: 'jev-1.13.0',
  keyword_pairs: [],
}

export const useCrawlerStore = create<CrawlerState>((set, get) => ({
  status: 'idle',
  stage: 'idle',
  platform: null,
  crawlerType: null,
  startedAt: null,
  logs: [],
  totalLogCount: 0,
  logSessionId: (() => { try { return localStorage.getItem('mediacrawler_log_session_id') } catch { return null } })(),
  clearedAfterLogId: getClearedLogIdFromStorage(), // 从 localStorage 初始化
  ...loadConfig(defaultConfig),

  setStatus: (status) => set({ status, stage: status === 'running' ? (get().status === 'running' ? get().stage : 'starting') : 'idle' }),
  setRunningInfo: (platform, crawlerType, startedAt) => set({ platform, crawlerType, startedAt }),

  receiveLogs: (incoming, sessionId) => {
    const state = get()
    const session = sessionId || incoming[0]?.session_id || state.logSessionId
    const changedSession = !!session && session !== state.logSessionId
    const cutoff = changedSession ? null : state.clearedAfterLogId
    const logs = mergeLogBatch(changedSession ? [] : state.logs, incoming, cutoff)
    // IDs increase for the entire run, even after old rows leave the buffer.
    const totalLogCount = Math.max(changedSession ? 0 : state.totalLogCount, ...incoming.map(log => log.id))
    if (changedSession) {
      saveClearedLogIdToStorage(null)
      try { localStorage.setItem('mediacrawler_log_session_id', session!) } catch { /* storage is optional */ }
    }
    if (changedSession || logs !== state.logs || totalLogCount !== state.totalLogCount) set({ logs, totalLogCount, logSessionId: session, clearedAfterLogId: cutoff })
  },

  addLog: (log) => get().receiveLogs([log]),
  setLogs: (logs) => get().receiveLogs(logs),

  clearLogs: () => {
    const { logs } = get()
    // 记录当前最大的 log id，清除后只显示比这个 id 大的日志
    const maxLogId = Math.max(get().clearedAfterLogId ?? 0, ...logs.map(l => l.id))
    set({ logs: [], clearedAfterLogId: maxLogId })
    // 持久化到 localStorage
    saveClearedLogIdToStorage(maxLogId)
  },

  restoreLogs: () => {
    // 清除清除标记，这样下次重新加载日志时就会显示所有日志
    set({ clearedAfterLogId: null })
    saveClearedLogIdToStorage(null)
  },

  updateKeywordText: (keywordText) => set((state) => {
    const collectionTopics = keywordText.split(/\r\n?|\n/).map(topicFromText)
    return { keywordText, collectionTopics, config: { ...state.config, ...topicSearchConfig(collectionTopics, state.config.semantic_filter && state.config.semantic_rule === 'scene') } }
  }),
  updateCollectionTopics: (collectionTopics) => set((state) => {
    const scene = state.config.semantic_filter && state.config.semantic_rule === 'scene'
    return { collectionTopics, keywordText: collectionTopics.map(card => card.text).join('\n'), config: { ...state.config, ...topicSearchConfig(collectionTopics, scene) } }
  }),

  updateConfig: (config) =>
    set((state) => ({
      config: { ...state.config, ...config, ...topicSearchConfig(state.collectionTopics, (config.semantic_filter ?? state.config.semantic_filter) && (config.semantic_rule ?? state.config.semantic_rule) === 'scene') },
    })),

  reset: () =>
    set({
      status: 'idle',
      stage: 'idle',
      platform: null,
      crawlerType: null,
      startedAt: null,
    }),
}))

useCrawlerStore.subscribe((state, previous) => {
  if (state.config !== previous.config || state.keywordText !== previous.keywordText || state.collectionTopics !== previous.collectionTopics) {
    saveConfig(state.config, state.keywordText, state.collectionTopics)
  }
})
