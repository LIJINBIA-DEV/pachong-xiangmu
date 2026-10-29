import type { CrawlerConfig } from '@/types/crawler'
import { publicationRangeError } from './publicationRange'
import { topicsError, type TopicCard } from './topicCards'

export type StartSection = 'target' | 'output' | 'topics' | 'login'

export function firstIncompleteStartSection(config: CrawlerConfig, context: {
  topics: TopicCard[]
  keyAvailable: boolean
  loginReady: boolean
  models: readonly string[]
}): StartSection | null {
  const search = config.crawler_type === 'search'
  if (!['xhs', 'wb'].includes(config.platform) || !['search', 'detail', 'creator'].includes(config.crawler_type)
      || search && (!Number.isInteger(config.max_notes_count) || Number(config.max_notes_count) < 1
        || Number(config.max_notes_count) > 10000 || !['all', 'day', 'week', 'month', 'custom'].includes(config.publish_time_range)
        || publicationRangeError(config))) return 'target'
  if (config.save_option !== 'excel' || search && config.semantic_filter && (
    !context.models.includes(config.semantic_model) || !config.enable_comments
    || !config.semantic_model.startsWith('semif') && !context.keyAvailable)) return 'output'
  if (search ? topicsError(context.topics, config.semantic_filter && config.semantic_rule === 'scene')
      : !(config.crawler_type === 'detail' ? config.specified_ids : config.creator_ids).trim()) return 'topics'
  if (!context.loginReady || !['qrcode', 'cookie'].includes(config.login_type)
      || config.login_type === 'cookie' && !config.cookies.trim()) return 'login'
  return null
}
