import type { CrawlerConfig } from '@/types/crawler'
import { createKeywordCombinations, parseKeywordGroup } from '@/lib/keywordCombinations'
import { topicFromText, topicSearchConfig, type TopicCard } from '@/lib/topicCards'

const KEY = 'mediacrawler_config_v1'

export function loadConfig(defaults: CrawlerConfig) {
  const result = { config: { ...defaults }, keywordText: '', collectionTopics: [topicFromText('')] }
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (![1, 2, 3, 4].includes(saved?.version)) return result
    for (const key of Object.keys(defaults) as (keyof CrawlerConfig)[]) {
      if (['cookies', 'semantic_api_key', 'keyword_pairs', 'keywords', 'save_option'].includes(key)) continue
      const value = saved.config?.[key]
      if (key === 'login_environment' && !['auto', 'local', 'server'].includes(value)) continue
      if (key === 'publish_time_range' && !['all', 'week', 'day', 'month', 'custom'].includes(value)) continue
      if ((key === 'max_notes_count' || key === 'max_comments_count') && value === null) {
        result.config[key] = null
      } else if (typeof value === typeof defaults[key] && value !== undefined) {
        Object.assign(result.config, { [key]: value })
      }
    }
    if (saved.version >= 2) {
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
    const legacyEvaluation = saved.version < 4 && result.config.semantic_filter && result.config.semantic_rule === 'scene'
    const cards = saved.collectionTopics
    if (saved.version >= 3 && Array.isArray(cards) && cards.length && cards.length <= 10000 && cards.every(card => card && typeof card.text === 'string' && typeof card.evaluation === 'string' && (saved.version !== 3 || typeof card.place === 'string'))) {
      result.collectionTopics = cards.map(card => ({
        text: legacyEvaluation ? card.place : card.text,
        evaluation: saved.version === 4 || legacyEvaluation ? card.evaluation : '',
      }))
    } else {
      result.collectionTopics = result.keywordText.split(/\r\n?|\n/).filter(row => row.trim()).map(text => {
        if (!legacyEvaluation) return topicFromText(text)
        const [evaluation, ...topic] = text.trim().split(/\s+/)
        return { text: topic.join(' '), evaluation }
      })
    }
    if (!result.collectionTopics.length) result.collectionTopics = [topicFromText('')]
    result.keywordText = result.collectionTopics.map(card => card.text).join('\n')
    Object.assign(result.config, topicSearchConfig(result.collectionTopics, result.config.semantic_filter && result.config.semantic_rule === 'scene'))
  } catch { /* Invalid or unavailable storage must not prevent editing. */ }
  return result
}

export function saveConfig(config: CrawlerConfig, keywordText: string, collectionTopics: TopicCard[]) {
  try {
    const { cookies: _cookies, semantic_api_key: _key, ...saved } = config
    localStorage.setItem(KEY, JSON.stringify({ version: 4, config: { ...saved, save_option: 'excel' }, keywordText, collectionTopics }))
  } catch { /* Storage can be disabled or full; keep settings in memory. */ }
}
