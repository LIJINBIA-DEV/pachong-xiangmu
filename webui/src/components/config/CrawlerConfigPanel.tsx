import { useId, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Square } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Button } from '@/components/ui/button'
import { useCrawlerStore } from '@/store/crawlerStore'
import { crawlerApi, type SemanticKeyCheckResult } from '@/lib/api'
import { usePlatforms, useConfigOptions, useStartCrawler, useStopCrawler } from '@/hooks/useCrawler'
import { keywordSearchError } from '@/lib/keywordSearches'
import { ParsedIdList } from './ParsedIdList'
import { KeywordSearchInput } from './KeywordSearchInput'
import { ImageRecognitionSettings } from './ImageRecognitionSettings'
import { JevProxySettings } from './JevProxySettings'
import { WeiboQRCodeLogin } from './WeiboQRCodeLogin'
import { ConfigHelpDialog } from './ConfigHelpDialog'
import messageIcon from '@/assets/config/message.svg'
import imageIcon from '@/assets/config/image.svg'
import playIcon from '@/assets/config/play.svg'
import './CrawlerConfigPanel.css'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="config-field"><span>{label}</span>{children}</label>
}
function ConfigSelect({ value, onChange, disabled, items, label }: {
  value: string; onChange: (value: string) => void; disabled: boolean
  items: { value: string; label: string }[]; label: string
}) {
  return <Select value={value} onValueChange={onChange} disabled={disabled}>
    <SelectTrigger aria-label={label}><SelectValue placeholder={label} /></SelectTrigger>
    <SelectContent>{items.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent>
  </Select>
}
function Choice({ label, checked, onChange, disabled, icon }: {
  label: string; checked: boolean; onChange: (value: boolean) => void; disabled: boolean; icon?: string
}) {
  const id = useId()
  return <div className="config-choice"><Checkbox id={id} checked={checked} disabled={disabled} onCheckedChange={(value) => onChange(value === true)} aria-label={label} />
    <label htmlFor={id}>{icon && <img src={icon} alt="" />}<span>{label}</span></label></div>
}

export function CrawlerConfigPanel() {
  const { t } = useTranslation('config')
  const storedConfig = useCrawlerStore((state) => state.config)
  const config = { ...storedConfig, save_option: 'excel' }
  const updateConfig = useCrawlerStore((state) => state.updateConfig)
  const status = useCrawlerStore((state) => state.status)
  const keywordText = useCrawlerStore((state) => state.keywordText)
  const updateKeywordText = useCrawlerStore((state) => state.updateKeywordText)
  const [semanticApiKey, setSemanticApiKey] = useState('')
  const [isTestingSemanticKey, setIsTestingSemanticKey] = useState(false)
  const [semanticKeyCheck, setSemanticKeyCheck] = useState<SemanticKeyCheckResult | null>(null)
  const [qrLoginReady, setQRLoginReady] = useState(false)
  const [help, setHelp] = useState<'config' | 'rules' | null>(null)
  const { data: platforms } = usePlatforms()
  const { data: options } = useConfigOptions()
  const { mutate: startCrawler, isPending: isStarting } = useStartCrawler()
  const { mutate: stopCrawler, isPending: isStopping } = useStopCrawler()
  const isDisabled = isStarting || status === 'running' || status === 'stopping'
  const isRunning = status === 'running'
  const isBusy = isStarting || isStopping || status === 'stopping'
  const loginEnvironment = config.login_environment && config.login_environment !== 'auto' ? config.login_environment : (options?.default_login_environment || (options?.web_qrcode_login ? 'server' : 'local'))
  const unavailableLocal = loginEnvironment === 'local' && options?.local_login_available === false
  const webQRLogin = loginEnvironment === 'server' && ['wb', 'xhs'].includes(config.platform) && config.login_type === 'qrcode'
  const loginPending = !options || unavailableLocal || (loginEnvironment === 'server' && config.login_type === 'qrcode' && (!['wb', 'xhs'].includes(config.platform) || !qrLoginReady))
  const missingKeywords = config.crawler_type === 'search' && !!keywordSearchError(keywordText)
  const invalidNoteCount = config.crawler_type === 'search' && (config.max_notes_count === null || !Number.isInteger(config.max_notes_count) || config.max_notes_count < 1 || config.max_notes_count > 10000)
  const semanticSupported = config.crawler_type === 'search' && (config.platform === 'wb' || config.platform === 'xhs')
  const commentBudgetSupported = config.platform === 'wb' && semanticSupported && config.semantic_filter
  const invalidCommentBudget = commentBudgetSupported && (config.max_comments_count == null || !Number.isInteger(config.max_comments_count) || config.max_comments_count < 1 || config.max_comments_count > 10000)
  function handleStart() {
    if (isBusy || isDisabled || missingKeywords || invalidNoteCount || invalidCommentBudget || loginPending) return
    startCrawler({ ...config, login_environment: loginEnvironment, headless: loginEnvironment === 'server', max_comments_count: commentBudgetSupported ? config.max_comments_count : undefined,
      semantic_filter: semanticSupported && config.semantic_filter,
      semantic_api_key: semanticSupported && config.semantic_filter && config.semantic_model === 'jev-1.13.0' ? semanticApiKey.trim() : undefined })
  }
  async function handleTestSemanticKey() {
    if (isTestingSemanticKey || isDisabled) return
    setIsTestingSemanticKey(true); setSemanticKeyCheck(null)
    try { setSemanticKeyCheck((await crawlerApi.checkSemanticKey(semanticApiKey.trim(), config.semantic_model)).data) }
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
            items={platforms?.filter((item) => ['wb', 'xhs'].includes(item.value)) || [{ value: 'wb', label: 'Weibo' }, { value: 'xhs', label: '小红书' }]}
            onChange={(value) => { setQRLoginReady(false); if (webQRLogin) void crawlerApi.cancelQRLogin(config.platform as 'wb' | 'xhs').catch(() => undefined); updateConfig({ platform: value, semantic_filter: ['wb', 'xhs'].includes(value) && config.semantic_filter }) }} /></Field>
          <Field label={t('field.crawlType')}><ConfigSelect label={t('field.crawlType')} value={config.crawler_type} disabled={isDisabled}
            items={options?.crawler_types || [{ value: 'search', label: 'Search Mode' }]}
            onChange={(value) => updateConfig({ crawler_type: value, semantic_filter: value === 'search' && config.semantic_filter })} /></Field>
          <Field label={t('field.startPage')}><Input type="number" min={1} aria-label={t('field.startPage')} value={config.start_page} onChange={(event) => updateConfig({ start_page: parseInt(event.target.value) || 1 })} disabled={isDisabled} /></Field>
          <Field label={t('field.maxNotesCount')}><Input type="number" min={1} max={10000} step={1} aria-label={t('field.maxNotesCount')} aria-invalid={invalidNoteCount}
            value={config.max_notes_count ?? ''} onChange={(event) => updateConfig({ max_notes_count: event.target.value === '' ? null : Number(event.target.value) })} disabled={isDisabled || config.crawler_type !== 'search'} /></Field>
        </div>
        {config.crawler_type === 'search' ? <KeywordSearchInput value={keywordText} onChange={updateKeywordText} disabled={isDisabled} /> : <div className="config-id-input">
          <Field label={t(config.crawler_type === 'detail' ? 'field.specifiedIds' : 'field.creatorIds')}>
            <textarea value={config.crawler_type === 'detail' ? config.specified_ids : config.creator_ids} disabled={isDisabled}
              placeholder={t(`field.${config.crawler_type === 'detail' ? 'specifiedIds' : 'creatorIds'}Placeholder.${config.platform}`)}
              onChange={(event) => updateConfig(config.crawler_type === 'detail' ? { specified_ids: event.target.value } : { creator_ids: event.target.value })} />
          </Field><ParsedIdList value={config.crawler_type === 'detail' ? config.specified_ids : config.creator_ids} platform={config.platform} type={config.crawler_type === 'detail' ? 'detail' : 'creator'} disabled={isDisabled} />
          {config.platform === 'xhs' && <p className="config-error">{t('warning.xhsToken')}</p>}
        </div>}
      </section>
      <section className="config-card config-output">
        <div className="config-section-heading"><h2>{t('section.outputConfig.title')}</h2>
          <Choice label={t('field.semanticFilter')} checked={config.semantic_filter} disabled={isDisabled || !semanticSupported || !config.enable_comments}
            onChange={(value) => updateConfig({ semantic_filter: value })} /></div>
        <div className="config-output-fields">
          <Field label={t('field.saveFormat')}><ConfigSelect label={t('field.saveFormat')} value="excel" onChange={() => updateConfig({ save_option: 'excel' })} disabled={isDisabled} items={[{ value: 'excel', label: 'Excel File' }]} /></Field>
          <Field label={t('field.commentBudget')}><Input type="number" min={1} max={10000} step={1} aria-label={t('field.commentBudget')} value={config.max_comments_count ?? ''}
            onChange={(event) => updateConfig({ max_comments_count: event.target.value === '' ? null : Number(event.target.value) })} disabled={!commentBudgetSupported || isDisabled} aria-invalid={invalidCommentBudget} /></Field>
          <Field label={t('field.semanticModel')}><ConfigSelect label={t('field.semanticModel')} value={config.semantic_model} disabled={semanticLocked}
            items={options?.semantic_models || [{ value: 'jev-1.13.0', label: 'Jev 1.13 (TypeSafe API)' }]} onChange={(value) => { updateConfig({ semantic_model: value }); setSemanticKeyCheck(null) }} /></Field>
        </div>
        <div className="config-semantic-key"><Field label={t('field.semanticApiKey')}><Input type="password" name="typesafe-api-key" value={semanticApiKey} autoComplete="off" spellCheck={false}
          disabled={semanticLocked || config.semantic_model !== 'jev-1.13.0'} placeholder={t('field.semanticApiKeyPlaceholder')}
          onChange={(event) => { setSemanticApiKey(event.target.value); setSemanticKeyCheck(null) }} /></Field>
          <Button type="button" variant="outline" onClick={() => { void handleTestSemanticKey() }} disabled={semanticLocked || isTestingSemanticKey || config.semantic_model !== 'jev-1.13.0'}>{t(isTestingSemanticKey ? 'field.semanticKeyTesting' : 'field.semanticKeyTest')}</Button>
        </div>
        <div className="config-semantic-status" aria-live="polite">
          {invalidCommentBudget && <p className="config-error">{t('field.commentBudgetInvalid')}</p>}
          {semanticKeyCheck && <p role="status" className={semanticKeyCheck.ok ? 'config-success' : 'config-error'}>{t(`field.semanticKeyCheckResult.${semanticKeyCheck.reason}`, { status: semanticKeyCheck.http_status ?? '' })}</p>}
          {config.semantic_filter && config.semantic_model !== 'jev-1.13.0' && <p>{t('field.semanticLocalHint')}</p>}
        </div>
        <JevProxySettings apiKey={semanticApiKey} disabled={isDisabled} onRoutingChange={() => setSemanticKeyCheck(null)} />
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
        {webQRLogin ? <WeiboQRCodeLogin key={config.platform} platform={config.platform as 'wb' | 'xhs'} disabled={isDisabled} onReady={setQRLoginReady} compact /> : config.login_type === 'cookie' ? <div className="config-cookie">
          <Field label={t('field.cookies')}><textarea value={config.cookies} disabled={isDisabled} placeholder={t('field.cookiesPlaceholder')} onChange={(event) => updateConfig({ cookies: event.target.value })} /></Field>
          {['xhs', 'dy'].includes(config.platform) && <p className="config-error">{t('warning.cookieSlider')}</p>}
        </div> : <div className="config-local-login"><p>{t('loginEnvironment.localSteps')}</p></div>}
      </section>
      <section className="config-card config-images">
        <h2>{t('field.imageSettingsTitle')}</h2>
        <div className="config-media-options">
          <Choice label={t('field.commentExtraction')} icon={messageIcon} checked={config.enable_comments} disabled={isDisabled} onChange={(value) => updateConfig({ enable_comments: value, enable_sub_comments: value && config.enable_sub_comments, semantic_filter: value && config.semantic_filter })} />
          <Choice label={t('field.subComments')} checked={config.enable_sub_comments} disabled={isDisabled || !config.enable_comments} onChange={(value) => updateConfig({ enable_sub_comments: value })} />
          <Choice label={t('field.downloadMedia')} icon={imageIcon} checked={config.enable_media} disabled={isDisabled} onChange={(value) => updateConfig({ enable_media: value })} />
          <Choice label={t('field.headlessMode')} checked={loginEnvironment === 'server'} disabled={true} onChange={() => undefined} />
        </div>
        <div className="config-image-subject"><Choice label={t('field.imageSubject')} checked={config.image_subject_recognition} disabled={isDisabled || config.platform !== 'wb'} onChange={(value) => updateConfig({ image_subject_recognition: value })} /></div>
        {config.platform === 'wb' && <ImageRecognitionSettings compact disabled={isDisabled || !config.image_subject_recognition} />}
      </section>
    </div>
    <div className="config-actions"><Button type="button" onClick={isRunning ? () => stopCrawler() : handleStart}
      disabled={isRunning ? isBusy : isBusy || missingKeywords || invalidNoteCount || invalidCommentBudget || loginPending}
      className={isRunning ? 'config-stop' : 'config-primary'}>
      {isRunning ? <Square className="h-4 w-4" /> : <img src={playIcon} alt="" />}
      {t(isRunning ? (isStopping ? 'button.stopping' : 'button.terminate') : (isStarting ? 'button.initiating' : 'button.initiateScan'))}
    </Button></div>
    <ConfigHelpDialog kind={help} onClose={() => setHelp(null)} />
  </div>
}
