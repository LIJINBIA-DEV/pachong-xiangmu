import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildSync } from 'esbuild'

const code = buildSync({ entryPoints: ['src/lib/reviewFiles.ts'], bundle: true, write: false, format: 'esm', platform: 'node' }).outputFiles[0].text
const { reviewFileSelection } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
const file = name => ({ name, path: `weibo/${name}`, type: name.endsWith('.xlsx') ? 'xlsx' : 'json' })

test('review offers only main Excel and maps a saved semantic selection to the same round', () => {
  const all = ['second.xlsx', 'second_semantic.xlsx', 'first.xlsx', 'first_semantic.xlsx', 'posts.json'].map(file)
  const selected = reviewFileSelection(all, 'weibo/first_semantic.xlsx')
  assert.deepEqual(selected.files.map(item => item.name), ['second.xlsx', 'first.xlsx'])
  assert.equal(selected.currentFile, 'weibo/first.xlsx')
  assert.equal(selected.missingMain, false)
})

test('missing main file does not silently load a different collection', () => {
  const selected = reviewFileSelection(['other.xlsx', 'lost_semantic.xlsx'].map(file), 'weibo/lost_semantic.xlsx')
  assert.equal(selected.currentFile, '')
  assert.equal(selected.missingMain, true)
})
