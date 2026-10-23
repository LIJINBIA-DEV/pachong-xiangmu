import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildSync } from 'esbuild'

const compiled = buildSync({
  entryPoints: ['src/store/crawlerStore.ts'], bundle: true, write: false,
  format: 'esm', platform: 'node', tsconfig: 'tsconfig.json',
}).outputFiles[0].text
let generation = 0
async function reloadStore() {
  const code = `${compiled}\n// load ${generation++}`
  return (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).useCrawlerStore
}
function storage() {
  const values = new Map()
  globalThis.localStorage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  }
  return values
}

test('login environment survives reload and invalid saved modes use auto', async () => {
  const values = storage()
  let store = await reloadStore()
  store.getState().updateConfig({ login_environment: 'server' })
  store = await reloadStore()
  assert.equal(store.getState().config.login_environment, 'server')
  store.getState().updateConfig({ login_environment: 'local' })
  store = await reloadStore()
  assert.equal(store.getState().config.login_environment, 'local')
  values.set('mediacrawler_config_v1', JSON.stringify({ version: 2, config: { login_environment: 'invalid' } }))
  store = await reloadStore()
  assert.equal(store.getState().config.login_environment, 'auto')
})

test('reload keeps authored search rows and collection settings, but no secrets or run status', async () => {
  const values = storage()
  let store = await reloadStore()
  store.getState().updateConfig({ max_notes_count: 10, max_comments_count: 80, save_option: 'excel', semantic_filter: true, enable_media: true, cookies: 'PRIVATE_COOKIE', semantic_api_key: 'PRIVATE_KEY' })
  store.getState().updateKeywordText('可爱 公园\n萌 广场\n可爱 公园')
  store.getState().setStatus('running')
  const persisted = values.get('mediacrawler_config_v1')
  assert.ok(!persisted.includes('PRIVATE_COOKIE') && !persisted.includes('PRIVATE_KEY'))
  store = await reloadStore()
  const state = store.getState()
  assert.equal(state.config.max_notes_count, 10)
  assert.equal(state.config.max_comments_count, 80)
  assert.equal(state.config.save_option, 'excel')
  assert.equal(state.config.semantic_filter, true)
  assert.equal(state.config.enable_media, true)
  assert.equal(state.config.keyword_pairs.length, 3)
  assert.equal(state.config.keywords, '可爱 公园,萌 广场,可爱 公园')
  assert.equal(state.keywordText, '可爱 公园\n萌 广场\n可爱 公园')
  assert.equal(state.config.cookies, '')
  assert.equal(state.config.semantic_api_key, undefined)
  assert.equal(state.status, 'idle')
  state.restoreLogs() // Must work without window.location or navigation.
  assert.equal(store.getState().config.max_notes_count, 10)
})

test('legacy groups and pending drafts migrate once, then new rows are never expanded', async () => {
  const values = storage()
  values.set('mediacrawler_config_v1', JSON.stringify({ version: 1,
    config: { max_notes_count: 11 }, keywordGroups: { first: '可爱,萌', second: '公园,广场' }, keywordDrafts: { second: '街区' } }))
  let store = await reloadStore()
  assert.equal(store.getState().keywordText, '可爱 公园\n可爱 广场\n可爱 街区\n萌 公园\n萌 广场\n萌 街区')
  store.getState().updateKeywordText('可爱 雕塑\n萌 公园')
  assert.equal(JSON.parse(values.get('mediacrawler_config_v1')).version, 2)
  store = await reloadStore()
  assert.deepEqual(store.getState().config.keyword_pairs, [['可爱', '雕塑'], ['萌', '公园']])
  assert.equal(store.getState().config.max_notes_count, 11)
})

test('unfinished legacy input and new invalid drafts remain editable across reload', async () => {
  const values = storage()
  values.set('mediacrawler_config_v1', JSON.stringify({ version: 1, keywordGroups: { first: '可爱,萌', second: '' } }))
  let store = await reloadStore()
  assert.equal(store.getState().keywordText, '可爱\n萌')
  store.getState().updateKeywordText('可爱 公园\n尚未写完 ')
  store = await reloadStore()
  assert.equal(store.getState().keywordText, '可爱 公园\n尚未写完 ')
})

test('invalid or disabled browser storage does not break startup or editing', async () => {
  const values = storage()
  values.set('mediacrawler_config_v1', '{invalid')
  assert.equal((await reloadStore()).getState().config.max_notes_count, 15)
  globalThis.localStorage = { getItem() { throw Error('disabled') }, setItem() { throw Error('disabled') }, removeItem() { throw Error('disabled') } }
  const store = await reloadStore()
  store.getState().updateConfig({ max_notes_count: 10 })
  store.getState().clearLogs()
  assert.equal(store.getState().config.max_notes_count, 10)
})

test('new and historical settings offer Excel without persisting secrets', async () => {
  const values = storage()
  let store = await reloadStore()
  assert.equal(store.getState().config.save_option, 'excel')
  values.set('mediacrawler_config_v1', JSON.stringify({ version: 1, config: { save_option: 'json', max_notes_count: 21 } }))
  store = await reloadStore()
  assert.equal(store.getState().config.save_option, 'excel')
  assert.equal(store.getState().config.max_notes_count, 21)
  store.getState().updateConfig({ max_notes_count: 22 })
  assert.equal(JSON.parse(values.get('mediacrawler_config_v1')).config.save_option, 'excel')
})
