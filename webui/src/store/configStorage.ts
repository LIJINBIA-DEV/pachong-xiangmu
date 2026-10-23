import type { CrawlerConfig } from '@/types/crawler'
import { createKeywordCombinations, parseKeywordGroup } from '@/lib/keywordCombinations'
import { keywordSearchConfig } from '@/lib/keywordSearches'

const KEY = 'mediacrawler_config_v1'

export function loadConfig(defaults: CrawlerConfig) {
  const result = { config: { ...defaults }, keywordText: '' }
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (saved?.version !== 1 && saved?.version !== 2) return result
    for (const key of Object.keys(defaults) as (keyof CrawlerConfig)[]) {
      if (['cookies', 'semantic_api_key', 'keyword_pairs', 'keywords', 'save_option'].includes(key)) continue
      const value = saved.config?.[key]
      if (key === 'login_environment' && !['auto', 'local', 'server'].includes(value)) continue
      if ((key === 'max_notes_count' || key === 'max_comments_count') && value === null) {
        result.config[key] = null
      } else if (typeof value === typeof defaults[key] && value !== undefined) {
        Object.assign(result.config, { [key]: value })
      }
    }
    if (saved.version === 2) {
      result.keywordText = typeof saved.keywordText === 'string' ? saved.keywordText : ''
    } else {
      // One-time migration only. New authored rows never generate a Cartesian product.
      const legacyGroup = (key: 'first' | 'second') => [saved.keywordGroups?.[key], saved.keywordDrafts?.[key]]
        .filter((value): value is string => typeof value === 'string').join(',')
      const first = legacyGroup('first'), second = legacyGroup('second')
      result.keywordText = createKeywordCombinations({ first, second }).join('\n')
      if (!result.keywordText) result.keywordText = [...parseKeywordGroup(first), ...parseKeywordGroup(second)].join('\n')
      if (!result.keywordText && typeof saved.config?.keywords === 'string') result.keywordText = saved.config.keywords.split(',').join('\n')
    }
    Object.assign(result.config, keywordSearchConfig(result.keywordText))
  } catch { /* Invalid or unavailable storage must not prevent editing. */ }
  return result
}

export function saveConfig(config: CrawlerConfig, keywordText: string) {
  try {
    const { cookies: _cookies, semantic_api_key: _key, ...saved } = config
    localStorage.setItem(KEY, JSON.stringify({ version: 2, config: { ...saved, save_option: 'excel' }, keywordText }))
  } catch { /* Storage can be disabled or full; keep settings in memory. */ }
}
