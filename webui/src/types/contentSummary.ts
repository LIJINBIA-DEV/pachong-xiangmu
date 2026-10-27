export type SummaryMode = 'auto' | 'evaluation' | 'topic'
export type SummaryScope = 'retained' | 'available'
export type SummaryStance = 'positive' | 'negative' | 'neutral' | 'mixed' | 'unclear'
export interface SummaryPost {
  ref: string
  post_id: string
  query: string
  title: string
  url: string
  status: string
  summary: string
  stance: SummaryStance
  topics: string[]
  evidence: { source: string; quote: string }[]
}
export interface ContentSummaryJob {
  id: string
  status: 'queued' | 'running' | 'ready' | 'failed' | 'interrupted'
  created_at: string
  finished_at: string | null
  mode: Exclude<SummaryMode, 'auto'>
  options: { mode: SummaryMode; scope: SummaryScope; include_comments: boolean; max_posts: number; model: string }
  stats: { records: number; unique_posts: number; eligible: number; review: number; unfiltered: number; omitted: number; skipped_empty: number; truncated: number; comments: number; comments_omitted: number }
  processed: number
  total: number
  calls: number
  estimated_calls: number
  error: string | null
  result: { overview: string; themes: { title: string; summary: string; refs: string[] }[]; posts: SummaryPost[]; stance_counts: Partial<Record<SummaryStance, number>> } | null
}
export interface ContentSummaryInfo {
  settings_ready: boolean
  settings: AISettings
  default_model: string
  key_configured: boolean
  inferred_mode: 'evaluation' | 'topic'
  counts: Record<string, number>
  busy: boolean
  job: ContentSummaryJob | null
  report: ContentSummaryJob | null
  stale: boolean
}
export interface ContentSummaryInput { file: string }
export interface AISettings {
  base_url: string
  model: string
  scope: SummaryScope
  include_comments: boolean
  max_posts: number
  key_configured: boolean
  key_from_environment: boolean
  ready: boolean
}
export interface AISettingsInput extends Pick<AISettings, 'base_url' | 'model' | 'scope' | 'include_comments' | 'max_posts'> {
  api_key?: string
  clear_key?: boolean
}
