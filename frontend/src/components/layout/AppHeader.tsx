import React from 'react'
import { UI_LANGUAGES, useLanguage } from '../../i18n'
import { LogoMark } from '../brand/Logo'
import type { NavView } from './Sidebar'

interface AppHeaderProps {
  currentView: NavView
  activeJobId: string | null
  jobStatus?: string | null
  navOpen?: boolean
  onToggleNav?: () => void
  menuButtonRef?: React.RefObject<HTMLButtonElement | null>
}

const VIEW_KEY: Record<NavView, string> = {
  home: 'home',
  explore: 'explore',
  multisensor: 'multisensor',
  change: 'change',
  upload: 'upload',
  history: 'history',
  benchmarks: 'benchmarks',
  settings: 'settings',
}

export const AppHeader: React.FC<AppHeaderProps> = ({
  currentView,
  activeJobId,
  jobStatus,
  navOpen = false,
  onToggleNav,
  menuButtonRef,
}) => {
  const { t, lang, setLang } = useLanguage()
  const view = VIEW_KEY[currentView]
  const statusLabel = jobStatus ? t(`status.${jobStatus}`, jobStatus) : t('status.processing')

  return (
    <header className="app-topbar">
      <div className="topbar-left-group">
        <button
          ref={menuButtonRef}
          type="button"
          className="nav-menu-button"
          onClick={onToggleNav}
          aria-label={navOpen ? t('nav.close') : t('nav.menu')}
          aria-expanded={navOpen}
          aria-controls="app-navigation"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>

        <div className="topbar-title-block">
          <span className="topbar-brand-row">
            <LogoMark size={18} title="SatQuery AI" />
            <h1 className="topbar-page-title">{t(`header.${view}.title`)}</h1>
          </span>
          <span className="topbar-page-subtitle">{t(`header.${view}.subtitle`)}</span>
        </div>
      </div>

      <div className="topbar-actions-block">
        {activeJobId && (
          <div className="topbar-job-pill">
            <span className="live-pulse-dot" />
            <span className="job-pill-text">{t('header.job')} {activeJobId.slice(0, 8)}… ({statusLabel})</span>
          </div>
        )}

        <div className="topbar-status" title={t('header.provider')}>
          <span className="badge-dot active-dot" />
          <span>Earth Search</span>
        </div>
        <label className="topbar-language">
          <span className="visually-hidden">Language</span>
          <select value={lang} onChange={(event) => setLang(event.target.value as typeof lang)} aria-label="Language">
            {UI_LANGUAGES.map((language) => <option key={language.code} value={language.code}>{language.native}</option>)}
          </select>
        </label>
      </div>
    </header>
  )
}
