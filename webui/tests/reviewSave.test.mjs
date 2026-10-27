import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { QueryClient, MutationObserver } from '@tanstack/react-query'
import ts from 'typescript'

const moduleUrl = (source) => `data:text/javascript;base64,${Buffer.from(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText).toString('base64')}`
const outcomeUrl = moduleUrl(readFileSync(new URL('../src/lib/reviewOutcome.ts', import.meta.url), 'utf8'))
const saveSource = readFileSync(new URL('../src/lib/reviewSave.ts', import.meta.url), 'utf8').replaceAll("'./reviewOutcome'", JSON.stringify(outcomeUrl))
const { reviewSaveOptions } = await import(moduleUrl(saveSource))
const { withReviewOutcomes } = await import(outcomeUrl)
const file = 'weibo/posts.json'
const key = ['manualReview', file]
const note = { account: 'non_marketing', account_key: 'author', images: { '1.jpg': 'qualified' }, review_images: [{ key: '1.jpg', decision_source: 'model' }], decision: null, post_decision: 'qualified', post_decision_source: 'manual' }
const initial = () => withReviewOutcomes({ entries: { first: structuredClone(note), second: structuredClone(note) }, total: 2, completed: 2 })
const change = { file, key: 'first', kind: 'post', decision: 'unqualified' }

test('actual save lifecycle updates before persistence returns and merges partial acknowledgement', async () => {
  const client = new QueryClient()
  client.setQueryData(key, initial())
  client.setQueryData(['collectionTasks'], { tasks: [] })
  client.setQueryData(['dataBrowse', file], { posts: [] })
  let acknowledge
  let signalStarted
  const started = new Promise((resolve) => { signalStarted = resolve })
  const observer = new MutationObserver(client, reviewSaveOptions(client, () => {
    signalStarted()
    return new Promise((resolve) => { acknowledge = resolve })
  }))
  const pending = observer.mutate(change)
  await started
  assert.equal(observer.getCurrentResult().isPending, true)
  assert.equal(client.getQueryData(key).entries.first.decision, 'unqualified')
  assert.equal(client.getQueryData(key).entries.second.decision, 'qualified')
  acknowledge({ entries: { first: client.getQueryData(key).entries.first }, partial: true, total: 1, completed: 1 })
  await pending
  assert.equal(client.getQueryData(key).total, 2)
  assert.equal(client.getQueryData(key).completed, 2)
  assert.equal(observer.getCurrentResult().isSuccess, true)
  assert.equal(client.getQueryState(['collectionTasks']).isInvalidated, true)
  assert.equal(client.getQueryState(['dataBrowse', file]).isInvalidated, true)
  client.clear()
})

test('actual failed save rolls back the image and post outcome and permits retry', async () => {
  const client = new QueryClient()
  const before = initial()
  client.setQueryData(key, before)
  let rejectSave
  let signalStarted
  let shouldFail = true
  const started = new Promise((resolve) => { signalStarted = resolve })
  const observer = new MutationObserver(client, reviewSaveOptions(client, () => {
    if (!shouldFail) return Promise.resolve({ entries: { first: client.getQueryData(key).entries.first }, partial: true, total: 1, completed: 1 })
    signalStarted()
    return new Promise((_resolve, reject) => { rejectSave = reject })
  }))
  const pending = observer.mutate(change)
  const failed = assert.rejects(pending, /disk write failed/)
  await started
  assert.equal(client.getQueryData(key).entries.first.decision, 'unqualified')
  rejectSave(new Error('disk write failed'))
  await failed
  assert.equal(observer.getCurrentResult().isError, true)
  assert.deepEqual(client.getQueryData(key), before)
  shouldFail = false
  await observer.mutate(change)
  assert.equal(client.getQueryData(key).entries.first.decision, 'unqualified')
  assert.equal(client.getQueryData(key).entries.second.decision, 'qualified')
  client.clear()
})

test('general evaluation can retain a text-only post and never inherits image gates', () => {
  const entry = { ...structuredClone(note), requires_images: false, review_images: [], images: {}, post_decision: 'qualified', post_decision_source: 'manual' }
  const result = withReviewOutcomes({ entries: { first: entry }, total: 1, completed: 0 })
  assert.equal(result.entries.first.decision, 'qualified')
  assert.equal(result.entries.first.automatic_decision, null)
  assert.equal(result.entries.first.automatic_decision_reason, 'text_review_pending')
  entry.post_decision = null
  entry.review_images = [{ key: 'bad.jpg' }]
  entry.images = { 'bad.jpg': 'unqualified' }
  assert.equal(withReviewOutcomes({ entries: { first: entry }, total: 1, completed: 0 }).entries.first.decision, null)
})


test('approval advances only after persistence confirms approval, including retry', async () => {
  const client = new QueryClient()
  client.setQueryData(key, initial())
  const approval = { file, key: 'first', kind: 'post', decision: 'qualified' }
  const advanced = []
  let acknowledge
  let fail = false
  let started
  const observer = new MutationObserver(client, reviewSaveOptions(client, () => new Promise((resolve, reject) => {
    acknowledge = (data) => fail ? reject(new Error('save failed')) : resolve(data)
    started()
  }), (saved) => advanced.push(saved.key)))
  const run = async (command, accepted = true) => {
    const ready = new Promise((resolve) => { started = resolve })
    const pending = observer.mutate(command)
    const settled = pending.then(() => null, error => error)
    await ready
    const count = advanced.length
    assert.equal(observer.getCurrentResult().isPending, true)
    assert.equal(advanced.length, count)
    const entry = structuredClone(client.getQueryData(key).entries.first)
    if (!accepted) { entry.semantic_rejection_reason = 'semantic_rejected'; entry.decision = 'unqualified' }
    acknowledge({ entries: { first: entry }, partial: true, total: 1, completed: 1 })
    const error = await settled
    return { error, count }
  }
  fail = true
  assert.match((await run(approval)).error.message, /save failed/)
  assert.deepEqual(advanced, [])
  fail = false
  await run(approval)
  assert.deepEqual(advanced, ['first'])
  await run({ ...approval, decision: 'unqualified' })
  await run({ ...approval, decision: null, post_decision: 'qualified', post_decision_source: 'manual' })
  await run(change)
  await run(approval, false)
  assert.deepEqual(advanced, ['first'])
  client.clear()
})
