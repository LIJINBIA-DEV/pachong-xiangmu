import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildSync } from 'esbuild'
const code = buildSync({ entryPoints: ['src/lib/topicCards.ts'], bundle: true, write: false, format: 'esm', platform: 'node' }).outputFiles[0].text
const { topicFromText, topicSearchConfig, topicsError } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)

test('complete topics are never automatically split into an opinion and object', () => {
  const card = topicFromText('苏州 房价')
  assert.deepEqual(card, { text: '苏州 房价', evaluation: '' })
  assert.equal(topicsError([card], false), null)
  assert.equal(topicsError([card], true), 'evaluation')
  assert.deepEqual(topicSearchConfig([card], false), { keywords: '苏州 房价', keyword_pairs: [['苏州 房价', '']] })
})
test('optional opinions use the entire topic as the target and preserve the API contract', () => {
  const cards = [{ text: ' 苏州  房价 ', evaluation: ' 贵 ' }, { text: '教师编考试', evaluation: '难考' }]
  assert.deepEqual(topicSearchConfig(cards, true), { keywords: '贵 苏州 房价,难考 教师编考试', keyword_pairs: [['贵', '苏州 房价'], ['难考', '教师编考试']] })
  assert.equal(topicsError(cards, true), null)
  assert.equal(topicsError([{ text: '主题', evaluation: '贵,便宜' }], true), 'separator')
  assert.equal(topicsError([{ text: '', evaluation: '贵' }], true), 'empty')
  assert.equal(topicsError([cards[0], { text: '苏州 房价', evaluation: '贵' }], true), 'duplicate')
})
