import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/lib/keywordSearches.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { parseKeywordSearches, keywordSearchConfig, keywordSearchError, parseSearchTxt } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const encode = (text) => new TextEncoder().encode(text).buffer

test('each authored nonblank row remains one search, without cross-pairing or deduplication', () => {
  const text = '\ufeff 可爱  公园\r\n\r\n萌\t雕塑\r可爱　公园\n萌 公园 雕像'
  assert.deepEqual(parseKeywordSearches(text), ['可爱 公园', '萌 雕塑', '可爱 公园', '萌 公园 雕像'])
  const config = keywordSearchConfig(text)
  assert.equal(config.keywords, '可爱 公园,萌 雕塑,可爱 公园,萌 公园 雕像')
  assert.deepEqual(config.keyword_pairs, [['可爱', '公园'], ['萌', '雕塑'], ['可爱', '公园'], ['萌', '公园 雕像']])
  assert.deepEqual(config.keyword_pairs.map(([a, b]) => `${a} ${b}`), config.keywords.split(','))
})
test('invalid separators, unfinished rows, empty or oversized input cannot start a task', () => {
  assert.equal(keywordSearchError('可爱 公园\n萌 雕像'), null)
  assert.equal(keywordSearchError('可爱 公园\n\n萌').line, 3)
  assert.equal(keywordSearchError('可爱,公园').reason, 'separator')
  assert.equal(keywordSearchError('可爱 公园,萌 雕像').reason, 'separator')
  assert.equal(keywordSearchError(' \n ').reason, 'empty')
  assert.equal(keywordSearchError(Array(10001).fill('可爱 公园').join('\n')).reason, 'limit')
})
test('new TXT format shares typing rules and supports UTF-8, UTF-16 and GBK', () => {
  assert.deepEqual(parseSearchTxt(encode('\ufeff可爱 公园\r\n萌 雕像')), ['可爱 公园', '萌 雕像'])
  const utf16 = Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from('可爱 公园\r\n萌 雕像', 'utf16le')])
  assert.deepEqual(parseSearchTxt(utf16.buffer.slice(utf16.byteOffset, utf16.byteOffset + utf16.byteLength)), ['可爱 公园', '萌 雕像'])
  assert.deepEqual(parseSearchTxt(Uint8Array.from([0xbf,0xc9,0xb0,0xae,0x20,0xb9,0xab,0xd4,0xb0]).buffer), ['可爱 公园'])
  assert.throws(() => parseSearchTxt(encode('可爱,萌')), /separator/)
  assert.throws(() => parseSearchTxt(encode('公园')), /terms/)
  assert.throws(() => parseSearchTxt(Uint8Array.from([0,1,2,3]).buffer))
})
test('converted source TXT contains all 189 former searches in source order', () => {
  const bytes = readFileSync(new URL('../../../关键词组合.txt', import.meta.url))
  const rows = parseSearchTxt(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength))
  assert.equal(rows.length, 189)
  assert.equal(rows[0], '可爱 公园')
  assert.equal(rows[63], '萌 公园')
  assert.equal(rows[188], '卡哇伊 休息区')
})
