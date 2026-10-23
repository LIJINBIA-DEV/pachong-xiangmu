import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/lib/keywordCombinations.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { parseKeywordTxt, mergeKeywordTerms, createKeywordCombinations } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const encode = (text) => new TextEncoder().encode(text).buffer

test('TXT imports comma-separated whole words, preserves order, and deduplicates', () => {
  const incoming = parseKeywordTxt(encode('\ufeff可爱,萌，卡哇伊\r\n可爱,,,\n'))
  assert.deepEqual(incoming, ['可爱', '萌', '卡哇伊'])
  assert.deepEqual(mergeKeywordTerms('可爱,软萌', incoming), ['可爱', '软萌', '萌', '卡哇伊'])
  assert.deepEqual(createKeywordCombinations({first: incoming.join(','), second: '公园,广场'}),
    ['可爱 公园', '可爱 广场', '萌 公园', '萌 广场', '卡哇伊 公园', '卡哇伊 广场'])
})
test('UTF-16 Notepad and legacy GBK files import Chinese without replacement characters', () => {
  const utf16 = Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from('公园,广场', 'utf16le')])
  assert.deepEqual(parseKeywordTxt(utf16.buffer.slice(utf16.byteOffset, utf16.byteOffset + utf16.byteLength)), ['公园', '广场'])
  assert.deepEqual(parseKeywordTxt(Uint8Array.from([0xb9,0xab,0xd4,0xb0,0x2c,0xb9,0xe3,0xb3,0xa1]).buffer), ['公园', '广场'])
})
test('empty and binary-looking files are rejected before adding labels', () => {
  assert.throws(() => parseKeywordTxt(encode(' ,\n， ')), /empty/)
  assert.throws(() => parseKeywordTxt(Uint8Array.from([0, 1, 2, 3]).buffer), /format/)
  assert.deepEqual(parseKeywordTxt(encode('city walk,口袋公园')), ['city walk', '口袋公园'])
})
