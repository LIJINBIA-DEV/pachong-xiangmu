import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildSync } from 'esbuild'

const code = buildSync({ entryPoints: ['src/lib/collectionStartValidation.ts'], bundle: true, write: false,
  format: 'esm', platform: 'node' }).outputFiles[0].text
const { firstIncompleteStartSection: issue } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
const ready = () => ({ platform: 'xhs', crawler_type: 'search', max_notes_count: 6, publish_time_range: 'all',
  save_option: 'excel', semantic_filter: true, semantic_rule: 'topic', semantic_model: 'openai-compatible',
  enable_comments: true, login_type: 'qrcode', cookies: '', specified_ids: '', creator_ids: '' })
const context = () => ({ topics: [{ text: '采集主题', evaluation: '' }], keyAvailable: true, loginReady: true,
  models: ['openai-compatible', 'jev-1.13.0', 'semif-qwen3.5-4b-q4'] })

test('each click reports only the first unfinished section in the requested order', () => {
  const config = { ...ready(), max_notes_count: null }
  const state = { ...context(), keyAvailable: false, loginReady: false, topics: [{ text: '', evaluation: '' }] }
  assert.equal(issue(config, state), 'target')
  assert.equal(issue(config, state), 'target')
  config.max_notes_count = 6
  assert.equal(issue(config, state), 'output')
  state.keyAvailable = true
  assert.equal(issue(config, state), 'topics')
  state.topics[0].text = '采集主题'
  assert.equal(issue(config, state), 'login')
  state.loginReady = true
  assert.equal(issue(config, state), null)
})

test('a saved key, disabled semantic filtering, and a local model require no retyping', () => {
  assert.equal(issue(ready(), context()), null)
  assert.equal(issue({ ...ready(), semantic_filter: false, semantic_model: '' }, { ...context(), keyAvailable: false }), null)
  assert.equal(issue({ ...ready(), semantic_model: 'semif-qwen3.5-4b-q4' }, { ...context(), keyAvailable: false }), null)
  assert.equal(issue({ ...ready(), semantic_model: '' }, context()), 'output')
})

test('invalid target counts and incomplete custom dates take precedence', () => {
  for (const count of [null, 0, -1, 1.5, 10001, NaN]) {
    assert.equal(issue({ ...ready(), max_notes_count: count }, { ...context(), keyAvailable: false }), 'target')
  }
  assert.equal(issue({ ...ready(), publish_time_range: 'custom', publish_start_date: '2026-10-28', publish_end_date: '' }, context()), 'target')
  assert.equal(issue({ ...ready(), publish_time_range: 'custom', publish_start_date: '2026-10-28', publish_end_date: '2026-10-27' }, context()), 'target')
})

test('an optional evaluation is required only when enabled, and duplicate topics are caught', () => {
  assert.equal(issue({ ...ready(), semantic_rule: 'scene' }, context()), 'topics')
  assert.equal(issue({ ...ready(), semantic_rule: 'scene' }, { ...context(), topics: [{ text: '主题', evaluation: '评价' }] }), null)
  assert.equal(issue(ready(), { ...context(), topics: [context().topics[0], context().topics[0]] }), 'topics')
})

test('detail/creator inputs and cookie login cannot silently submit empty values', () => {
  for (const mode of ['detail', 'creator']) {
    const config = { ...ready(), crawler_type: mode, semantic_filter: false, max_notes_count: null, login_type: 'cookie' }
    assert.equal(issue(config, context()), 'topics')
    config[mode === 'detail' ? 'specified_ids' : 'creator_ids'] = 'post-or-creator-id'
    assert.equal(issue(config, context()), 'login')
    config.cookies = 'test-cookie'
    assert.equal(issue(config, context()), null)
  }
})
