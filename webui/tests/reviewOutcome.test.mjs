import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/lib/reviewOutcome.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } })
const { reviewOutcome, withReviewOutcomes, applyReviewChange, mergeReviewResponse } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const entry = (account, values) => ({ account, review_images: values.map((_, i) => ({ key: String(i) })), images: Object.fromEntries(values.map((v, i) => [String(i), v])), decision: 'qualified' })

test('model passes need no duplicate approval, uncertain posts stay pending, human corrections win', () => {
  const review = withReviewOutcomes({ total: 2, completed: 0, entries: {
    passed: { ...entry(null, []), screening_passed: true },
    uncertain: { ...entry(null, []), screening_passed: false },
  } })
  assert.equal(review.completed, 1)
  assert.equal(review.entries.passed.decision, 'qualified')
  assert.equal(review.entries.passed.decision_source, 'automatic')
  assert.equal(review.entries.uncertain.decision, null)
  const corrected = applyReviewChange(review, { key: 'passed', kind: 'post', decision: 'unqualified' })
  assert.equal(corrected.entries.passed.decision_reason, 'manual_unqualified')
  const reset = applyReviewChange(corrected, { key: 'passed', kind: 'post', decision: null })
  assert.equal(reset.entries.passed.decision_reason, 'semantic_passed')
  assert.equal(review.entries.passed.post_decision, undefined)
})

test('institution exclusions win optimistic account and whole-post approvals', () => {
  for (const reason of ['news_media_account', 'government_account', 'institution_account']) {
    let review = withReviewOutcomes({ entries: { first: { ...entry('marketing', ['qualified']), account_rejection_reason: reason, account_source: 'identity' } }, total: 1, completed: 1 })
    review = applyReviewChange(review, { key: 'first', kind: 'account', decision: 'non_marketing' })
    review = applyReviewChange(review, { key: 'first', kind: 'post', decision: 'qualified' })
    assert.equal(review.entries.first.account, 'marketing')
    assert.equal(review.entries.first.decision, 'unqualified')
    assert.equal(review.entries.first.decision_reason, reason)
  }
})

test('read-only account information does not block a whole-post decision', () => {
  const review = withReviewOutcomes({ entries: { first: { ...entry(null, ['qualified']), account_identity_status: 'review', post_decision: 'qualified', post_decision_source: 'manual' } }, total: 1, completed: 0 })
  assert.equal(review.entries.first.decision, 'qualified')
  assert.equal(review.completed, 1)
})
test('definite Jev negatives cannot be revived by positive images or optimistic post corrections', () => {
  for (const reason of ['semantic_reject', 'evidence_contradicted']) {
    const original = { ...entry('non_marketing', ['qualified']), semantic_rejection_reason: reason, post_decision: 'qualified', post_decision_source: 'manual' }
    const snapshot = withReviewOutcomes({ entries: { first: original }, total: 1, completed: 1 })
    const after = applyReviewChange(snapshot, { key: 'first', kind: 'post', decision: 'qualified' })
    assert.equal(after.entries.first.decision, 'unqualified')
    assert.equal(after.entries.first.decision_reason, reason)
    assert.equal(after.entries.first.decision_source, 'automatic')
    assert.equal(after.entries.first.images['0'], 'qualified')
  }
})
const cases = [
  ['marketing', ['qualified'], 'unqualified', 'marketing'],
  ['non_marketing', ['qualified', 'unqualified'], 'qualified', 'retained'],
  ['non_marketing', ['qualified', null], 'qualified', 'retained'],
  ['non_marketing', ['unqualified', 'unqualified'], 'unqualified', 'all_images_rejected'],
  ['non_marketing', ['unqualified', null], null, 'images_pending'],
  [null, ['qualified'], 'qualified', 'retained'],
  [null, ['unqualified'], 'unqualified', 'all_images_rejected'],
  ['non_marketing', [], 'unqualified', 'no_images'],
]
for (const [account, images, decision, decision_reason] of cases) {
  test(`${account}: ${images} => ${decision_reason}`, () => {
    assert.deepEqual(reviewOutcome(entry(account, images)), account === 'marketing' ? { decision: 'unqualified', decision_reason: 'marketing' } : { decision: null, decision_reason: 'text_review_pending' })
  })
}
test('legacy manual conclusions cannot alter filters or progress', () => {
  const first = { ...entry(null, ['qualified']), decision: 'qualified' }
  const second = { ...entry('non_marketing', ['qualified']), decision: 'unqualified' }
  const review = withReviewOutcomes({ entries: { first, second }, total: 2, completed: 2 })
  assert.equal(review.completed, 0)
  assert.equal(review.entries.first.decision, null)
  assert.equal(review.entries.second.decision, null)
  assert.equal(second.decision, 'unqualified')
})

test('explicit post corrections take priority while preserving automatic suggestions', () => {
  const approved = { ...entry('marketing', ['unqualified']), post_decision: 'qualified', post_decision_source: 'manual' }
  const rejected = { ...entry('non_marketing', ['qualified']), post_decision: 'unqualified', post_decision_source: 'manual' }
  const pending = { ...entry(null, [null]), post_decision: 'qualified', post_decision_source: 'manual' }
  const review = withReviewOutcomes({ entries: { approved, rejected, pending }, total: 3, completed: 0 })
  assert.equal(review.completed, 3)
  assert.equal(review.entries.approved.decision, 'qualified')
  assert.equal(review.entries.approved.automatic_decision, 'unqualified')
  assert.equal(review.entries.rejected.decision, 'unqualified')
  assert.equal(review.entries.rejected.automatic_decision, null)
  assert.equal(review.entries.pending.automatic_decision, null)
  assert.equal(review.entries.pending.decision_reason, 'manual_qualified')
  assert.equal(review.entries.approved.decision_source, 'manual')
  assert.deepEqual(review.entries.approved.images, approved.images)
  assert.equal(approved.decision, 'qualified')
})

