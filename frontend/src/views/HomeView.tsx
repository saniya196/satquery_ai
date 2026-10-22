import React from 'react'
import type { HistorySummary, JobStatus } from '../types/analysis'
import type { NavView } from '../components/layout/Sidebar'

interface HomeViewProps {
  onNavigate: (view: NavView) => void
  recentQueries: HistorySummary[]
  onOpenQuery: (id: string) => void
  loadingHistory: boolean
}

const RECENT_QUERY_LIMIT = 5

const STATUS_LABELS: Record<JobStatus, string> = {
  completed: 'Completed',
  failed: 'Failed',
  processing: 'Processing',
  queued: 'Queued',
}

/** Makes an element with role="button" operable from the keyboard, as the ARIA pattern requires. */
function activateWithKeyboard(action: () => void) {
  return (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      action()
    }
  }
}

function formatTimestamp(created: string | undefined): string {
  if (!created) return ''
  const parsed = new Date(created)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export const HomeView: React.FC<HomeViewProps> = ({
  onNavigate,
  recentQueries,
  onOpenQuery,
  loadingHistory,
}) => {
  const recent = recentQueries.slice(0, RECENT_QUERY_LIMIT)

  return (
    <div className="home-dashboard-container">
      {/* The page title and subtitle live in the top bar; this section is the only
          entry point into analysis, with one card per imagery source. */}
      <section className="home-entry-section">
        <div className="home-section-heading">
          <h2>Start an analysis</h2>
          <p>Choose how to supply imagery, then ask your question in plain language.</p>
        </div>

        <div className="mode-entry-grid">
          <div
            className="mode-entry-card map-entry"
            role="button"
            tabIndex={0}
            onClick={() => onNavigate('map')}
            onKeyDown={activateWithKeyboard(() => onNavigate('map'))}
          >
            <div className="mode-card-icon map-icon-bg" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21" />
                <line x1="9" y1="3" x2="9" y2="18" />
                <line x1="15" y1="6" x2="15" y2="21" />
              </svg>
            </div>
            <div className="mode-card-content">
              <h3>Map Mode</h3>
              <p>Draw an area of interest and query Sentinel-2 L2A imagery</p>
            </div>
            <span className="mode-card-arrow" aria-hidden="true">→</span>
          </div>

          <div
            className="mode-entry-card upload-entry"
            role="button"
            tabIndex={0}
            onClick={() => onNavigate('upload')}
            onKeyDown={activateWithKeyboard(() => onNavigate('upload'))}
          >
            <div className="mode-card-icon upload-icon-bg" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </div>
            <div className="mode-card-content">
              <h3>Upload Mode</h3>
              <p>Run the same verified pipeline on your own GeoTIFF</p>
            </div>
            <span className="mode-card-arrow" aria-hidden="true">→</span>
          </div>
        </div>
      </section>

      {/* Quiet capability strip: no second set of entry cards, just links onward. */}
      <section className="home-capability-strip" aria-label="Platform capabilities">
        <div
          className="capability-item"
          role="button"
          tabIndex={0}
          onClick={() => onNavigate('multisensor')}
          onKeyDown={activateWithKeyboard(() => onNavigate('multisensor'))}
        >
          <span className="capability-label">Multi-sensor</span>
          <span className="capability-detail">Sentinel-2 analytics; Sentinel-1 SAR fusion is not yet available</span>
        </div>
        <div
          className="capability-item"
          role="button"
          tabIndex={0}
          onClick={() => onNavigate('benchmarks')}
          onKeyDown={activateWithKeyboard(() => onNavigate('benchmarks'))}
        >
          <span className="capability-label">Verified results</span>
          <span className="capability-detail">Evidence, confidence and execution trace on every analysis</span>
        </div>
      </section>

      <section className="recent-queries-card" aria-label="Recent queries">
        <div className="recent-queries-header">
          <h3>Recent queries</h3>
          <button type="button" className="view-all-link" onClick={() => onNavigate('history')}>
            View all →
          </button>
        </div>

        {loadingHistory ? (
          <div className="recent-queries-loading">
            <span className="home-loading-dot" aria-hidden="true" />
            <span>Loading recent activity…</span>
          </div>
        ) : recent.length === 0 ? (
          <div className="recent-queries-empty">
            <p>No analyses yet. Use Map Mode or Upload Mode above to run your first query.</p>
          </div>
        ) : (
          <div className="recent-queries-list">
            {recent.map((item) => (
              <div
                key={item.id}
                className="recent-query-row"
                role="button"
                tabIndex={0}
                title={item.query || undefined}
                onClick={() => onOpenQuery(item.id)}
                onKeyDown={activateWithKeyboard(() => onOpenQuery(item.id))}
              >
                <div className="query-row-main">
                  <span className="query-row-text">
                    {item.query || `Analysis (${item.operation || 'Index'})`}
                  </span>
                  <span className="query-row-date">{formatTimestamp(item.created)}</span>
                </div>
                <div className="query-row-status">
                  <span className={`status-badge-pill status-${item.status}`}>
                    {STATUS_LABELS[item.status] ?? item.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
