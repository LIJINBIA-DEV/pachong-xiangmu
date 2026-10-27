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

test('publication ranges and custom dates survive reload while unknown ranges use unlimited', async () => {
  const values = storage()
  let store = await reloadStore()
  assert.equal(store.getState().config.publish_time_range, 'all')
  store.getState().updateConfig({ publish_time_range: 'custom', publish_start_date: '2026-10-01', publish_end_date: '2026-10-26' })
  store = await reloadStore()
  assert.equal(store.getState().config.publish_time_range, 'custom')
  assert.equal(store.getState().config.publish_start_date, '2026-10-01')
  assert.equal(store.getState().config.publish_end_date, '2026-10-26')
  values.set('mediacrawler_config_v1', JSON.stringify({ version: 2, config: { publish_time_range: 'unsupported' } }))
  store = await reloadStore()
  assert.equal(store.getState().config.publish_time_range, 'all')
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
    config: { max_notes_count: 11, semantic_filter: true, semantic_rule: 'scene' }, keywordGroups: { first: '可爱,萌', second: '公园,广场' }, keywordDrafts: { second: '街区' } }))
  let store = await reloadStore()
  assert.equal(store.getState().keywordText, '公园\n广场\n街区\n公园\n广场\n街区')
  assert.equal(store.getState().config.keywords, '可爱 公园,可爱 广场,可爱 街区,萌 公园,萌 广场,萌 街区')
  store.getState().updateCollectionTopics([{ text: '雕塑', evaluation: '可爱' }, { text: '公园', evaluation: '萌' }])
  assert.equal(JSON.parse(values.get('mediacrawler_config_v1')).version, 4)
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


test('cleared logs stay cleared across status polling, reconnect and reload, but reset for a new run', async () => {
  storage()
  let store = await reloadStore()
  const log = id => ({ id, timestamp: '12:00:00', level: 'info', message: String(id) })
  store.getState().receiveLogs([log(9), log(10)], 'old-run')
  store.getState().clearLogs()
  store.getState().setStatus('running')
  store.getState().setRunningInfo('xhs', 'search', '2026-10-26')
  store.getState().receiveLogs([log(9), log(10)], 'old-run')
  assert.equal(store.getState().logs.length, 0)
  store = await reloadStore()
  store.getState().receiveLogs([log(9), log(10)], 'old-run')
  assert.equal(store.getState().logs.length, 0)
  store.getState().receiveLogs([log(11)], 'old-run')
  store.getState().receiveLogs([log(1)], 'new-run')
  assert.deepEqual(store.getState().logs.map(item => item.id), [1])
  assert.equal(store.getState().clearedAfterLogId, null)
})

test('legacy image recognition settings are not restored', async () => {
  const values = storage()
  values.set('mediacrawler_config_v1', JSON.stringify({ version: 3, config: { image_subject_recognition: true, enable_media: true }, collectionTopics: [{ text: '已有主题', evaluation: '已有', place: '主题' }] }))
  const store = await reloadStore()
  assert.equal(store.getState().config.image_subject_recognition, undefined)
  assert.equal(store.getState().config.enable_media, true)
  assert.equal(store.getState().collectionTopics[0].text, '已有主题')
})


test('v3 evaluation cards migrate without changing the original queries or evaluation targets', async () => {
  const values = storage()
  values.set('mediacrawler_config_v1', JSON.stringify({ version: 3, config: { semantic_filter: true, semantic_rule: 'scene' },
    collectionTopics: [{ text: '难考 长沙 教师编', evaluation: '难考', place: '长沙 教师编' }] }))
  let store = await reloadStore()
  assert.deepEqual(store.getState().collectionTopics, [{ text: '长沙 教师编', evaluation: '难考' }])
  assert.equal(store.getState().config.keywords, '难考 长沙 教师编')
  assert.deepEqual(store.getState().config.keyword_pairs, [['难考', '长沙 教师编']])
  store.getState().updateConfig({ semantic_rule: 'topic' })
  assert.equal(store.getState().collectionTopics[0].text, '长沙 教师编')
  assert.equal(store.getState().config.keywords, '长沙 教师编')
  store = await reloadStore()
  assert.equal(store.getState().collectionTopics[0].evaluation, '难考')
  store.getState().updateConfig({ semantic_rule: 'scene' })
  assert.deepEqual(store.getState().config.keyword_pairs, [['难考', '长沙 教师编']])
})

test('v3 topic cards keep the whole authored topic instead of guessing an opinion', async () => {
  const values = storage()
  for (const config of [{ semantic_filter: true, semantic_rule: 'topic' }, { semantic_filter: false, semantic_rule: 'scene' }]) {
    values.set('mediacrawler_config_v1', JSON.stringify({ version: 3, config,
      collectionTopics: [{ text: '苏州 房价', evaluation: '苏州', place: '房价' }] }))
    const store = await reloadStore()
    assert.deepEqual(store.getState().collectionTopics, [{ text: '苏州 房价', evaluation: '' }])
    assert.equal(store.getState().config.keywords, '苏州 房价')
  }
})

test('new topic and opinion drafts survive edits, toggles and reload independently', async () => {
  storage()
  let store = await reloadStore()
  store.getState().updateConfig({ semantic_filter: true, semantic_rule: 'scene' })
  store.getState().updateCollectionTopics([{ text: '苏州 房价', evaluation: '贵' }, { text: '教师编考试', evaluation: '' }])
  store = await reloadStore()
  assert.deepEqual(store.getState().collectionTopics, [{ text: '苏州 房价', evaluation: '贵' }, { text: '教师编考试', evaluation: '' }])
  store.getState().updateConfig({ semantic_filter: false })
  assert.equal(store.getState().config.keywords, '苏州 房价,教师编考试')
  store.getState().updateConfig({ semantic_filter: true })
  assert.equal(store.getState().config.keywords, '贵 苏州 房价,教师编考试')
  store.getState().updateCollectionTopics([{ text: '苏州 新房价格', evaluation: '贵' }])
  assert.deepEqual(store.getState().config.keyword_pairs, [['贵', '苏州 新房价格']])
})
