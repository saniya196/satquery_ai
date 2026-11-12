import React, { useState } from 'react'
import { ONBOARDING_DISMISSED_KEY, useLanguage } from '../i18n'
import type { HistorySummary, JobStatus } from '../types/analysis'
import type { NavView } from '../components/layout/Sidebar'
import { LogoMark } from '../components/brand/Logo'

interface HomeViewProps {
  onNavigate: (view: NavView) => void
  onStartTask: (query: string, options?: { compareMode?: boolean }) => void
  recentQueries: HistorySummary[]
  onOpenQuery: (id: string) => void
  loadingHistory: boolean
}

const RECENT_QUERY_LIMIT = 5

function formatTimestamp(created: string | undefined): string {
  if (!created) return ''
  const parsed = new Date(created)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export const HomeView: React.FC<HomeViewProps> = ({
  onNavigate,
  onStartTask,
  recentQueries,
  onOpenQuery,
  loadingHistory,
}) => {
  const { t } = useLanguage()
  const [query, setQuery] = useState('')
  const [onboardingDismissed, setOnboardingDismissed] = useState(() => localStorage.getItem(ONBOARDING_DISMISSED_KEY) === '1')
  const recent = recentQueries.slice(0, RECENT_QUERY_LIMIT)

  const dismissOnboarding = () => {
    localStorage.setItem(ONBOARDING_DISMISSED_KEY, '1')
    setOnboardingDismissed(true)
  }

  const statusLabel = (status: JobStatus) => t(`status.${status}`, status)
  const submitQuery = (event: React.FormEvent) => {
    event.preventDefault()
    const trimmed = query.trim()
    if (trimmed) onStartTask(trimmed)
  }

  const tasks = [
    { title: t('task.greenery.title'), desc: t('task.greenery.desc'), query: t('task.greenery.query') },
    { title: t('task.water.title'), desc: t('task.water.desc'), query: t('task.water.query') },
    { title: t('task.builtup.title'), desc: t('task.builtup.desc'), query: t('task.builtup.query') },
    { title: t('task.compare.title'), desc: t('task.compare.desc'), query: t('task.compare.query'), compareMode: true },
    { title: t('task.change.title'), desc: t('task.change.desc'), query: t('task.change.query') },
  ]

  return (
    <div className="home-dashboard-container">
      {!onboardingDismissed && (
        <section className="home-onboarding-card" aria-label={t('onboarding.title')} style={{ border: '1px solid var(--border-soft)', borderRadius: 12, padding: 16, marginBottom: 16, background: 'var(--surface)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
            <div>
              <h2 style={{ margin: '0 0 8px', fontSize: 18 }}>{t('onboarding.title')}</h2>
              <ol style={{ margin: 0, paddingLeft: 20, display: 'grid', gap: 4 }}>
                <li>{t('onboarding.step1')}</li>
                <li>{t('onboarding.step2')}</li>
                <li>{t('onboarding.step3')}</li>
              </ol>
              <p style={{ margin: '8px 0 0', fontSize: 13, color: 'var(--muted)' }}>{t('onboarding.sampleNote')}</p>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button type="button" className="filter-btn" onClick={dismissOnboarding}>{t('common.skip')}</button>
              <button type="button" className="filter-btn active" onClick={dismissOnboarding}>{t('common.gotIt')}</button>
            </div>
          </div>
        </section>
      )}

      <section className="home-hero-section">
        <div className="home-hero-orbit" aria-hidden="true">
          <LogoMark size={380} />
        </div>
        <div className="home-hero-copy">
          <span className="home-eyebrow">{t('app.tagline')}</span>
          <h2>{t('home.heroTitle')}</h2>
          <p>{t('home.heroHelp')}</p>
        </div>
        <form className="home-query-composer" onSubmit={submitQuery}>
          <label htmlFor="home-query">{t('home.queryLabel')}</label>
          <div className="home-query-row">
            <input
              id="home-query"
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('home.queryPlaceholder')}
              aria-describedby="home-query-help"
            />
            <button type="submit" className="home-query-submit" disabled={!query.trim()}>
              {t('home.askButton')} <span aria-hidden="true">→</span>
            </button>
          </div>
          <span id="home-query-help" className="home-query-help">{t('home.queryHelp')}</span>
        </form>
        <div className="home-example-row" aria-label={t('home.examplesLabel')}>
          <span className="home-example-label">{t('home.examplesLabel')}</span>
          {tasks.slice(0, 4).map((task) => (
            <button key={task.title} type="button" className="home-example-chip" onClick={() => setQuery(task.query)}>
              {task.title}
            </button>
          ))}
        </div>
      </section>

      <section className="home-task-section">
        <div className="home-section-heading">
          <div><h2>{t('home.tasksHeading')}</h2></div>
          <p>{t('home.tasksHelp')}</p>
        </div>
        <div className="home-task-grid">
          {tasks.map((task) => (
            <button
              key={task.title}
              type="button"
              className="home-task-item"
              onClick={() => onStartTask(task.query, { compareMode: task.compareMode })}
            >
              <span className="home-task-title">{task.title}</span>
              <span className="home-task-desc">{task.desc}</span>
              <span className="home-task-arrow" aria-hidden="true">↗</span>
            </button>
          ))}
        </div>
      </section>

      <section className="home-start-section">
        <div className="home-section-heading">
          <div>
            <span className="home-section-kicker">{t('home.start')}</span>
            <h2>{t('home.startHeading')}</h2>
          </div>
          <p>{t('home.startHelp')}</p>
        </div>

        <div className="mode-entry-grid">
          <button type="button" className="mode-entry-card map-entry" onClick={() => onNavigate('explore')}>
            <span className="mode-card-icon map-icon-bg" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21" /><line x1="9" y1="3" x2="9" y2="18" /><line x1="15" y1="6" x2="15" y2="21" /></svg>
            </span>
            <span className="mode-card-content">
              <span className="mode-card-title" role="heading" aria-level={3}>{t('home.mapTitle')}</span>
              <span className="mode-card-description">{t('home.mapDesc')}</span>
            </span>
            <span className="mode-card-arrow" aria-hidden="true">→</span>
          </button>

          <button type="button" className="mode-entry-card upload-entry" onClick={() => onNavigate('upload')}>
            <span className="mode-card-icon upload-icon-bg" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>
            </span>
            <span className="mode-card-content">
              <span className="mode-card-title" role="heading" aria-level={3}>{t('home.uploadTitle')}</span>
              <span className="mode-card-description">{t('home.uploadDesc')}</span>
            </span>
            <span className="mode-card-arrow" aria-hidden="true">→</span>
          </button>
        </div>
      </section>

      <section className="home-capability-strip" aria-label="Platform capabilities">
        <button type="button" className="capability-item" onClick={() => onNavigate('multisensor')}>
          <span className="capability-label">{t('home.capMoreData')}</span>
          <span className="capability-detail">{t('home.capMoreDataDesc')}</span>
        </button>
        <button type="button" className="capability-item" onClick={() => onNavigate('benchmarks')}>
          <span className="capability-label">{t('home.capChecked')}</span>
          <span className="capability-detail">{t('home.capCheckedDesc')}</span>
        </button>
      </section>

      <section className="recent-queries-card" aria-label={t('home.recent')}>
        <div className="recent-queries-header">
          <h2>{t('home.recent')}</h2>
          <button type="button" className="view-all-link" onClick={() => onNavigate('history')}>{t('home.viewAll')}</button>
        </div>

        {loadingHistory ? (
          <div className="recent-queries-loading"><span className="home-loading-dot" aria-hidden="true" /><span>{t('home.loadingRecent')}</span></div>
        ) : recent.length === 0 ? (
          <div className="recent-queries-empty">
            <p><strong>{t('home.noAnalyses')}</strong> {t('home.noAnalysesHelp')}</p>
            <button type="button" className="view-all-link" onClick={() => onNavigate('explore')}>{t('home.openMap')}</button>
          </div>
        ) : (
          <div className="recent-queries-list">
            {recent.map((item) => (
              <button key={item.id} type="button" className="recent-query-row" title={item.query || undefined} onClick={() => onOpenQuery(item.id)}>
                <span className="query-row-main">
                  <span className="query-row-text">{item.query || `Analysis (${item.operation || 'Index'})`}</span>
                  <span className="query-row-date">{formatTimestamp(item.created)}</span>
                </span>
                <span className="query-row-status"><span className={`status-badge-pill status-${item.status}`}>{statusLabel(item.status)}</span></span>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
