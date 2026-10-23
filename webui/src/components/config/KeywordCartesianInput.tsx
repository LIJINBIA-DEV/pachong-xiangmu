import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload, X } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { createKeywordCombinations, mergeKeywordTerms, parseKeywordGroup, parseKeywordTxt } from '@/lib/keywordCombinations'
import { Button } from '@/components/ui/button'
import type { KeywordGroups } from '@/lib/keywordCombinations'

interface KeywordCartesianInputProps {
  groups: KeywordGroups
  drafts: KeywordGroups
  onChange: (group: keyof KeywordGroups, value: string) => void
  onDraftChange: (group: keyof KeywordGroups, value: string) => void
  disabled: boolean
}

export function KeywordCartesianInput({ groups, drafts, onChange, onDraftChange, disabled }: KeywordCartesianInputProps) {
  const { t } = useTranslation('config')
  const combinations = useMemo(() => createKeywordCombinations(groups), [groups])
  const fields = ['first', 'second'] as const
  const hasPendingKeywords = fields.some((group) => drafts[group].trim())
  const [importing, setImporting] = useState<keyof KeywordGroups | null>(null)
  const [messages, setMessages] = useState<Partial<Record<keyof KeywordGroups, { error?: string; added?: number }>>>({})
  const latest = useRef({ groups, disabled })
  latest.current = { groups, disabled }

  const importTxt = async (group: keyof KeywordGroups, file?: File) => {
    if (!file || disabled || importing) return
    setImporting(group)
    try {
      if (!/\.txt$/i.test(file.name)) throw new Error('type')
      if (file.size > 1024 * 1024) throw new Error('size')
      const incoming = parseKeywordTxt(await file.arrayBuffer())
      if (latest.current.disabled) return
      const existing = parseKeywordGroup(latest.current.groups[group])
      const terms = mergeKeywordTerms(latest.current.groups[group], incoming)
      const other = parseKeywordGroup(latest.current.groups[group === 'first' ? 'second' : 'first']).length
      if (terms.length > 1000 || terms.length * other > 10000) throw new Error('limit')
      onChange(group, terms.join(','))
      setMessages((previous) => ({ ...previous, [group]: { added: terms.length - existing.length } }))
    } catch (error) {
      const code = error instanceof Error && ['type', 'size', 'format', 'empty', 'limit'].includes(error.message) ? error.message : 'read'
      setMessages((previous) => ({ ...previous, [group]: { error: code } }))
    } finally { setImporting(null) }
  }

  const addKeywords = (group: keyof KeywordGroups) => {
    const terms = [...new Set([...parseKeywordGroup(groups[group]), ...parseKeywordGroup(drafts[group])])]
    onChange(group, terms.join(','))
    onDraftChange(group, '')
  }

  return (
    <div className="space-y-3">
      <p id="keyword-groups-hint" className="text-xs text-cyber-text-secondary leading-relaxed">
        {t('field.keywordGroupsHint')}
      </p>
      {fields.map((group) => (
        <div key={group} className="space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <Label htmlFor={`keyword-group-${group}`} className="text-xs text-cyber-text-secondary font-mono">
              {t(`field.keywordGroup.${group}`)}
            </Label>
            <div className="flex items-center gap-2"><span className="text-xs text-cyber-text-secondary">
              {t('field.keywordCount', { count: parseKeywordGroup(groups[group]).length })}
            </span>
              <Button type="button" variant="outline" size="sm" className="h-7 px-2 text-xs" disabled={disabled || !!importing} onClick={() => document.getElementById(`keyword-txt-${group}`)?.click()} aria-label={t('field.importTxtFor', { group: t(`field.keywordGroup.${group}`) })}><Upload className="h-3.5 w-3.5" />{t(importing === group ? 'field.importingTxt' : 'field.importTxt')}</Button>
              <input id={`keyword-txt-${group}`} type="file" accept=".txt,text/plain" className="hidden" disabled={disabled || !!importing} onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; void importTxt(group, file) }} />
            </div>
          </div>
          <Input
            id={`keyword-group-${group}`}
            aria-describedby="keyword-groups-hint keyword-combinations-status"
            value={drafts[group]}
            onChange={(event) => onDraftChange(group, event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.nativeEvent.isComposing && event.keyCode !== 229) {
                event.preventDefault()
                addKeywords(group)
              }
            }}
            onPaste={(event) => {
              const text = event.clipboardData.getData('text')
              if (/[\r\n]/.test(text)) {
                event.preventDefault()
                const input = event.currentTarget
                const start = input.selectionStart ?? input.value.length
                const end = input.selectionEnd ?? start
                onDraftChange(group, input.value.slice(0, start) + text.replace(/[\r\n]+/g, ',') + input.value.slice(end))
              }
            }}
            disabled={disabled}
            placeholder={t(`field.keywordGroupPlaceholder.${group}`)}
            className="h-9 text-xs placeholder:text-cyber-text-secondary"
          />
          {messages[group] && <p role={messages[group]?.error ? 'alert' : 'status'} className={messages[group]?.error ? 'text-xs leading-5 text-red-700 dark:text-red-300' : 'text-xs leading-5 text-cyber-text-secondary'}>{messages[group]?.error ? t(`field.importTxtErrors.${messages[group]?.error}`) : t('field.importTxtSuccess', { count: messages[group]?.added })}</p>}
          {parseKeywordGroup(groups[group]).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {parseKeywordGroup(groups[group]).map((term) => (
                <span key={term} className="inline-flex max-w-full items-center gap-1 rounded-md border border-cyber-neon-cyan/30 bg-cyber-neon-cyan/10 px-2 py-1 text-xs font-mono text-cyber-text-primary">
                  <span className="break-words min-w-0">{term}</span>
                  <button
                    type="button"
                    disabled={disabled}
                    aria-label={t('field.removeKeyword', { group: t(`field.keywordGroup.${group}`), keyword: term })}
                    onClick={() => onChange(group, parseKeywordGroup(groups[group]).filter((keyword) => keyword !== term).join(','))}
                    className="shrink-0 rounded-sm p-0.5 text-cyber-text-secondary hover:text-cyber-neon-pink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-neon-cyan/50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <X className="h-3 w-3" aria-hidden="true" />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
      <div className="space-y-2 border-t border-cyber-border-subtle pt-3">
        <p id="keyword-combinations-status" role="status" className="text-xs text-cyber-text-secondary leading-relaxed">
          {hasPendingKeywords
            ? t('field.keywordDraftPending')
            : combinations.length > 0
            ? t('field.combinationCount', { count: combinations.length })
            : t('field.keywordGroupsRequired')}
        </p>
        {combinations.length > 0 && (
          <details>
            <summary className="cursor-pointer text-xs text-cyber-text-primary rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-neon-cyan/50">
              {t('field.combinationPreview')}
            </summary>
            <ol className="mt-2 max-h-36 overflow-y-auto list-decimal pl-6 space-y-1 text-xs text-cyber-text-secondary">
              {combinations.map((combination) => <li key={combination} className="break-words">{combination}</li>)}
            </ol>
          </details>
        )}
      </div>
    </div>
  )
}
