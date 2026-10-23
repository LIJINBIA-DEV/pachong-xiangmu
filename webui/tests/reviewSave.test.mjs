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
const note = { account: 'non_marketing', account_key: 'author', images: { '1.jpg': 'qualified' }, review_images: [{ key: '1.jpg', decision_source: 'model' }], decision: null }
const initial = () => withReviewOutcomes({ entries: { first: structuredClone(note), second: structuredClone(note) }, total: 2, completed: 2 })
const change = { file, key: 'first', kind: 'image', imageKey: '1.jpg', decision: 'unqualified' }

test('actual save lifecycle updates before persistence returns and merges partial acknowledgement', async () => {
  const client = new QueryClient()
  client.setQueryData(key, initial())
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
