/** Each nonblank line is one search. Never generate combinations from authored rows. */
export function parseKeywordSearches(value: string): string[] {
  return value.replace(/^\ufeff/, '').split(/\r\n?|\n/)
    .map((line) => line.trim().replace(/\s+/g, ' ')).filter(Boolean)
}

export function keywordSearchError(value: string, rule: 'scene' | 'topic' = 'scene'): { reason: string; line?: number } | null {
  const rows = value.replace(/^\ufeff/, '').split(/\r\n?|\n/)
  if (!parseKeywordSearches(value).length) return { reason: 'empty' }
  if (parseKeywordSearches(value).length > 10000) return { reason: 'limit' }
  for (let index = 0; index < rows.length; index++) {
    const row = rows[index].trim()
    if (!row) continue
    if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffd]/.test(row)) return { reason: 'format', line: index + 1 }
    if (/[,，、;；]/.test(row)) return { reason: 'separator', line: index + 1 }
    if (rule === 'scene' && row.split(/\s+/).length < 2) return { reason: 'terms', line: index + 1 }
  }
  return null
}

/** Keep the existing semantic API contract: first term, followed by remaining terms. */
export function keywordSearchConfig(value: string) {
  const searches = parseKeywordSearches(value)
  return {
    keywords: searches.join(','),
    keyword_pairs: searches.map((search): [string, string] => {
      const [first, ...rest] = search.split(' ')
      return [first, rest.join(' ')]
    }),
  }
}

/** UTF-8, UTF-16 Notepad and legacy GBK TXT, with the same row rules as typing. */
export function parseSearchTxt(buffer: ArrayBuffer, rule: 'scene' | 'topic' = 'scene'): string[] {
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
  const error = keywordSearchError(content, rule)
  if (error) throw new Error(error.reason)
  return parseKeywordSearches(content)
}
