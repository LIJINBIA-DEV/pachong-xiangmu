import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { keywordSearchError, parseSearchTxt, parseKeywordSearches } from '@/lib/keywordSearches'
import uploadIcon from '@/assets/config/upload.svg'

export function KeywordSearchInput({ value, onChange, disabled }: {
  value: string; onChange: (value: string) => void; disabled: boolean
}) {
  const { t } = useTranslation('config')
  const input = useRef<HTMLInputElement>(null)
  const [importing, setImporting] = useState(false)
  const error = value.trim() ? keywordSearchError(value) : null
  async function importFile(file?: File) {
    if (!file || disabled || importing) return
    setImporting(true)
    try {
      if (!/\.txt$/i.test(file.name)) throw new Error('type')
      if (file.size > 1024 * 1024) throw new Error('size')
      const rows = parseSearchTxt(await file.arrayBuffer())
      // Append exactly the imported rows, including duplicates, in their original order.
      if (parseKeywordSearches(value).length + rows.length > 10000) throw new Error('limit')
      onChange([value.trimEnd(), ...rows].filter(Boolean).join('\n'))
      toast.success(t('field.searchImportSuccess', { count: rows.length }))
    } catch (cause) {
      toast.error(t(`field.searchErrors.${cause instanceof Error ? cause.message : 'read'}`, { defaultValue: t('field.searchErrors.read') }))
    } finally {
      setImporting(false)
      if (input.current) input.current.value = ''
    }
  }
  return <div className="keyword-search-input">
    <div className="keyword-search-heading">
      <label htmlFor="keyword-searches">{t('field.searchKeywords')}</label>
      <Button type="button" variant="outline" className="config-import" disabled={disabled || importing} onClick={() => input.current?.click()}>
        <img src={uploadIcon} alt="" />{t(importing ? 'field.importingTxt' : 'field.importTxt')}
      </Button>
      <input ref={input} type="file" accept=".txt,text/plain" hidden aria-label={t('field.importTxt')} onChange={(event) => { void importFile(event.target.files?.[0]) }} />
    </div>
    <textarea id="keyword-searches" value={value} onChange={(event) => onChange(event.target.value)}
      disabled={disabled || importing} spellCheck={false} wrap="off"
      aria-invalid={!!error} aria-describedby={error ? 'keyword-search-error' : undefined}
      placeholder={t('field.searchPlaceholder')} />
    {error && <p id="keyword-search-error" role="alert" className="config-error">{t(`field.searchErrors.${error.reason}`, { line: error.line })}</p>}
  </div>
}
