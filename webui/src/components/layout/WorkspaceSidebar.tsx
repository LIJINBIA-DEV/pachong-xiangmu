import configIcon from '@/assets/review/imgSvg.svg'
import consoleIcon from '@/assets/review/imgSvg1.svg'
import dataIcon from '@/assets/review/imgSvg2.svg'
import reviewIcon from '@/assets/review/imgSvg3.svg'
import logsIcon from '@/assets/review/imgSvg4.svg' 
import dashboardIcon from '@/assets/dashboard/navigation.svg'
import { useTranslation } from 'react-i18next'
import { useCrawlerStore } from '@/store/crawlerStore'

export type WorkspacePage = 'dashboard' | 'config' | 'console' | 'data' | 'review' | 'logs'
export const workspacePages: WorkspacePage[] = ['dashboard', 'config', 'console', 'data', 'review', 'logs']

// Navigation structure adapted from wangdaye-cli: Sidebar Nav Group (21st-12101).
export function WorkspaceSidebar({ page, onNavigate }: { page: WorkspacePage; onNavigate: (page: WorkspacePage) => void }) {
  const { t } = useTranslation('workspace')
  const status = useCrawlerStore((state) => state.status)
  const icons = { dashboard: dashboardIcon, config: configIcon, console: consoleIcon, data: dataIcon, review: reviewIcon, logs: logsIcon }
  return (
    <aside className={`shrink-0 border-b border-cyber-border-subtle bg-cyber-bg-panel md:w-52 md:border-b-0 md:border-r ${page === 'config' ? 'config-sidebar' : page === 'dashboard' ? 'dashboard-sidebar' : ''}`}>
      <div className="hidden px-5 pb-2 pt-6 text-sm font-semibold text-cyber-text-primary md:block">{t('workspace')}</div>
      <nav aria-label={t('navigation')} className="grid grid-cols-6 gap-1 p-2 md:flex md:flex-col md:gap-2 md:p-3">
        {workspacePages.map((item) => {
          const icon = icons[item]
          return <a key={item} href={`#/${item}`} onClick={(event) => { event.preventDefault(); onNavigate(item) }} aria-current={item === page ? 'page' : undefined}
            className={`flex min-h-12 flex-col items-center justify-center gap-1 rounded-lg px-2 py-2 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyber-neon-cyan md:flex-row md:justify-start md:gap-3 md:px-3 md:text-sm ${item === page ? 'bg-cyber-neon-cyan/10 font-semibold text-cyber-text-primary' : 'text-cyber-text-secondary hover:bg-cyber-bg-secondary hover:text-cyber-text-primary'}`}>
            <img src={icon} alt="" aria-hidden="true" className="shrink-0" /><span>{t(`pages.${item}`)}</span>
          </a>
        })}
      </nav>
      <div className="hidden border-t border-cyber-border-subtle px-5 py-4 text-xs leading-6 text-cyber-text-secondary md:block">
        <div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${status === 'running' ? 'bg-cyber-neon-green' : 'bg-cyber-text-secondary'}`} />{t(`status.${status}`)}</div>
        <p className="mt-2">{t('navigationHint')}</p>
      </div>
    </aside>
  )
}
