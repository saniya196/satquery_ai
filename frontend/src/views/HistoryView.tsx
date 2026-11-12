import React, { useState } from 'react'
import { useLanguage } from '../i18n'
import type { HistorySummary } from '../types/analysis'

const OPERATION_LABELS: Record<string, string> = {
  change_detection: 'Change detection',
  index_stats: 'Index statistics',
  time_series: 'Time series',
  land_cover: 'Land-cover classification',
}

function operationLabel(operation: string | null | undefined): string {
  if (!operation) return 'Analysis'
  return OPERATION_LABELS[operation] ?? operation.replaceAll('_', ' ')
}

function dateSummary(query: string): string | null {
  const dates = query.match(/\b\d{4}-\d{2}-\d{2}\b/g) ?? []
  const uniqueDates = [...new Set(dates)]
  if (uniqueDates.length === 0) return null
  return uniqueDates.length === 1 ? uniqueDates[0] : `${uniqueDates[0]} → ${uniqueDates[1]}`
}

interface HistoryViewProps {
  items: HistorySummary[]
  loading: boolean
  error: string | null
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onRefresh: () => void
}

export const HistoryView: React.FC<HistoryViewProps> = ({
  items,
  loading,
  error,
  onSelect,
  onDelete,
  onRefresh,
}) => {
  const { t } = useLanguage()
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'completed' | 'failed'>('all')

  const filtered = items.filter((item) => {
    const matchesSearch = item.query.toLowerCase().includes(searchTerm.toLowerCase()) ||
      operationLabel(item.operation).toLowerCase().includes(searchTerm.toLowerCase())
    const matchesStatus = statusFilter === 'all' || item.status === statusFilter
    return matchesSearch && matchesStatus
  })

  return (
    <div className="history-view-container">
      <div className="history-view-header">
        <div>
          <h2>{t('history.title')}</h2>
          <p>{t('history.subtitle')}</p>
        </div>
        <button
          type="button"
          className="refresh-btn"
          onClick={onRefresh}
          disabled={loading}
        >
          {loading ? t('history.refreshing') : `↻ ${t('common.refresh')}`}
        </button>
      </div>

      <p className="history-artifacts-note" style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 12 }}>
        {t('history.artifactsNote')}
      </p>

      <div className="history-controls-row">
        <div className="search-box">
          <input
            type="text"
            placeholder={t('history.search')}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            aria-label={t('history.search')}
          />
        </div>
        <div className="filter-group">
          <button
            type="button"
            className={`filter-btn ${statusFilter === 'all' ? 'active' : ''}`}
            onClick={() => setStatusFilter('all')}
          >
            {t('history.all')} ({items.length})
          </button>
          <button
            type="button"
            className={`filter-btn ${statusFilter === 'completed' ? 'active' : ''}`}
            onClick={() => setStatusFilter('completed')}
          >
            {t('history.completed')} ({items.filter((i) => i.status === 'completed').length})
          </button>
          <button
            type="button"
            className={`filter-btn ${statusFilter === 'failed' ? 'active' : ''}`}
            onClick={() => setStatusFilter('failed')}
          >
            {t('history.failed')} ({items.filter((i) => i.status === 'failed').length})
          </button>
        </div>
      </div>

      {error && (
        <div className="history-error-banner">
          <span>{t('history.error')}: {error}</span>
        </div>
      )}

      {loading ? (
        <div className="history-loading-state">
          <span className="spinner-dot" />
          <span>{t('history.loading')}</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="history-empty-card">
          <p>{items.length === 0 ? t('home.noAnalyses') : t('history.empty')}</p>
          {items.length === 0 && <p style={{ marginTop: 8, fontSize: 14 }}>{t('home.noAnalysesHelp')}</p>}
        </div>
      ) : (
        <div className="history-table-card">
          <table className="history-records-table">
            <thead>
              <tr>
                <th>{t('history.status')}</th>
                <th>{t('history.query')}</th>
                <th>{t('history.operation')}</th>
                <th>{t('history.created')}</th>
                <th>{t('history.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.id}>
                  <td>
                    <span className={`status-pill status-${item.status}`}>
                      {t(`status.${item.status}`, item.status)}
                    </span>
                  </td>
                  <td className="query-cell">
                    <strong>{item.query}</strong>
                  </td>
                  <td className="op-cell">
                    <span className="op-chip">{operationLabel(item.operation)}</span>
                  </td>
                  <td className="date-cell">
                    <div>{item.created ? new Date(item.created).toLocaleString() : '—'}</div>
                    {dateSummary(item.query) && <small className="history-observation-date">Observations: {dateSummary(item.query)}</small>}
                  </td>
                  <td className="actions-cell">
                    <button
                      type="button"
                      className="open-analysis-btn"
                      onClick={() => onSelect(item.id)}
                      title={item.status !== 'completed' ? t('history.artifactsNote') : undefined}
                    >
                      {t('history.open')}
                    </button>
                    <button
                      type="button"
                      className="delete-item-btn"
                      onClick={() => onDelete(item.id)}
                      title={t('history.delete')}
                      aria-label={t('history.delete')}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
