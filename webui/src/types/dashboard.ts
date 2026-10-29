export type DashboardPeriod = 'task' | 'today' | 'week' | 'month' | 'year' | 'custom'
export type ImageState = 'qualified' | 'unqualified' | 'pending' | 'failed'
export interface DashboardGroup {
  keyword: string; collected: number; qualified: number; target: number | null
  status: 'running' | 'completed' | 'interrupted' | 'pending'; reason: string | null
}
export interface TrendPoint { at: string; collected: number; qualified: number; images: number }
export interface DashboardImage {
  name: string; keyword: string; note_id: string; file: string; download: string
  status: ImageState; url: string | null; reason: string
}
export interface DashboardSnapshot {
  updated_at: string
  task: { id: string | null; platform: string; file: string | null; files: string[]; status: string
    started_at: string | null; current_keyword: string; completed_groups: number; total_groups: number }
  metrics: { collected_posts: number; checked_posts: number; qualified_posts: number; pending_review: number
    images: { downloaded: number; download_pending: number; download_failed: number; qualified: number
      unqualified: number; pending: number; failed: number; recognized: number; pass_rate: number | null } }
  groups: DashboardGroup[]
  ranking: { keyword: string; collected: number; qualified: number }[]
  trend: TrendPoint[]; group_trends: Record<string, TrendPoint[]>
  range: { start: string; end: string; period: DashboardPeriod }
  images: DashboardImage[]; missing_files: string[]; unknown_time_posts: number
}

export interface CollectionProgress {
  session_id: string; status: string; stage: string; started_at: string | null; task_id: string | null
  current_keyword: string; checked: number; saved: number; qualified: number; target: number | null
  percent: number | null; comments: number; images: number; completed_topics: number; total_topics: number
  updated_at: string; run_status?: string
}

export type OverviewPeriod = 'today' | 'week' | 'month' | 'year' | 'all' | 'custom'
export interface OverviewMetrics {
  recorded: number; checked: number; retained: number; review: number; excluded: number
  unfiltered: number; processing: number; duplicate: number; comments: number
  images: number; downloaded: number; download_failed: number; online_images: number; missing_images: number
  auto_passed: number; manual_retained: number; manual_excluded: number
}
export interface OverviewTask {
  id: string; title: string; platform: string; file: string | null; status: string
  started_at: string | null; last_at: string | null; rounds: number; target: number | null
  duration_seconds: number | null; estimated_time: boolean; metrics: OverviewMetrics
  summaries: { ready: number; failed: number; running: number }
}
export interface OverviewPoint { at: string; recorded: number; retained: number; review: number; rounds: number }
export interface DashboardOverview {
  updated_at: string; range: { period: OverviewPeriod; start: string; end: string; interval: 'hour' | 'day' | 'month' }
  metrics: OverviewMetrics & { tasks: number; rounds: number; unique_posts: number; summary_ready: number }
  timeline: OverviewPoint[]; tasks: OverviewTask[]
  task_options: { id: string; title: string; platform: string; started_at: string | null }[]
  warnings: Record<string, number>; active: boolean
  scope: { task_id: string | null; platform: string | null; time_basis: string; review_basis: string }
}
