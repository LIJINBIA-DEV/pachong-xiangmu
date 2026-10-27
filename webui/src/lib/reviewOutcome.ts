import type { AccountDecision, ManualReviewResponse, ReviewDecision, ReviewEntry } from '@/types/dataBrowser'

export type ReviewChange = { key: string; kind: 'image' | 'account' | 'post'; decision: ReviewDecision | AccountDecision; imageKey?: string }

export function automaticReviewOutcome(entry: ReviewEntry): Pick<ReviewEntry, 'decision' | 'decision_reason'> {
  if (entry.semantic_rejection_reason) return { decision: 'unqualified', decision_reason: entry.semantic_rejection_reason }
  if (entry.account_rejection_reason) return { decision: 'unqualified', decision_reason: entry.account_rejection_reason }
  if (entry.account === 'marketing') return { decision: 'unqualified', decision_reason: 'marketing' }
  return { decision: null, decision_reason: 'text_review_pending' }
}

export function reviewOutcome(entry: ReviewEntry): Pick<ReviewEntry, 'decision' | 'decision_reason'> {
  if (entry.semantic_rejection_reason || entry.account_rejection_reason) return automaticReviewOutcome(entry)
  // Preserve explicit human corrections, without reviving obsolete post labels.
  if (entry.post_decision_source === 'manual' && (entry.post_decision === 'qualified' || entry.post_decision === 'unqualified')) {
    return { decision: entry.post_decision, decision_reason: entry.post_decision === 'qualified' ? 'manual_qualified' : 'manual_unqualified' }
  }
  return automaticReviewOutcome(entry)
}

export function withReviewOutcomes(review: ManualReviewResponse): ManualReviewResponse {
  const entries = Object.fromEntries(Object.entries(review.entries).map(([key, entry]) => {
    const automatic = automaticReviewOutcome(entry)
    const outcome = reviewOutcome(entry)
    return [key, { ...entry, ...outcome, automatic_decision: automatic.decision, automatic_decision_reason: automatic.decision_reason,
      decision_source: outcome.decision_reason?.startsWith('manual_') ? 'manual' as const : 'automatic' as const }]
  }))
  return { ...review, entries, completed: Object.values(entries).filter((entry) => entry.decision !== null).length }
}

export function applyReviewChange(review: ManualReviewResponse, change: ReviewChange): ManualReviewResponse {
  const target = review.entries[change.key]
  if (!target) return review
  const entries = Object.fromEntries(Object.entries(review.entries).map(([key, entry]) => {
    if (change.kind === 'account') {
      if (key !== change.key && (!target.account_key || entry.account_key !== target.account_key)) return [key, entry]
      // Exclusion-list defaults remain authoritative on the server as well.
      if (entry.account_source === 'blocklist' || entry.account_rejection_reason) return [key, entry]
      return [key, { ...entry, account: change.decision as AccountDecision, account_source: 'manual' as const, account_reason: null }]
    }
    if (key !== change.key) return [key, entry]
    const decision = change.decision as ReviewDecision
    if (change.kind === 'post') return [key, { ...entry, post_decision: decision, post_decision_source: decision ? 'manual' as const : null }]
    if (!change.imageKey || !entry.review_images.some((image) => image.key === change.imageKey)) return [key, entry]
    return [key, { ...entry, images: { ...entry.images, [change.imageKey]: decision },
      review_images: entry.review_images.map((image) => image.key === change.imageKey ? { ...image, decision_source: 'manual' as const } : image) }]
  }))
  return withReviewOutcomes({ ...review, entries })
}

export function mergeReviewResponse(current: ManualReviewResponse | undefined, response: ManualReviewResponse): ManualReviewResponse | undefined {
  if (!response.partial) return withReviewOutcomes(response)
  if (!current) return undefined
  return withReviewOutcomes({ ...current, partial: false, entries: { ...current.entries, ...response.entries } })
}
