import { useId, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { parseSearchTxt } from '@/lib/keywordSearches'
import { topicCardError, topicFromText, topicSearch, topicsError, type TopicCard } from '@/lib/topicCards'
import uploadIcon from '@/assets/config/upload.svg'

export function KeywordSearchInput({ cards, onChange, disabled, scene, target, controls }: {
  cards: TopicCard[]; onChange: (cards: TopicCard[]) => void; disabled: boolean; scene: boolean; target: number | null; controls?: ReactNode
}) {
  const { t } = useTranslation('config')
  const id = useId()
  const input = useRef<HTMLInputElement>(null)
  const [importing, setImporting] = useState(false)
  const [focused, setFocused] = useState<number | null>(null)
  const locked = disabled || importing
  const error = topicsError(cards, scene)
  const update = (index: number, card: TopicCard) => onChange(cards.map((item, i) => i === index ? card : item))
  async function importFile(file?: File) {
    if (!file || locked) return
    setImporting(true)
    try {
      if (!/\.txt$/i.test(file.name)) throw new Error('type')
      if (file.size > 1024 * 1024) throw new Error('size')
      const incoming = parseSearchTxt(await file.arrayBuffer(), 'topic').map(topicFromText)
      const existing = cards.filter(card => topicSearch(card, scene))
      if (existing.length + incoming.length > 10000) throw new Error('limit')
      onChange([...existing, ...incoming])
      toast.success(t('field.searchImportSuccess', { count: incoming.length }))
    } catch (cause) {
      toast.error(t(`field.searchErrors.${cause instanceof Error ? cause.message : 'read'}`, { defaultValue: t('field.searchErrors.read') }))
    } finally {
      setImporting(false)
      if (input.current) input.current.value = ''
    }
  }
  return <section className="keyword-search-input topic-cards" aria-label={t('topics.title')}>
    <div className="keyword-search-heading">
      <h3>{t('topics.title')}</h3>
      <Button type="button" variant="outline" className="config-import" disabled={locked} onClick={() => input.current?.click()}>
        <img src={uploadIcon} alt="" />{t(importing ? 'field.importingTxt' : 'field.importTxt')}
      </Button>
      <input ref={input} type="file" accept=".txt,text/plain" hidden aria-label={t('field.importTxt')} onChange={event => { void importFile(event.target.files?.[0]) }} />
    </div>
    {controls}
    <p className="topic-intro">{t('topics.intro')}</p>
    <div className="topic-card-list">
      {cards.map((card, index) => {
        const problem = topicCardError(card, scene)
        const duplicate = !!topicSearch(card, scene) && cards.some((other, i) => i < index && topicSearch(other, scene) === topicSearch(card, scene))
        const visibleError = duplicate ? 'duplicate' : (card.text.trim() || card.evaluation.trim()) ? problem : null
        const hintId = `${id}-${index}-hint`, errorId = `${id}-${index}-error`
        const describedBy = [focused === index ? hintId : '', visibleError ? errorId : ''].filter(Boolean).join(' ') || undefined
        return <fieldset key={index} className="topic-card" onBlur={event => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(null)
        }}>
          <legend>{t('topics.card', { number: index + 1 })}</legend>
          <div className="topic-card-toolbar"><span>{t('topics.quota', { count: target ?? 0 })}</span>
            <button type="button" disabled={locked} aria-label={t('topics.remove', { number: index + 1 })} onClick={() => {
              setFocused(null); onChange(cards.length === 1 ? [topicFromText('')] : cards.filter((_, i) => i !== index))
            }}><Trash2 size={14} />{t('topics.delete')}</button>
          </div>
          <label className="topic-text-label">{t('topics.question')}<input value={card.text} disabled={locked} placeholder={t('topics.placeholder')} onFocus={() => setFocused(index)} onChange={event => update(index, { ...card, text: event.target.value })} aria-invalid={!!visibleError} aria-describedby={describedBy} /></label>
          {scene && <label className="topic-evaluation-field">{t('topics.evaluation')}<input value={card.evaluation} disabled={locked} placeholder={t('topics.evaluationPlaceholder')} onFocus={() => setFocused(index)} onChange={event => update(index, { ...card, evaluation: event.target.value })} aria-invalid={!!visibleError} aria-describedby={describedBy} /><span className="config-option-hint">{t('topics.evaluationHint')}</span></label>}
          {focused === index && <div id={hintId} className="topic-input-hint" role="note">
            <p>{t('topics.focusHint')}</p>
          </div>}
          {scene && topicSearch(card, scene) && <p className="topic-search-preview">{t('topics.searchPreview', { text: topicSearch(card, scene) })}</p>}
          {visibleError && <p id={errorId} className="config-error" role="alert">{t(`topics.errors.${visibleError}`, { defaultValue: t('topics.errors.format') })}</p>}
        </fieldset>
      })}
    </div>
    <Button type="button" variant="outline" className="topic-add-button" disabled={locked || cards.length >= 10000} onClick={() => onChange([...cards, topicFromText('')])}><Plus size={15} />{t('topics.add')}</Button>
    <div className="topic-task-summary" aria-live="polite">
      <strong>{t(error ? 'topics.summaryPending' : 'topics.summary', { count: cards.length, total: cards.length * (target ?? 0), target: target ?? 0 })}</strong>
      <p>{t('topics.summaryHint')}</p>
    </div>
  </section>
}
