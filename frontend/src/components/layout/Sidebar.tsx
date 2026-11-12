import React, { useEffect, useRef } from 'react'
import { useLanguage } from '../../i18n'
import { LogoMark } from '../brand/Logo'

export type NavView = 'home' | 'explore' | 'multisensor' | 'change' | 'upload' | 'history' | 'benchmarks' | 'settings'

interface SidebarProps {
  currentView: NavView
  onSelectView: (view: NavView) => void
  activeJobCount?: number
  open?: boolean
  onClose?: () => void
  /** When true, sidebar is always visible as a fixed left rail (desktop). When false, drawer overlay (mobile). */
  permanent?: boolean
  /** When true (permanent mode only), sidebar shows icons only. */
  collapsed?: boolean
  onToggleCollapse?: () => void
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  onSelectView,
  activeJobCount = 0,
  open = false,
  onClose,
  permanent = false,
  collapsed = false,
  onToggleCollapse,
}) => {
  const { t } = useLanguage()
  const closeButtonRef = useRef<HTMLButtonElement | null>(null)
  const collapseButtonRef = useRef<HTMLButtonElement | null>(null)

  // Only rendered as a drawer on narrow viewports; move focus into it once open.
  useEffect(() => {
    if (!open || permanent) return
    const frame = requestAnimationFrame(() => closeButtonRef.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [open, permanent])

  const navItems: { id: NavView; labelKey: string; icon: React.ReactNode }[] = [
    {
      id: 'home',
      labelKey: 'nav.home',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
          <polyline points="9 22 9 12 15 12 15 22" />
        </svg>
      ),
    },
    {
      id: 'explore',
      labelKey: 'nav.explore',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-4-4M11 8v6M8 11h6" />
        </svg>
      ),
    },
    {
      id: 'multisensor',
      labelKey: 'nav.multisensor',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
          <path d="M2 12h20" />
        </svg>
      ),
    },
    {
      id: 'change',
      labelKey: 'nav.change',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
        </svg>
      ),
    },
    {
      id: 'upload',
      labelKey: 'nav.upload',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
      ),
    },
    {
      id: 'history',
      labelKey: 'nav.history',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      ),
    },
    {
      id: 'benchmarks',
      labelKey: 'nav.benchmarks',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 20V10" />
          <path d="M12 20V4" />
          <path d="M6 20v-6" />
        </svg>
      ),
    },
    {
      id: 'settings',
      labelKey: 'nav.settings',
      icon: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      ),
    },
  ]

  return (
    <aside
      id="app-navigation"
      className={`nav-sidebar${permanent ? ' nav-sidebar-permanent' : ''}${collapsed ? ' nav-sidebar-collapsed' : ''}${open ? ' nav-sidebar-open' : ''}`}
      aria-label="Main Navigation"
    >
      {!permanent && (
        <button
          ref={closeButtonRef}
          type="button"
          className="nav-drawer-close"
          onClick={onClose}
          aria-label={t('nav.close')}
        >
          <span aria-hidden="true">✕</span>
        </button>
      )}

      <div className="nav-sidebar-brand" onClick={() => onSelectView('home')} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelectView('home') } }}>
        <div className="nav-brand-icon">
          <LogoMark size={26} title="SatQuery AI" />
        </div>
        {!collapsed && (
          <div className="nav-brand-text">
            <span className="nav-brand-title">SatQuery <span className="nav-brand-accent">AI</span></span>
            <span className="nav-brand-tagline">{t('app.tagline')}</span>
          </div>
        )}
        {permanent && (
          <button
            ref={collapseButtonRef}
            type="button"
            className="nav-collapse-toggle"
            onClick={onToggleCollapse}
            aria-label={collapsed ? t('nav.expand') : t('nav.collapse')}
            title={collapsed ? t('nav.expand') : t('nav.collapse')}
          >
            <span aria-hidden="true">{collapsed ? '›' : '‹'}</span>
          </button>
        )}
      </div>

      <nav className="nav-items-list">
        {navItems.map((item) => {
          const isActive = currentView === item.id
          return (
            <button
              key={item.id}
              type="button"
              className={`nav-item-button ${isActive ? 'nav-item-active' : ''}`}
              onClick={() => {
                onSelectView(item.id)
                if (!permanent) onClose?.()
              }}
              aria-current={isActive ? 'page' : undefined}
              title={collapsed ? t(item.labelKey) : undefined}
            >
              <span className="nav-item-icon">{item.icon}</span>
              {!collapsed && <span className="nav-item-label">{t(item.labelKey)}</span>}
              {item.id === 'explore' && activeJobCount > 0 && (
                <span className="nav-item-badge">{activeJobCount}</span>
              )}
            </button>
          )
        })}
      </nav>

      <div className="nav-sidebar-footer">
        <div className="nav-user-profile">
          <div className="user-avatar" title="SatQuery Operator">S</div>
          {!collapsed && (
            <div className="user-details">
              <span className="user-name">SIH 26167</span>
              <span className="user-role">Operator</span>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}
