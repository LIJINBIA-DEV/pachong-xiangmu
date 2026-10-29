export interface BrowseComment {
  id: string
  content: string
  nickname: string
  kind?: 'semantic' | 'keyword'
}

export interface BrowsePost {
  key: string
  id: string
  index: number
  title: string
  content: string
  url: string
  source_keyword: string
  status: string
  semantic_status?: string
  review_decision_source?: 'manual' | 'automatic' | null
  review_decision_reason?: string | null
  nickname: string
  published_at: string
  account_id?: string
  profile_url?: string
  gender?: string
  verification?: string
  publish_location?: string
  post_ip_region?: string
  display_location?: string
  location_source?: string
  evidence: string
  evidence_source: string
  selection_origin?: string
  manual_review_required?: boolean
  model_original_choice?: string
  jev_original_choice?: string
  hit_comments: BrowseComment[]
  comments: BrowseComment[]
  images: { url: string; name: string; local: boolean }[]
  image_count: number | null
  downloaded_image_count: number
  image_download_status: 'downloaded' | 'not_downloaded' | 'partial' | 'no_images' | 'unknown'
}

export interface BrowseResponse {
  posts: BrowsePost[]
  total: number
  file_total: number
  offset: number
  limit: number
  counts: Record<string, number>
}

export interface ImageSubjectPrediction {
  status: 'recognized' | 'unrecognized' | 'not_downloaded' | 'download_failed' | 'error'
  label?: '人物' | '食物' | '二者都不是'
  reason?: string
  image_type?: '实景照片' | '宣传海报' | '广告设计图' | '聊天截图' | '网页截图' | '文字／图文设计卡片' | '不确定' | null
  type_reason?: string
  type_status?: 'pending' | null
  policy_status?: 'pending' | null
  suggestion?: 'qualified' | 'unqualified' | null
  elapsed_seconds?: number
  model?: string
  provider?: 'local' | 'siliconflow'
}
export interface ImageSubjectSettings {
  provider: 'local' | 'siliconflow'
  model: string
  key_configured: boolean
  key_from_environment: boolean
  local_ready: boolean
  ready: boolean
}
export interface ImageSubjectStatus {
  status: string
  total: number
  completed: number
  failed: number
  not_downloaded: number
  busy: boolean
  ready: boolean
  error?: string | null
  provider?: 'local' | 'siliconflow'
  model?: string
}
export interface ReviewImage { key: string; url: string; remote_url?: string; name: string; local: boolean; subject?: ImageSubjectPrediction; download_problem?: 'not_downloaded' | 'download_failed' | null; decision_source?: 'model' | 'manual' | 'download' | null }
export type ReviewDecision = 'qualified' | 'unqualified' | null
export type AccountDecision = 'marketing' | 'non_marketing' | null
export interface ReviewEntry {
  decision: ReviewDecision
  screening_passed?: boolean
  requires_images?: boolean
  decision_reason?: 'semantic_passed' | 'text_review_pending' | 'marketing' | 'no_images' | 'all_images_rejected' | 'account_pending' | 'images_pending' | 'retained' | 'manual_qualified' | 'manual_unqualified' | 'pet_not_allowed' | 'semantic_reject' | 'evidence_contradicted' | 'news_media_account' | 'government_account' | 'institution_account' | 'account_blocklist_bot' | 'account_blocklist_media' | 'account_blocklist_government'
  semantic_rejection_reason?: 'pet_not_allowed' | 'semantic_reject' | 'evidence_contradicted' | null
  account_rejection_reason?: ReviewEntry['decision_reason'] | null
  account_identity_status?: 'excluded' | 'review' | 'personal' | null
  account_identity_evidence?: string | null
  post_decision?: ReviewDecision
  post_decision_source?: 'manual' | null
  decision_source?: 'manual' | 'automatic'
  automatic_decision?: ReviewDecision
  automatic_decision_reason?: ReviewEntry['decision_reason']
  images: Record<string, ReviewDecision>
  account: AccountDecision
  account_source?: 'blocklist' | 'default' | 'manual' | 'identity' | 'identity_review' | null
  account_reason?: string | null
  account_key: string
  account_scope: 'batch_account' | 'post_only'
  updated_at: string | null
  review_images: ReviewImage[]
}
export interface ManualReviewResponse { entries: Record<string, ReviewEntry>; total: number; completed: number; partial?: boolean }

export interface SupplementPlan {
  task_id: string | null
  anchor: string
  groups: { keyword: string; retained: number; excluded: number; pending: number; target: number | null; shortfall: number | null }[]
  review_complete: boolean
  running: boolean
  supported: boolean
  needs_setup: boolean
  needs_api_key: boolean
  needs_cookies?: boolean
    needs_qr_login?: boolean
  shortfall: number | null
  rounds: number
  files: string[]
  last_status: string | null
  last_results: Record<string, { retained: number; target: number; reason: string }>
}

export interface CollectionLogEntry {
  id: string; round: number; keyword: string; target: number; retained: number; missing: number
  reason: string; evidence: string; page: number | null; recorded_at: string | null; run_status: string
  diagnostics: { pages_checked?: number; checked_page?: number; http_status?: number; api_ok?: number; cards_count?: number; parsed_count?: number; blocked_accounts?: number; evaluated?: number; not_retained?: number; message_code?: string }
}
export interface CollectionLogsResponse {
  task_id: string | null
  overview?: { platform: string; status: string; target: number; topics: number; saved: number; checked: number; qualified: number; comments: number; images: number; pending_review: number; files: string[]; missing_files: string[]; filter: string | null; comments_enabled?: boolean; media_enabled?: boolean; publish_range?: string; publish_start?: string; publish_end?: string }
  timeline?: { kind: string; at: string; round?: number; target?: number; retained?: number; status?: string; keyword?: string; post_id?: string; decision?: string | null; model?: string; records?: number; error?: string | null; reason?: string }[]
  rounds: { number: number; status: string; started_at: string | null; finished_at: string | null; elapsed_seconds?: number | null; target?: number; retained?: number; pages?: number }[]
  entries: CollectionLogEntry[]
  account_events?: { stage: string; source_file: string; note_id: string; keyword: string; nickname: string; status: 'excluded' | 'review'; reason: string; evidence: string; recorded_at: string }[]
  comment_events?: { id: string; stage: string; note_id: string; status: string; reason: string; explanation: string; response_message: string; exception_type: string; http_status?: number; api_ok?: number; request_count?: number; recorded_at: string }[]
}
