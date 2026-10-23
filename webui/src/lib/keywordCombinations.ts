export interface KeywordGroups {
  first: string
  second: string
}

/** Commas, list separators and newlines separate terms; spaces inside a term are kept. */
export function parseKeywordGroup(value: string): string[] {
  return [...new Set(value.split(/[,，、;；\r\n]+/)
    .map((term) => term.trim().replace(/\s+/g, ' '))
    .filter(Boolean))]
}

/** Windows Notepad TXT files: UTF-8, UTF-16 with BOM, or legacy GBK. */
export function parseKeywordTxt(buffer: ArrayBuffer): string[] {
  const bytes = new Uint8Array(buffer)
  let content: string
  try {
    if (bytes[0] === 0xff && bytes[1] === 0xfe) content = new TextDecoder('utf-16le', { fatal: true }).decode(bytes)
    else if (bytes[0] === 0xfe && bytes[1] === 0xff) content = new TextDecoder('utf-16be', { fatal: true }).decode(bytes)
    else {
      try { content = new TextDecoder('utf-8', { fatal: true }).decode(bytes) }
      catch { content = new TextDecoder('gb18030', { fatal: true }).decode(bytes) }
    }
  } catch { throw new Error('format') }
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffd]/.test(content)) throw new Error('format')
  const terms = parseKeywordGroup(content.replace(/^\ufeff/, ''))
  if (!terms.length) throw new Error('empty')
  return terms
}

export function mergeKeywordTerms(existing: string, incoming: string[]): string[] {
  return [...new Set([...parseKeywordGroup(existing), ...incoming])]
}

/** Keep the first group's order, then pair each term with every term in the second group. */
export function createKeywordCombinations(groups: KeywordGroups): string[] {
  return createKeywordPairs(groups).map(([left, right]) => `${left} ${right}`)
}

export function createKeywordPairs(groups: KeywordGroups): [string, string][] {
  const first = parseKeywordGroup(groups.first)
  const second = parseKeywordGroup(groups.second)
  const seen = new Set<string>()
  return first.flatMap((left) => second.map((right): [string, string] => [left, right]))
    .filter(([left, right]) => {
      const query = `${left} ${right}`
      if (seen.has(query)) return false
      seen.add(query)
      return true
    })
}
