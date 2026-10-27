import type { CrawlerConfig } from '@/types/crawler'

export function publicationRangeError(config: Pick<CrawlerConfig, 'publish_time_range' | 'publish_start_date' | 'publish_end_date'>): string | null {
  if (config.publish_time_range !== 'custom') return null
  const start = config.publish_start_date, end = config.publish_end_date
  if (!start || !end) return 'required'
  const valid = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
  if (!valid(start) || !valid(end) || end === '9999-12-31') return 'invalid'
  return start > end ? 'order' : null
}
