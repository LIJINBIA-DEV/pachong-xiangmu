export interface CrawlerConfig {
  platform: string
  login_type: string
  login_environment?: 'auto' | 'local' | 'server'
  crawler_type: string
  keywords: string
  specified_ids: string  // 详情模式下的帖子/视频ID
  creator_ids: string    // 创作者模式下的创作者ID
  start_page: number
  max_notes_count: number | null
  max_comments_count?: number | null
  enable_comments: boolean
  enable_sub_comments: boolean
  enable_media: boolean  // 是否下载媒体（封面/视频/图文图片），支持 xhs/dy/ks/bili/wb
  image_subject_recognition: boolean
  save_option: string
  cookies: string
  headless: boolean
  semantic_filter: boolean
  semantic_model: string
  semantic_api_key?: string
  keyword_pairs: [string, string][]
}

export interface CrawlerStatus {
  status: 'idle' | 'running' | 'stopping' | 'error'
  platform: string | null
  crawler_type: string | null
  started_at: string | null
  error_message: string | null
}

export interface LogEntry {
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
