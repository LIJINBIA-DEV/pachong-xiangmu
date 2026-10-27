import { useTranslation } from 'react-i18next'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import closeIcon from '@/assets/config/close.svg'
import { Button } from '@/components/ui/button'

export function ConfigHelpDialog({ kind, semanticRule, onClose }: { kind: 'rules' | 'config' | null; semanticRule?: 'scene' | 'topic'; onClose: () => void }) {
  const { t } = useTranslation('config')
  return <DialogPrimitive.Root open={!!kind} onOpenChange={(open) => { if (!open) onClose() }}>
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="config-modal-overlay" />
      <DialogPrimitive.Content className={`config-modal ${kind === 'config' ? 'config-modal-wide' : ''}`} aria-describedby="config-help-body">
        <header><DialogPrimitive.Title>{t(`help.${kind || 'rules'}`)}</DialogPrimitive.Title>
          <DialogPrimitive.Close aria-label={t('help.close')}><img src={closeIcon} alt="" /></DialogPrimitive.Close></header>
        <div id="config-help-body" className="config-help-body">
          <h3>{t('help.semantic')}</h3><p>{t(semanticRule === 'scene' ? 'topics.evaluationOnlyHint' : 'topics.filterHint')}</p><p>{t('field.targetCountHint')}</p>
          <h3>{t('help.budget')}</h3><p>{t('field.commentBudgetHint')}</p><p>{t('field.commentBudgetRange')}</p>
          {kind === 'config' && <><h3>{t('section.authMatrix.title')}</h3><p>{t('qrLogin.hint')}</p><h3>{t('help.media')}</h3><p>{t('field.downloadMediaHint')}</p><p>{t('field.headlessModeHint')}</p><p>{t('field.semanticApiKeyHint')}</p></>}
        </div>
        <footer><DialogPrimitive.Close asChild><Button className="config-primary">{t('help.ok')}</Button></DialogPrimitive.Close></footer>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  </DialogPrimitive.Root>
}
