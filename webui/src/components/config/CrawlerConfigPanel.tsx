import { useId, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CircleHelp } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Button } from '@/components/ui/button'
import { useCrawlerStore } from '@/store/crawlerStore'
import { crawlerApi, type SemanticKeyCheckResult } from '@/lib/api'
import { usePlatforms, useConfigOptions, useStartCrawler, useStopCrawler } from '@/hooks/useCrawler'
import { topicsError } from '@/lib/topicCards'
import { publicationRangeError } from '@/lib/publicationRange'
import { ParsedIdList } from './ParsedIdList'
import { KeywordSearchInput } from './KeywordSearchInput'
import { JevProxySettings } from './JevProxySettings'
import { WeiboQRCodeLogin } from './WeiboQRCodeLogin'
import { ConfigHelpDialog } from './ConfigHelpDialog'
import messageIcon from '@/assets/config/message.svg'
import imageIcon from '@/assets/config/image.svg'
import { CollectionProgressBar } from './CollectionProgressBar'
import './CrawlerConfigPanel.css'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="config-field"><span>{label}</span>{children}</label>
}
function ConfigSelect({ value, onChange, disabled, items, label }: {
  value: string; onChange: (value: string) => void; disabled: boolean
  items: { value: string; label: string; description?: string }[]; label: string
}) {
  return <Select value={value} onValueChange={onChange} disabled={disabled}>
    <SelectTrigger aria-label={label}><SelectValue placeholder={label} /></SelectTrigger>
    <SelectContent>{items.map((item) => <SelectItem key={item.value} value={item.value} title={item.description}>{item.label}</SelectItem>)}</SelectContent>
  </Select>
}
function Choice({ label, checked, onChange, disabled, icon }: {
  label: string; checked: boolean; onChange: (value: boolean) => void; disabled: boolean; icon?: string
}) {
  const id = useId()
  return <div className="config-choice"><Checkbox id={id} checked={checked} disabled={disabled} onCheckedChange={(value) => onChange(value === true)} aria-label={label} />
    <label htmlFor={id}>{icon && <img src={icon} alt="" />}<span>{label}</span></label></div>
}

