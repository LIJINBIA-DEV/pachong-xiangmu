import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { QueryClient, QueryObserver } from '@tanstack/react-query'
import ts from 'typescript'

const source = readFileSync(new URL('../src/lib/reviewLoading.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
const { reviewPostQueryOptions, savedImagePreviewUrl } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('rescan cannot send a negative offset even when refetch bypasses enabled=false', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const calls = []
  const observer = new QueryObserver(client, reviewPostQueryOptions('weibo/test.xlsx', -1, async (...args) => {
    calls.push(args)
    return { posts: [] }
  }))
  try {
    await observer.refetch()
    assert.deepEqual(calls, [])
  } finally { observer.destroy(); client.clear() }
})

test('retry uses the query identity and supports cancellation', async () => {
  const client = new QueryClient()
  const calls = []
  const options = reviewPostQueryOptions('weibo/one.xlsx', 2, async (file, offset, signal) => {
    calls.push({ file, offset, hasSignal: signal instanceof AbortSignal })
    return { posts: [{ id: 'third-post' }] }
  })
  try {
    const result = await client.fetchQuery(options)
    assert.equal(result.posts[0].id, 'third-post')
    assert.deepEqual(calls, [{ file: 'weibo/one.xlsx', offset: 2, hasSignal: true }])
  } finally { client.clear() }
})

test('rescan with no file performs no HTTP request', async () => {
  const client = new QueryClient()
  let calls = 0
  const observer = new QueryObserver(client, reviewPostQueryOptions('', 0, async () => { calls++; return {} }))
  try { await observer.refetch(); assert.equal(calls, 0) }
  finally { observer.destroy(); client.clear() }
})

test('cards request a preview while retaining their original image URL', () => {
  const image = { local: true, url: '/api/data/media/wb/media/post/001%20photo.jpg' }
  assert.equal(savedImagePreviewUrl(image), image.url + '?preview=true')
  assert.equal(image.url, '/api/data/media/wb/media/post/001%20photo.jpg')
  const remote = { local: false, url: 'https://example.com/remote.jpg' }
  assert.equal(savedImagePreviewUrl(remote), remote.url)
})
