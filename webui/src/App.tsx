import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Toaster } from 'sonner'
import { useCrawlerStatus } from '@/hooks/useCrawler'
import { MainContent } from '@/components/layout/MainContent'
import { CrawlerConfigPanel } from '@/components/config/CrawlerConfigPanel'
import { WorkspaceSidebar, workspacePages, type WorkspacePage } from '@/components/layout/WorkspaceSidebar'
import { DataManagementPage } from '@/components/data/DataManagementPage'
import { ManualReviewPage } from '@/components/data/ManualReviewPage'
import { CollectionLogsPage } from '@/components/data/CollectionLogsPage'
import { EnvironmentCheck, isEnvChecked } from '@/components/env/EnvironmentCheck'
import { LicenseDisclaimer, isLicenseAccepted } from '@/components/license/LicenseDisclaimer'
import { DashboardPage } from '@/components/dashboard/DashboardPage'

function App() {
  const { t } = useTranslation('workspace')
  useCrawlerStatus()
  const readPage = (): WorkspacePage => {
    const value = window.location.hash.slice(2) as WorkspacePage
    return workspacePages.includes(value) ? value : 'dashboard'
  }
  const [page, setPage] = useState<WorkspacePage>(readPage)
  const [reviewRequest, setReviewRequest] = useState<{ file: string; id: number }>()
  const [visited, setVisited] = useState<WorkspacePage[]>([page])
  useEffect(() => { setVisited((pages) => pages.includes(page) ? pages : [...pages, page]) }, [page])
  useEffect(() => {
    const onHash = () => {
      if (window.location.hash.startsWith('#/')) setPage(readPage())
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const navigate = (next: WorkspacePage) => { setPage(next); window.location.hash = `/${next}` }
  // Initialize by checking localStorage if license has been accepted
  const [licenseAccepted, setLicenseAccepted] = useState(() => isLicenseAccepted())
  // Initialize by checking localStorage if env check has passed
  const [envChecked, setEnvChecked] = useState(() => isEnvChecked())

  const handleEnvCheckComplete = () => {
    setEnvChecked(true)
  }

  const handleLicenseAccept = () => {
    setLicenseAccepted(true)
  }

  return (
    <div className="flex flex-col h-screen cyber-grid overflow-hidden relative">
      {/* License Disclaimer Modal - Shows on first use */}
      {!licenseAccepted && (
        <LicenseDisclaimer onAccept={handleLicenseAccept} />
      )}

      {/* Environment Check Modal - Shows after license accepted */}
      {licenseAccepted && !envChecked && (
        <EnvironmentCheck onCheckComplete={handleEnvCheckComplete} />
      )}

      {/* Main Area */}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <WorkspaceSidebar page={page} onNavigate={navigate} />
        <main className={`flex min-h-0 min-w-0 flex-1 flex-col bg-cyber-bg-primary p-4 md:p-6 ${page === 'config' ? 'config-workspace' : page === 'dashboard' ? 'dashboard-workspace' : ''}`}>
          {page !== 'review' && page !== 'dashboard' && <header className={`mb-5 shrink-0 ${page === 'config' ? 'config-page-heading' : ''}`}><h1 className="text-xl font-semibold text-cyber-text-primary">{t(`pages.${page}`)}</h1><p className="mt-1 text-sm leading-6 text-cyber-text-secondary">{t(`descriptions.${page}`)}</p></header>}
          {(page === 'dashboard' || visited.includes('dashboard')) && <div className={`${page === 'dashboard' ? 'flex' : 'hidden'} min-h-0 flex-1 flex-col`}><DashboardPage active={page === 'dashboard'} onReview={(file) => { if (file) setReviewRequest({ file, id: Date.now() }); navigate('review') }} /></div>}
          {/* Keep configuration drafts, credentials and log subscriptions alive across pages. */}
          <div className={`${page === 'config' ? 'flex' : 'hidden'} config-scroll min-h-0 flex-1 flex-col overflow-y-auto`}><CrawlerConfigPanel /></div>
          <div className={`${page === 'console' ? 'flex' : 'hidden'} min-h-0 flex-1 flex-col`}><MainContent /></div>
          {(page === 'data' || visited.includes('data')) && <div className={`${page === 'data' ? 'flex' : 'hidden'} min-h-0 flex-1 flex-col`}><DataManagementPage /></div>}
          {(page === 'review' || visited.includes('review')) && <div className={`${page === 'review' ? 'flex' : 'hidden'} min-h-0 flex-1 flex-col`}><ManualReviewPage fileRequest={reviewRequest} /></div>}
          {(page === 'logs' || visited.includes('logs')) && <div className={`${page === 'logs' ? 'flex' : 'hidden'} min-h-0 flex-1 flex-col`}><CollectionLogsPage active={page === 'logs'} /></div>}
        </main>
        </div>

      {/* Toast notifications - Theme-aware style */}
      <Toaster
        position="top-right"
        toastOptions={{
          className: 'glass-panel font-mono text-cyber-text-primary',
          style: {
            fontFamily: 'JetBrains Mono, monospace',
          },
        }}
      />
    </div>
  )
}

export default App
