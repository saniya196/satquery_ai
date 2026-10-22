import React from 'react'
import type { HistorySummary } from '../types/analysis'
import type { NavView } from '../components/layout/Sidebar'

interface HomeViewProps {
  onNavigate: (view: NavView) => void
  recentQueries: HistorySummary[]
  onOpenQuery: (id: string) => void
  loadingHistory: boolean
}

export const HomeView: React.FC<HomeViewProps> = ({
  onNavigate,
  recentQueries,
  onOpenQuery,
  loadingHistory,
}) => {
  return (
    <div className="home-dashboard-container">
      {/* Welcome Card matching Reference Panel 1 */}
      <section className="welcome-section-card">
        <div className="welcome-header">
          <h2>Welcome to SatQuery AI</h2>
          <p>Analyze satellite imagery, ask questions in natural language, and get accurate, verifiable insights.</p>
        </div>

        <div className="mode-entry-grid">
          <div
            className="mode-entry-card map-entry"
            onClick={() => onNavigate('map')}
            role="button"
            tabIndex={0}
          >
            <div className="mode-card-icon map-icon-bg">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21" />
                <line x1="9" y1="3" x2="9" y2="18" />
                <line x1="15" y1="6" x2="15" y2="21" />
              </svg>
            </div>
            <div className="mode-card-content">
              <h3>Map Mode</h3>
              <p>Draw an area on the map and ask a question</p>
            </div>
            <span className="mode-card-arrow">→</span>
          </div>

          <div
            className="mode-entry-card upload-entry"
            onClick={() => onNavigate('upload')}
            role="button"
            tabIndex={0}
          >
            <div className="mode-card-icon upload-icon-bg">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </div>
            <div className="mode-card-content">
              <h3>Upload Mode</h3>
              <p>Upload GeoTIFF files for analysis</p>
            </div>
            <span className="mode-card-arrow">→</span>
          </div>
        </div>
      </section>

      {/* Feature Pillars Banner */}
      <section className="feature-pillars-grid">
        <div
          className="feature-pillar-card clickable-pillar"
          onClick={() => onNavigate('map')}
          role="button"
          tabIndex={0}
        >
          <div className="pillar-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
              <circle cx="12" cy="10" r="3" />
            </svg>
          </div>
          <div className="pillar-text">
            <strong>Map Mode</strong>
            <span>Draw area & ask in plain language</span>
          </div>
        </div>

        <div
          className="feature-pillar-card clickable-pillar"
          onClick={() => onNavigate('upload')}
          role="button"
          tabIndex={0}
        >
          <div className="pillar-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242" />
              <path d="M12 12v9" />
              <path d="m16 16-4-4-4 4" />
            </svg>
          </div>
          <div className="pillar-text">
            <strong>Upload Mode</strong>
            <span>Upload GeoTIFFs for analysis</span>
          </div>
        </div>

        <div
          className="feature-pillar-card clickable-pillar"
          onClick={() => onNavigate('multisensor')}
          role="button"
          tabIndex={0}
        >
          <div className="pillar-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
              <path d="M2 12h20" />
            </svg>
          </div>
          <div className="pillar-text">
            <strong>Multi-sensor</strong>
            <span>Sentinel-2 analytics; SAR fusion unavailable</span>
          </div>
        </div>

        <div
          className="feature-pillar-card clickable-pillar"
          onClick={() => onNavigate('benchmarks')}
          role="button"
          tabIndex={0}
        >
          <div className="pillar-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          </div>
          <div className="pillar-text">
            <strong>Verified Results</strong>
            <span>Evidence, confidence & execution trace</span>
          </div>
        </div>
      </section>

      {/* Recent Queries matching Reference Panel 1 */}
      <section className="recent-queries-card">
        <div className="recent-queries-header">
          <h3>Recent Queries</h3>
          <button
            type="button"
            className="view-all-link"
            onClick={() => onNavigate('history')}
          >
            View all history →
          </button>
        </div>

        {loadingHistory ? (
          <div className="recent-queries-loading">
            <span className="spinner-dot" />
            <span>Loading recent activity…</span>
          </div>
        ) : recentQueries.length === 0 ? (
          <div className="recent-queries-empty">
            <p>No recent analysis queries yet. Draw an area on the map or upload a GeoTIFF to begin.</p>
            <button
              type="button"
              className="start-query-button"
              onClick={() => onNavigate('map')}
            >
              Start First Analysis
            </button>
          </div>
        ) : (
          <div className="recent-queries-list">
            {recentQueries.slice(0, 6).map((item) => (
              <div
                key={item.id}
                className="recent-query-row"
                onClick={() => onOpenQuery(item.id)}
                role="button"
                tabIndex={0}
              >
                <div className="query-row-main">
                  <span className="query-row-text">{item.query || `Analysis (${item.operation || 'Index'})`}</span>
                  <span className="query-row-date">
                    {item.created ? new Date(item.created).toLocaleString(undefined, {
                      day: 'numeric',
                      month: 'short',
                      year: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    }) : ''}
                  </span>
                </div>
                <div className="query-row-status">
                  <span className={`status-badge-pill status-${item.status}`}>
                    {item.status === 'completed' ? 'Completed' : item.status}
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