test('resetting a correction restores automatic selection and pending progress', () => {
  const reset = { ...entry(null, [null]), post_decision: null, post_decision_source: null, decision_source: 'manual' }
  const review = withReviewOutcomes({ entries: { reset }, total: 1, completed: 1 })
  assert.equal(review.entries.reset.decision, null)
  assert.equal(review.entries.reset.decision_source, 'automatic')
  assert.equal(review.completed, 0)
  assert.equal(reviewOutcome({ ...entry('non_marketing', ['qualified']), post_decision: 'unqualified' }).decision, null)
})

test('legacy image edits cannot decide the post or mutate the rollback snapshot', () => {
  const before = withReviewOutcomes({ entries: { first: entry('non_marketing', ['qualified', 'unqualified']) }, total: 1, completed: 1 })
  const after = applyReviewChange(before, { key: 'first', kind: 'image', imageKey: '0', decision: 'unqualified' })
  assert.equal(after.entries.first.images['0'], 'unqualified')
  assert.equal(after.entries.first.decision, null)
  assert.equal(after.entries.first.automatic_decision_reason, 'text_review_pending')
  assert.equal(after.entries.first.review_images[0].decision_source, 'manual')
  assert.equal(before.entries.first.images['0'], 'qualified')
  assert.equal(before.entries.first.decision, null)
  assert.equal(before.entries.first.review_images[0].decision_source, undefined)
})

test('image edits preserve manual post decisions and account edits update shared accounts only', () => {
  const first = { ...entry('non_marketing', ['qualified']), account_key: 'shared', post_decision: 'qualified', post_decision_source: 'manual' }
  const second = { ...entry('non_marketing', ['qualified']), account_key: 'shared' }
  const third = { ...entry('non_marketing', ['qualified']), account_key: 'other' }
  const before = withReviewOutcomes({ entries: { first, second, third }, total: 3, completed: 3 })
  const imageChanged = applyReviewChange(before, { key: 'first', kind: 'image', imageKey: '0', decision: 'unqualified' })
  assert.equal(imageChanged.entries.first.decision, 'qualified')
  assert.equal(imageChanged.entries.first.automatic_decision, null)
  const accountChanged = applyReviewChange(before, { key: 'second', kind: 'account', decision: 'marketing' })
  assert.equal(accountChanged.entries.first.account, 'marketing')
  assert.equal(accountChanged.entries.first.decision, 'qualified')
  assert.equal(accountChanged.entries.second.decision, 'unqualified')
  assert.equal(accountChanged.entries.third.account, 'non_marketing')
  assert.equal(before.entries.second.account, 'non_marketing')
})

test('optimistic post reset and image reset update final outcome and progress', () => {
  const first = { ...entry('non_marketing', [null]), post_decision: 'qualified', post_decision_source: 'manual' }
  const before = withReviewOutcomes({ entries: { first }, total: 1, completed: 1 })
  const reset = applyReviewChange(before, { key: 'first', kind: 'post', decision: null })
  assert.equal(reset.entries.first.decision, null)
  assert.equal(reset.completed, 0)
  const approved = applyReviewChange(reset, { key: 'first', kind: 'image', imageKey: '0', decision: 'qualified' })
  assert.equal(approved.completed, 0)
  const cleared = applyReviewChange(approved, { key: 'first', kind: 'image', imageKey: '0', decision: null })
  assert.equal(cleared.entries.first.decision, null)
  assert.equal(cleared.completed, 0)
})

test('partial save responses preserve all other posts and recompute global progress', () => {
  const before = withReviewOutcomes({ entries: { first: entry('non_marketing', [null]), second: { ...entry('non_marketing', ['qualified']), post_decision: 'qualified', post_decision_source: 'manual' } }, total: 2, completed: 1 })
  const response = { entries: { first: { ...entry('non_marketing', ['qualified']), post_decision: 'qualified', post_decision_source: 'manual' } }, total: 1, completed: 1, partial: true }
  const merged = mergeReviewResponse(before, response)
  assert.equal(merged.total, 2)
  assert.equal(merged.completed, 2)
  assert.deepEqual(Object.keys(merged.entries), ['first', 'second'])
  assert.equal(before.entries.first.decision, null)
  assert.equal(mergeReviewResponse(undefined, response), undefined)
  assert.equal(mergeReviewResponse(before, { ...response, partial: false }).total, 1)
})

test('account preview does not merge unknown accounts or override exclusion lists', () => {
  const first = entry('non_marketing', ['qualified'])
  const second = entry('non_marketing', ['qualified'])
  const before = withReviewOutcomes({ entries: { first, second }, total: 2, completed: 2 })
  const after = applyReviewChange(before, { key: 'first', kind: 'account', decision: 'marketing' })
  assert.equal(after.entries.first.account, 'marketing')
  assert.equal(after.entries.second.account, 'non_marketing')
  const blocked = { ...entry('marketing', ['qualified']), account_key: 'blocked', account_source: 'blocklist' }
  const blockedReview = withReviewOutcomes({ entries: { blocked }, total: 1, completed: 1 })
  assert.equal(applyReviewChange(blockedReview, { key: 'blocked', kind: 'account', decision: 'non_marketing' }).entries.blocked.account, 'marketing')
})