export function CrawlerConfigPanel({ active = true }: { active?: boolean }) {
  const { t } = useTranslation('config')
  const { t: td } = useTranslation('data')
  const modeHelpId = useId()
  const storedConfig = useCrawlerStore((state) => state.config)
  const config = { ...storedConfig, save_option: 'excel', start_page: 1 }
  const updateConfig = useCrawlerStore((state) => state.updateConfig)
  const status = useCrawlerStore((state) => state.status)
  const collectionTopics = useCrawlerStore((state) => state.collectionTopics)
  const updateCollectionTopics = useCrawlerStore((state) => state.updateCollectionTopics)
  const [semanticApiKey, setSemanticApiKey] = useState('')
  const keyClient = useQueryClient()
  const semanticSettings = useQuery({ queryKey: ['semanticKeySettings'], queryFn: async () => (await crawlerApi.getSemanticSettings()).data, enabled: active, retry: 1 })
  const saveKey = useMutation({ mutationFn: async (input: { api_key?: string; clear_key?: boolean }) => (await crawlerApi.saveSemanticSettings(input)).data,
    onSuccess: data => { keyClient.setQueryData(['semanticKeySettings'], data); setSemanticApiKey(''); setSemanticKeyCheck(null); void keyClient.invalidateQueries({ queryKey: ['supplement'] }) } })
  async function persistSemanticKey(clear = false) {
    try { await saveKey.mutateAsync(clear ? { clear_key: true } : { api_key: semanticApiKey.trim() }); return true }
    catch { return false }
  }
  const [isTestingSemanticKey, setIsTestingSemanticKey] = useState(false)
  const [semanticKeyCheck, setSemanticKeyCheck] = useState<SemanticKeyCheckResult | null>(null)
  const [qrLoginReady, setQRLoginReady] = useState(false)
  const [help, setHelp] = useState<'config' | 'rules' | null>(null)
  const { data: platforms } = usePlatforms()
  const { data: options } = useConfigOptions()
  const { mutate: startCrawler, isPending: isStarting } = useStartCrawler()
  const { mutate: stopCrawler, isPending: isStopping } = useStopCrawler()
  const isDisabled = isStarting || status === 'running' || status === 'stopping'
  const isBusy = isStarting || isStopping || status === 'stopping'
  const loginEnvironment = config.login_environment && config.login_environment !== 'auto' ? config.login_environment : (options?.default_login_environment || (options?.web_qrcode_login ? 'server' : 'local'))
  const unavailableLocal = loginEnvironment === 'local' && options?.local_login_available === false
  const webQRLogin = ['wb', 'xhs'].includes(config.platform) && config.login_type === 'qrcode'
  const loginPending = !options || unavailableLocal || (webQRLogin && !qrLoginReady) || (loginEnvironment === 'server' && config.login_type === 'qrcode' && !['wb', 'xhs'].includes(config.platform))
  const evaluationOnly = !!config.semantic_filter && config.semantic_rule === 'scene'
  const missingKeywords = config.crawler_type === 'search' && !!topicsError(collectionTopics, evaluationOnly)
  const invalidNoteCount = config.crawler_type === 'search' && (config.max_notes_count === null || !Number.isInteger(config.max_notes_count) || config.max_notes_count < 1 || config.max_notes_count > 10000)
  const invalidTimeRange = config.crawler_type === 'search' ? publicationRangeError(config) : null
  const semanticSupported = config.crawler_type === 'search' && (config.platform === 'wb' || config.platform === 'xhs')
  const semanticCommentSampling = semanticSupported && config.semantic_filter
  async function handleStart() {
    if (saveKey.isPending || isTestingSemanticKey || isBusy || isDisabled || missingKeywords || invalidNoteCount || invalidTimeRange || loginPending) return
    if (semanticSupported && config.semantic_filter && !config.semantic_model.startsWith('semif') && semanticApiKey.trim() && !await persistSemanticKey()) return
    startCrawler({ ...config, login_environment: loginEnvironment, headless: loginEnvironment === 'server', max_comments_count: semanticCommentSampling ? 5 : undefined,
      publish_time_range: config.crawler_type === 'search' ? config.publish_time_range : 'all',
      publish_start_date: config.crawler_type === 'search' && config.publish_time_range === 'custom' ? config.publish_start_date : undefined,
      publish_end_date: config.crawler_type === 'search' && config.publish_time_range === 'custom' ? config.publish_end_date : undefined,
      enable_sub_comments: !semanticCommentSampling && config.enable_comments && config.enable_sub_comments,
      semantic_filter: semanticSupported && config.semantic_filter,
      semantic_api_key: undefined })
  }
  async function handleTestSemanticKey() {
    if (isTestingSemanticKey || isDisabled || saveKey.isPending) return
    setIsTestingSemanticKey(true); setSemanticKeyCheck(null)
    try {
      const result = (await crawlerApi.checkSemanticKey(semanticApiKey.trim(), config.semantic_model)).data
      if (result.ok && semanticApiKey.trim()) await persistSemanticKey()
      setSemanticKeyCheck(result)
    }
    catch { setSemanticKeyCheck({ ok: false, reason: 'backend_unreachable' }) }
    finally { setIsTestingSemanticKey(false) }
  }
  const semanticLocked = isDisabled || !semanticSupported || !config.semantic_filter
  return <div className="config-panel">
    <div className="config-grid">
      <section className="config-card config-target">
        <h2>{t('section.targetMatrix.title')}</h2>
        <div className="config-target-fields">
          <Field label={t('field.platform')}><ConfigSelect label={t('field.platform')} value={config.platform} disabled={isDisabled}
            items={(platforms?.filter((item) => ['wb', 'xhs'].includes(item.value)) || [{ value: 'wb', label: '微博' }, { value: 'xhs', label: '小红书' }]).map(item => ({ ...item, label: td(`file.platforms.${item.value}`, { defaultValue: item.label }) }))}
            onChange={(value) => { setQRLoginReady(false); if (webQRLogin) void crawlerApi.cancelQRLogin(config.platform as 'wb' | 'xhs').catch(() => undefined); updateConfig({ platform: value, semantic_filter: ['wb', 'xhs'].includes(value) && config.semantic_filter }) }} /></Field>
          <div className="config-field config-crawl-mode">
            <div className="config-mode-heading"><span>{t('field.crawlType')}</span><div className="config-mode-help">
              <button type="button" aria-label={t('crawlModes.help')} aria-describedby={modeHelpId}><CircleHelp size={16} aria-hidden="true" /></button>
              <div id={modeHelpId} role="tooltip" className="config-mode-tooltip">{['search', 'detail', 'creator'].map(mode => <p key={mode}><strong>{t(`crawlModes.${mode}.label`)}</strong><span>{t(`crawlModes.${mode}.description`)}</span></p>)}</div>
            </div></div>
            <ConfigSelect label={t('field.crawlType')} value={config.crawler_type} disabled={isDisabled}
              items={(options?.crawler_types || ['search', 'detail', 'creator'].map(value => ({ value, label: value }))).map(item => ({ ...item, label: t(`crawlModes.${item.value}.label`, { defaultValue: item.label }), description: t(`crawlModes.${item.value}.description`) }))}
              onChange={(value) => updateConfig({ crawler_type: value, semantic_filter: value === 'search' && config.semantic_filter })} />
          </div>
          <Field label={t('field.maxNotesCount')}><Input type="number" min={1} max={10000} step={1} aria-label={t('field.maxNotesCount')} aria-invalid={invalidNoteCount}
            value={config.max_notes_count ?? ''} onChange={(event) => updateConfig({ max_notes_count: event.target.value === '' ? null : Number(event.target.value) })} disabled={isDisabled || config.crawler_type !== 'search'} /></Field>
        </div>
        {config.crawler_type === 'search' && <section className="config-publication-range" aria-label={t('publication.label')}>
          <Field label={t('publication.label')}><ConfigSelect label={t('publication.label')} value={config.publish_time_range} disabled={isDisabled}
            items={(['all', 'week', 'day', 'month', 'custom'] as const).map((value) => ({ value, label: t(`publication.options.${value}`) }))}
            onChange={(value) => updateConfig({ publish_time_range: value as typeof config.publish_time_range })} /></Field>
          <p className="config-option-hint">{t(config.publish_time_range === 'custom' ? 'publication.customHint' : 'publication.hint')}</p>
          {config.publish_time_range === 'custom' && <div className="config-publication-dates">
            <Field label={t('publication.start')}><Input type="date" aria-label={t('publication.start')} value={config.publish_start_date} max={config.publish_end_date || undefined} onChange={(event) => updateConfig({ publish_start_date: event.target.value })} disabled={isDisabled} required aria-invalid={!!invalidTimeRange} /></Field>
            <Field label={t('publication.end')}><Input type="date" aria-label={t('publication.end')} value={config.publish_end_date} min={config.publish_start_date || undefined} onChange={(event) => updateConfig({ publish_end_date: event.target.value })} disabled={isDisabled} required aria-invalid={!!invalidTimeRange} /></Field>
          </div>}
          {invalidTimeRange && <p role="alert" className="config-error">{t(`publication.errors.${invalidTimeRange}`)}</p>}
        </section>}
        {config.crawler_type === 'search' ? <KeywordSearchInput cards={collectionTopics} onChange={updateCollectionTopics} scene={evaluationOnly} target={config.max_notes_count} disabled={isDisabled} controls={<div className="topic-filter-settings">
          <div className="topic-filter-controls"><Choice label={t('field.semanticFilter')} checked={config.semantic_filter} disabled={isDisabled || !semanticSupported || !config.enable_comments}
            onChange={(value) => updateConfig({ semantic_filter: value })} />
            {config.semantic_filter && <Choice label={t('topics.evaluationOnly')} checked={evaluationOnly} disabled={semanticLocked}
              onChange={value => updateConfig({ semantic_rule: value ? 'scene' : 'topic' })} />}</div>
          <p className="config-option-hint">{t(!config.enable_comments ? 'topics.commentsRequired' : !config.semantic_filter ? 'topics.filterOffHint' : evaluationOnly ? 'topics.evaluationOnlyHint' : 'topics.filterHint')}</p>
        </div>} /> : <div className="config-id-input">
          <Field label={t(config.crawler_type === 'detail' ? 'field.specifiedIds' : 'field.creatorIds')}>
            <textarea value={config.crawler_type === 'detail' ? config.specified_ids : config.creator_ids} disabled={isDisabled}
              placeholder={t(`field.${config.crawler_type === 'detail' ? 'specifiedIds' : 'creatorIds'}Placeholder.${config.platform}`)}
              onChange={(event) => updateConfig(config.crawler_type === 'detail' ? { specified_ids: event.target.value } : { creator_ids: event.target.value })} />
          </Field><ParsedIdList value={config.crawler_type === 'detail' ? config.specified_ids : config.creator_ids} platform={config.platform} type={config.crawler_type === 'detail' ? 'detail' : 'creator'} disabled={isDisabled} />
          {config.platform === 'xhs' && <p className="config-error">{t('warning.xhsToken')}</p>}
        </div>}
      </section>
      <div className="config-settings-stack">
      <section className="config-card config-output">
        <div className="config-section-heading"><h2>{t('section.outputConfig.title')}</h2></div>
        <div className="config-output-fields">
          <Field label={t('field.saveFormat')}><ConfigSelect label={t('field.saveFormat')} value="excel" onChange={() => updateConfig({ save_option: 'excel' })} disabled={isDisabled} items={[{ value: 'excel', label: 'Excel File' }]} /></Field>
          <Field label={t('field.semanticModel')}><ConfigSelect label={t('field.semanticModel')} value={config.semantic_model} disabled={semanticLocked}
            items={options?.semantic_models || [{ value: 'jev-1.13.0', label: 'Jev 1.13 (TypeSafe API)' }, { value: 'openai-compatible', label: '通用大模型 (DeepSeek / 通义千问等)' }]} onChange={(value) => { updateConfig({ semantic_model: value }); setSemanticKeyCheck(null) }} /></Field>
        </div>
        <div className="config-semantic-key"><Field label={t('field.semanticApiKey')}><Input type="password" name="typesafe-api-key" value={semanticApiKey} autoComplete="off" spellCheck={false}
          disabled={semanticLocked || saveKey.isPending || isTestingSemanticKey || config.semantic_model.startsWith('semif')} placeholder={t(semanticSettings.data?.key_configured ? 'field.semanticKeySavedPlaceholder' : 'field.semanticApiKeyPlaceholder')}
          onChange={(event) => { setSemanticApiKey(event.target.value); setSemanticKeyCheck(null); saveKey.reset() }} /></Field>
          <Button type="button" variant="outline" onClick={() => { void handleTestSemanticKey() }} disabled={semanticLocked || saveKey.isPending || isTestingSemanticKey || config.semantic_model.startsWith('semif')}>{t(isTestingSemanticKey ? 'field.semanticKeyTesting' : 'field.semanticKeyTest')}</Button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2" aria-label={t('field.semanticKeyStorage')}>
          <Button type="button" size="sm" variant="outline" onClick={() => { void persistSemanticKey() }} disabled={isDisabled || saveKey.isPending || isTestingSemanticKey || !semanticApiKey.trim()}>{t(saveKey.isPending ? 'field.semanticKeySaving' : 'field.semanticKeySave')}</Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => { void persistSemanticKey(true) }} disabled={isDisabled || saveKey.isPending || isTestingSemanticKey || !semanticSettings.data?.key_configured}>{t('field.semanticKeyClear')}</Button>
          <p className="config-option-hint" role="status">{t(semanticApiKey.trim() ? 'field.semanticKeyUnsaved' : semanticSettings.data?.key_configured ? 'field.semanticKeySaved' : 'field.semanticKeyNotSaved')}</p>
          {saveKey.isError && <p role="alert" className="config-error">{t('field.semanticKeySaveFailed')}</p>}
          {semanticSettings.isError && <p role="alert" className="config-error">{t('field.semanticKeyReadFailed')}</p>}
        </div>
        <div className="config-semantic-status" aria-live="polite">
          <p>{t('field.targetCountHint')}</p>
          {semanticKeyCheck && <p role="status" className={semanticKeyCheck.ok ? 'config-success' : 'config-error'}>{t(`field.semanticKeyCheckResult.${semanticKeyCheck.reason}`, { status: semanticKeyCheck.http_status ?? '' })}</p>}
          {config.semantic_filter && config.semantic_model.startsWith('semif') && <p>{t('field.semanticLocalHint')}</p>}
        </div>
        {config.semantic_model.startsWith('jev') && <JevProxySettings apiKey={semanticApiKey} disabled={isDisabled} onRoutingChange={() => setSemanticKeyCheck(null)} />}
        <Button type="button" variant="outline" className="config-rules-button" onClick={() => setHelp('rules')}>{t('help.viewRules')}</Button>
      </section>
      <section className="config-card config-login">
        <div className="config-login-heading"><h2>{t('section.authMatrix.title')}</h2><span>{t('field.loginMethod')}</span>
          <ConfigSelect label={t('field.loginMethod')} value={config.login_type} disabled={isDisabled}
            items={options?.login_types.map((item) => ({ ...item, label: item.value === 'qrcode' ? t('qrLogin.method') : item.label })) || [{ value: 'qrcode', label: t('qrLogin.method') }, { value: 'cookie', label: 'Cookie' }]}
            onChange={(value) => { setQRLoginReady(false); if (webQRLogin && value !== 'qrcode') void crawlerApi.cancelQRLogin(config.platform as 'wb' | 'xhs').catch(() => undefined); updateConfig({ login_type: value }) }} />
          <button type="button" className="config-help-link" onClick={() => setHelp('config')}>{t('help.viewConfig')}</button></div>
        <div className="config-login-environment">
          <Field label={t('loginEnvironment.label')}><ConfigSelect label={t('loginEnvironment.label')} value={loginEnvironment} disabled={isDisabled || !options?.login_environment_selection}
            items={[{ value: 'local', label: t('loginEnvironment.local') }, { value: 'server', label: t('loginEnvironment.server') }]}
            onChange={(value) => {
              setQRLoginReady(false)
              if (webQRLogin) void crawlerApi.cancelQRLogin(config.platform as 'wb' | 'xhs').catch(() => undefined)
              updateConfig({ login_environment: value as 'local' | 'server', headless: value === 'server' })
            }} /></Field>
          <p>{t(unavailableLocal ? 'loginEnvironment.unavailable' : `loginEnvironment.${loginEnvironment}Hint`)}</p>
        </div>
        <p className="config-browser-mode">{t(loginEnvironment === 'server' ? 'collection.browserBackground' : 'collection.browserVisible')}</p>
        {webQRLogin ? <WeiboQRCodeLogin key={config.platform} platform={config.platform as 'wb' | 'xhs'} loginEnvironment={loginEnvironment} disabled={isDisabled} onReady={setQRLoginReady} compact /> : config.login_type === 'cookie' ? <div className="config-cookie">
          <Field label={t('field.cookies')}><textarea value={config.cookies} disabled={isDisabled} placeholder={t('field.cookiesPlaceholder')} onChange={(event) => updateConfig({ cookies: event.target.value })} /></Field>
          {['xhs', 'dy'].includes(config.platform) && <p className="config-error">{t('warning.cookieSlider')}</p>}
        </div> : <div className="config-local-login"><p>{t('loginEnvironment.localSteps')}</p></div>}
      </section>
      <section className="config-card config-images" aria-label={t('collection.title')}>
        <h2>{t('collection.title')}</h2>
        {isDisabled && <p className="config-option-hint" role="status">{t('collection.locked')}</p>}
        {!semanticCommentSampling && <section className="config-option-group" aria-labelledby="collection-comments-heading">
          <h3 id="collection-comments-heading">{t('collection.commentsTitle')}</h3>
          {!semanticCommentSampling && <p className="config-option-hint">{t('collection.commentsHint')}</p>}
          {!semanticCommentSampling && <div className="config-comment-options">
            <Choice label={t('collection.commentsToggle')} icon={messageIcon} checked={config.enable_comments} disabled={isDisabled} onChange={(value) => updateConfig({ enable_comments: value, enable_sub_comments: value && config.enable_sub_comments, semantic_filter: value && config.semantic_filter })} />
            {config.enable_comments ? <Choice label={t('collection.repliesToggle')} checked={config.enable_sub_comments} disabled={isDisabled} onChange={(value) => updateConfig({ enable_sub_comments: value })} />
              : <p className="config-option-hint">{t('collection.repliesUnavailable')}</p>}
          </div>}
          {!semanticCommentSampling && <p className="config-option-hint">{t(config.enable_comments ? 'collection.repliesHint' : 'collection.commentsOff')}</p>}
          {!semanticCommentSampling && config.enable_comments && <p className="config-option-hint">{t('collection.commentLimitDefault')}</p>}
        </section>}
        <section className="config-option-group" aria-labelledby="collection-media-heading">
          <h3 id="collection-media-heading">{t('collection.mediaTitle')}</h3>
          <Choice label={t('collection.mediaToggle')} icon={imageIcon} checked={config.enable_media} disabled={isDisabled} onChange={(value) => updateConfig({ enable_media: value })} />
          <p className="config-option-hint">{t(config.enable_media ? 'collection.mediaOn' : 'collection.mediaOff')}</p>
          <p className="config-option-hint">{t('collection.mediaCount')}</p>
        </section>
      </section>
      </div>
    </div>
    <CollectionProgressBar active={active} busy={isBusy || isDisabled} starting={isStarting} stopping={isStopping} onStart={handleStart} onStop={() => stopCrawler()}
      startDisabled={saveKey.isPending || isTestingSemanticKey || isBusy || missingKeywords || invalidNoteCount || !!invalidTimeRange || loginPending} />
    <ConfigHelpDialog kind={help} semanticRule={config.semantic_rule} onClose={() => setHelp(null)} />
  </div>
}
