import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildSync } from 'esbuild'
const code = buildSync({ entryPoints: ['src/lib/logBuffer.ts'], bundle: true, write: false, format: 'esm', platform: 'node', tsconfig: 'tsconfig.json' }).outputFiles[0].text
const { mergeLogBatch, createLogBuffer } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
const log = id => ({ id, timestamp: '12:00:00', level: 'info', message: String(id) })

test('a burst of 100 messages reaches the store as one batch', async () => {
  const received = []
  const buffer = createLogBuffer((logs, session) => received.push({ logs, session }))
  for (let id = 1; id <= 100; id++) buffer.push([log(id)], 'task-one')
  assert.equal(received.length, 0)
  await new Promise(resolve => setTimeout(resolve, 140))
  assert.equal(received.length, 1)
  assert.equal(received[0].logs.length, 100)
  assert.equal(received[0].session, 'task-one')
})

test('reconnecting does not replay duplicate or cleared logs or rerender unchanged arrays', () => {
  const current = [log(8), log(9)]
  assert.equal(mergeLogBatch(current, [log(1), log(8), log(9)], 7), current)
  assert.deepEqual(mergeLogBatch(current, [log(10), log(10), log(4)], 7).map(item => item.id), [8, 9, 10])
  assert.equal(mergeLogBatch([], Array.from({ length: 600 }, (_, id) => log(id)), null).length, 500)
})

test('a new run drops queued messages from the previous run', () => {
  const batches = []
  const buffer = createLogBuffer((logs, session) => batches.push({ logs, session }))
  buffer.push([log(80)], 'old')
  buffer.push([log(1)], 'new')
  buffer.flush()
  assert.deepEqual(batches, [{ logs: [log(1)], session: 'new' }])
})
