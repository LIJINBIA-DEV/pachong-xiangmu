import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildSync } from 'esbuild'

const code = buildSync({ entryPoints: ['src/lib/publicationRange.ts'], bundle: true, write: false, format: 'esm', platform: 'node' }).outputFiles[0].text
const { publicationRangeError } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)

test('presets do not require leftover custom dates', () => {
  for (const publish_time_range of ['all', 'week', 'day', 'month']) {
    assert.equal(publicationRangeError({ publish_time_range, publish_start_date: '', publish_end_date: '' }), null)
  }
})

test('custom date input rejects missing, reversed and nonexistent calendar dates', () => {
  const custom = (start, end) => publicationRangeError({ publish_time_range: 'custom', publish_start_date: start, publish_end_date: end })
  assert.equal(custom('', ''), 'required')
  assert.equal(custom('2026-10-02', '2026-10-01'), 'order')
  assert.equal(custom('2026-02-30', '2026-03-02'), 'invalid')
  assert.equal(custom('2026-10-01', '2026-10-01'), null)
  assert.equal(custom('2024-02-29', '2024-03-01'), null)
})
