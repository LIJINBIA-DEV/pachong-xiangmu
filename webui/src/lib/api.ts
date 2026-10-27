import type { AISettings, AISettingsInput, ContentSummaryInfo, ContentSummaryInput, ContentSummaryJob } from '@/types/contentSummary'
import axios from 'axios'
import type { BrowseResponse, ManualReviewResponse, ReviewDecision, AccountDecision, SupplementPlan, CollectionLogsResponse } from '@/types/dataBrowser'
import type { CrawlerConfig as StartConfig } from '@/types/crawler'
import type { CollectionProgress, DashboardSnapshot, DashboardPeriod } from '@/types/dashboard'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Types
export interface CrawlerConfig {
  platform: string
  login_type: string
  crawler_type: string
  keywords: string
  start_page: number
  publish_time_range?: 'all' | 'week' | 'day' | 'month' | 'custom'
  publish_start_date?: string
  publish_end_date?: string
  max_notes_count: number | null
  enable_comments: boolean
  enable_sub_comments: boolean
  enable_media: boolean
  save_option: string
  cookies: string
  headless: boolean
}

export interface CrawlerStatus {
  stage?: 'idle' | 'waiting_login' | 'starting' | 'running'
  status: 'idle' | 'running' | 'stopping' | 'error'
  platform: string | null
  crawler_type: string | null
  started_at: string | null
  error_message: string | null
}

export interface LogEntry {
  session_id?: string | null
  id: number
  timestamp: string
  level: 'info' | 'warning' | 'error' | 'success' | 'debug'
  message: string
}

export interface DataFile {
  name: string
  path: string
  size: number
  modified_at: number
  record_count: number | null
  type: string
  file_kind?: 'collection' | 'semantic' | null
  retained_count?: number | null
  review_count?: number | null
  review_main?: string | null
}

export interface ReviewExportJob {
  id: string
  status: 'queued' | 'preparing' | 'ready' | 'failed' | 'cancelled'
  processed: number
  total: number
  error: string | null
  counts: { retained?: number; images?: number; pending?: number; missing?: number; no_images?: number }
  download_url: string | null
  filename: string
}

export interface CollectionTask {
  id: string
  title: string
  platform: string
  primary_file: string
  files: DataFile[]
  modified_at: number
  started_at: string | null
  status: string
  counts: Record<string, number> | null
  rounds: number
}

export interface FilePreviewResponse {
  data: Record<string, unknown>[]
  total: number
  columns?: string[]
  sheets?: string[]
  sheet?: string
}

export interface Platform {
  value: string
  label: string
  icon: string
}

export interface ConfigOption {
  value: string
  label: string
}

export interface TrashFile {
  id: string
  path: string
  name: string
  size: number
  deleted_at: number
}

export interface SemanticKeyCheckResult {
  ok: boolean
  reason: 'usable' | 'missing_key' | 'authentication_rejected' | 'billing_or_rate_limit' | 'provider_error' | 'request_rejected' | 'timeout' | 'network_error' | 'invalid_response' | 'backend_unreachable'
  http_status?: number
  model?: string
}

export interface JevProxyStatus {
  available: boolean
  enabled: boolean
  subscription_configured: boolean
  nodes: string[]
  selected_node: string | null
  status: string
  message: string
}

export interface JevProxySettings {
  enabled: boolean
  subscription_url?: string
  clear_subscription?: boolean
}

export const jevProxyApi = {
  get: () => api.get<JevProxyStatus>('/jev-proxy'),
  save: (settings: JevProxySettings) => api.put<JevProxyStatus>('/jev-proxy', settings, { timeout: 90000 }),
  refresh: () => api.post<JevProxyStatus>('/jev-proxy/refresh', undefined, { timeout: 90000 }),
  selectNode: (name: string) => api.put<JevProxyStatus>('/jev-proxy/node', { name }),
  test: (apiKey?: string) => api.post<SemanticKeyCheckResult>('/jev-proxy/test', { api_key: apiKey || undefined }, { timeout: 90000 }),
}

export interface WeiboLoginStatus {
  status: 'idle' | 'loading' | 'waiting' | 'checking' | 'authenticated' | 'verification_required' | 'expired' | 'error' | 'cancelled'
  qr_image: string | null
  expires_at: number | null
  reason: string | null
  busy: boolean
  supported: boolean
  saved_session: boolean
  local_browser?: boolean
  desktop_available?: boolean
  desktop_port?: number
}

