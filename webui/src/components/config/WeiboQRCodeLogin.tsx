import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Loader2, QrCode, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { crawlerApi } from '@/lib/api'
import refreshIcon from '@/assets/config/refresh.svg'

export function WeiboQRCodeLogin({ platform = 'wb', loginEnvironment = 'auto', disabled, onReady, compact = false }: { platform?: 'wb' | 'xhs'; loginEnvironment?: 'auto' | 'local' | 'server'; disabled: boolean; onReady: (ready: boolean) => void; compact?: boolean }) {
  const { t: translate } = useTranslation('config')
  const t = (key: string, options?: Record<string, unknown>) => translate(platform === 'xhs' ? key.replace('qrLogin.', 'xhsQrLogin.') : key, options || {})
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['qrLogin', platform], queryFn: async () => (await crawlerApi.getQRLogin(platform)).data,
    refetchInterval: 1500, retry: 1 })
  const login = query.data
  const start = useMutation({ mutationFn: async (refresh: boolean) => (await crawlerApi.startQRLogin(platform, refresh, loginEnvironment)).data,
    onSuccess: (state) => client.setQueryData(['qrLogin', platform], state) })
  const cancel = useMutation({ mutationFn: async () => (await crawlerApi.cancelQRLogin(platform)).data,
    onSuccess: (state) => client.setQueryData(['qrLogin', platform], state) })
  const authenticated = login?.status === 'authenticated' && !!login.saved_session
  const qrImage = login?.status === 'waiting' ? login.qr_image : null
  useEffect(() => { onReady(authenticated && !login?.busy) }, [authenticated, login?.busy, onReady])
  const pending = start.isPending || cancel.isPending
  const desktopUrl = new URL('/vnc.html', typeof window === 'undefined' ? 'http://localhost' : window.location.href)
  desktopUrl.port = String(login?.desktop_port || 6080)
  desktopUrl.search = 'autoconnect=true&resize=scale'
  const seconds = login?.expires_at ? Math.max(0, Math.ceil(login.expires_at - Date.now() / 1000)) : 0
  const refresh = authenticated || !!qrImage || ['expired', 'error', 'verification_required'].includes(login?.status || '')
  return <div className={compact ? 'config-qr-login' : 'space-y-3 rounded-lg border border-cyber-border-subtle bg-cyber-bg-tertiary/30 p-3'} aria-label={t('qrLogin.title')} data-authenticated={authenticated ? 'true' : undefined}>
    {compact && !authenticated && <div className="config-qr-placeholder">{qrImage ? <img src={qrImage} alt={t('qrLogin.imageAlt')} /> : <><span>{t('qrLogin.placeholder')}</span></>}</div>}
    <div className={compact ? 'config-qr-info' : 'contents'}>
    <p className="text-xs font-semibold text-cyber-text-primary">{t('qrLogin.title')}</p>
    <p className="text-xs leading-5 text-cyber-text-secondary" role="status">
      {query.isError ? t('qrLogin.unavailable') : login?.local_browser && login.busy && login.status === 'verification_required'
        ? t('qrLogin.localVerification') : login?.desktop_available && login.status === 'verification_required'
        ? '需要人工验证，当前登录窗口已保留，请打开登录浏览器处理。'
        : t(`qrLogin.status.${login?.status || 'idle'}`)}
    </p>
    {qrImage && <div className="space-y-2">{!compact && <img src={qrImage} alt={t('qrLogin.imageAlt')} className="mx-auto h-52 w-52 rounded-md bg-white p-2" />}<p className="text-xs text-cyber-text-secondary">{login?.local_browser ? t('qrLogin.interactiveExpires', { seconds }) : login?.desktop_available ? `登录窗口还可操作 ${seconds} 秒；二维码有效期以官方页面为准。` : t('qrLogin.expires', { seconds })}</p></div>}
    {login?.status === 'loading' || login?.status === 'checking' ? <Loader2 className="h-5 w-5 animate-spin text-cyber-neon-cyan" /> : null}
    {login?.reason && !(login.desktop_available && login.reason === 'login_verification_required') && <p className="text-xs leading-5 text-red-600" role="alert">{t(`qrLogin.reasons.${login.reason}`, { defaultValue: t('qrLogin.unavailable') })}</p>}
    {!!login?.saved_session && login.status !== 'authenticated' && <p className="text-xs text-cyber-text-secondary">{t('qrLogin.saved')}</p>}
    {login?.desktop_available && login.busy && <div className="space-y-2">
      <a href={desktopUrl.href} target="_blank" rel="noopener noreferrer" className="inline-flex rounded-md border px-3 py-2 text-sm text-cyan-700">打开登录浏览器</a>
      <p className="text-xs leading-5 text-cyber-text-secondary">输入部署时设置的浏览器密码。在窗口中扫码或完成验证；成功后自动保存登录状态。会话最多保留 10 分钟，可随时取消。</p>
    </div>}
    <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" disabled={disabled || pending || login?.status === 'loading' || login?.status === 'checking'} onClick={() => { cancel.reset(); start.mutate(refresh) }}>
      {refresh ? (compact ? <img src={refreshIcon} alt="" className="h-4 w-4" /> : <RefreshCw className="h-4 w-4" />) : <QrCode className="h-4 w-4" />}{t(refresh ? 'qrLogin.refresh' : 'qrLogin.start')}
    </Button>{login?.busy && <Button type="button" size="sm" variant="ghost" disabled={pending} onClick={() => { start.reset(); cancel.mutate() }}>{t('qrLogin.cancel')}</Button>}</div>
    {(start.isError || cancel.isError) && <p className="text-xs text-red-600" role="alert">{t('qrLogin.actionFailed')}</p>}
    <p className="text-xs leading-5 text-cyber-text-muted">{t(login?.local_browser ? 'qrLogin.localHint' : 'qrLogin.hint')}</p>
    </div>
  </div>
}
