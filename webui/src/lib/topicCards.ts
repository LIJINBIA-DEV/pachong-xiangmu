import { keywordSearchError } from './keywordSearches'

export interface TopicCard { text: string; evaluation: string }
export const cleanTopic = (value: string) => value.trim().replace(/\s+/g, ' ')
export function topicFromText(text: string): TopicCard {
  return { text, evaluation: '' }
}
export function topicSearch(card: TopicCard, scene: boolean) {
  return scene ? [card.evaluation, card.text].map(cleanTopic).filter(Boolean).join(' ') : cleanTopic(card.text)
}
export function topicSearchConfig(cards: TopicCard[], scene: boolean) {
  return {
    keywords: cards.map(card => topicSearch(card, scene)).filter(Boolean).join(','),
    keyword_pairs: cards.filter(card => topicSearch(card, scene)).map((card): [string, string] =>
      scene ? [cleanTopic(card.evaluation), cleanTopic(card.text)] : [cleanTopic(card.text), '']),
  }
}
export function topicCardError(card: TopicCard, scene: boolean): string | null {
  const text = topicSearch(card, scene)
  if (!text) return 'empty'
  if (!card.text.trim()) return 'empty'
  if (scene && !card.evaluation.trim()) return 'evaluation'
  return keywordSearchError(text, 'topic')?.reason ?? null
}
export function topicsError(cards: TopicCard[], scene: boolean): string | null {
  if (!cards.length) return 'empty'
  if (cards.length > 10000) return 'limit'
  const seen = new Set<string>()
  for (const card of cards) {
    const error = topicCardError(card, scene)
    if (error) return error
    const query = topicSearch(card, scene)
    if (seen.has(query)) return 'duplicate'
    seen.add(query)
  }
  return null
}