// API functions
export const crawlerApi = {
  getSemanticSettings: () => api.get<{ key_configured: boolean }>('/crawler/semantic-settings'),
  saveSemanticSettings: (input: { api_key?: string; clear_key?: boolean }) => api.put<{ key_configured: boolean }>('/crawler/semantic-settings', input),
  getQRLogin: (platform: 'wb' | 'xhs') => api.get<WeiboLoginStatus>(`/crawler/${platform === 'wb' ? 'weibo' : 'xhs'}-login`),
  startQRLogin: (platform: 'wb' | 'xhs', refresh = false, loginEnvironment: StartConfig['login_environment'] = 'auto') => api.post<WeiboLoginStatus>(`/crawler/${platform === 'wb' ? 'weibo' : 'xhs'}-login`, { refresh, login_environment: loginEnvironment }),
  cancelQRLogin: (platform: 'wb' | 'xhs') => api.delete<WeiboLoginStatus>(`/crawler/${platform === 'wb' ? 'weibo' : 'xhs'}-login`),
  getWeiboLogin: () => api.get<WeiboLoginStatus>('/crawler/weibo-login'),
  startWeiboLogin: (refresh = false) => api.post<WeiboLoginStatus>('/crawler/weibo-login', { refresh }),
  cancelWeiboLogin: () => api.delete<WeiboLoginStatus>('/crawler/weibo-login'),
  start: (config: CrawlerConfig) => api.post('/crawler/start', config),
  checkSemanticKey: (apiKey: string, model: string) =>
    api.post<SemanticKeyCheckResult>('/crawler/semantic-key-check', { api_key: apiKey || null, model }),
  stop: () => api.post('/crawler/stop'),
  getStatus: () => api.get<CrawlerStatus>('/crawler/status'),
  getLogs: (limit = 100) => api.get<{ logs: LogEntry[] }>('/crawler/logs', { params: { limit } }),
}

export const dataApi = {
  getAISettings: () => api.get<AISettings>('/data/ai-settings'),
  saveAISettings: (input: AISettingsInput) => api.put<AISettings>('/data/ai-settings', input),
  getContentSummary: (file: string) => api.get<ContentSummaryInfo>('/data/content-summary', { params: { file } }),
  generateContentSummary: (input: ContentSummaryInput) => api.post<ContentSummaryJob>('/data/content-summary', input),
  getContentSummaryDownloadUrl: (file: string, identity: string) => `/api/data/content-summary/${identity}/download?${new URLSearchParams({ file })}`,
  getTasks: () => api.get<{ tasks: CollectionTask[] }>('/data/tasks'),
  getPostExportUrl: (file: string, status: string) => `/api/data/export?${new URLSearchParams({ file, status })}`,
  getCollectionProgress: () => api.get<CollectionProgress>('/dashboard/progress'),
  getDashboard: (period: DashboardPeriod = 'task', start?: string, end?: string) => api.get<DashboardSnapshot>('/dashboard', { params: { period, start, end } }),
  getCollectionLogs: (file: string) => api.get<CollectionLogsResponse>('/data/collection-logs', { params: { file } }),
  getSupplement: (file: string) => api.get<SupplementPlan>('/data/supplement', { params: { file } }),
  supplement: (file: string, target?: number, config?: StartConfig, api_key?: string, cookies?: string) => api.post<SupplementPlan>('/data/supplement', { file, target, config, api_key, cookies }),
  getTrash: () => api.get<{ files: TrashFile[] }>('/data/trash'),
  deleteFile: (file: string) => api.post<TrashFile>('/data/trash', { file }),
  restoreFile: (id: string) => api.post<TrashFile>(`/data/trash/${id}/restore`),
  purgeFile: (id: string) => api.delete<TrashFile>(`/data/trash/${id}`),
  getReview: (file: string) => api.get<ManualReviewResponse>('/data/review', { params: { file } }),
  exportReview: (file: string) => api.post<ReviewExportJob>('/data/review/export/jobs', { file }),
  getReviewExport: (id: string) => api.get<ReviewExportJob>(`/data/review/export/jobs/${id}`),
  listReviewExports: () => api.get<{ jobs: ReviewExportJob[] }>('/data/review/export/jobs'),
  cancelReviewExport: (id: string) => api.delete<ReviewExportJob>(`/data/review/export/jobs/${id}`),
  saveReview: (file: string, postKey: string, kind: 'image' | 'account' | 'post', decision: ReviewDecision | AccountDecision, imageKey?: string) =>
    api.patch<ManualReviewResponse>('/data/review', { file, post_key: postKey, kind, decision, image_key: imageKey, partial: true }),
  browse: (file: string, offset = 0, search = '', status = 'all', limit = 20, signal?: AbortSignal) =>
    api.get<BrowseResponse>('/data/browse', { params: { file, offset, limit, search, status }, signal }),
  getFiles: (platform?: string, fileType?: string) =>
    api.get<{ files: DataFile[] }>('/data/files', { params: { platform, file_type: fileType } }),
  getFileContent: (path: string, limit = 100, sheet?: string) =>
    api.get<FilePreviewResponse>('/data/files/' + path, { params: { preview: true, limit, sheet } }),
  getStats: () => api.get('/data/stats'),
  getDownloadUrl: (path: string) => `/api/data/download/${path}`,
}

export const configApi = {
  getPlatforms: () => api.get<{ platforms: Platform[] }>('/config/platforms'),
  getOptions: () =>
    api.get<{
      login_types: ConfigOption[]
      web_qrcode_login: boolean
      default_login_environment?: 'local' | 'server'
      local_login_available?: boolean
      login_environment_selection?: boolean
      crawler_types: ConfigOption[]
      save_options: ConfigOption[]
      semantic_models: ConfigOption[]
    }>('/config/options'),
}

export interface EnvCheckResult {
  success: boolean
  message: string
  output?: string
  error?: string
}

export const envApi = {
  check: () => api.get<EnvCheckResult>('/env/check'),
}

export default api
