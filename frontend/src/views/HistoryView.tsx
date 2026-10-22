import React, { useState } from 'react'
import type { HistorySummary } from '../types/analysis'

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
  const [searchTerm, setSearchTerm] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'completed' | 'failed'>('all')

  const filtered = items.filter((item) => {
    const matchesSearch = item.query.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (item.operation && item.operation.toLowerCase().includes(searchTerm.toLowerCase()))
    const matchesStatus = statusFilter === 'all' || item.status === statusFilter
    return matchesSearch && matchesStatus
  })

  return (
    <div className="history-view-container">
      <div className="history-view-header">
        <div>
          <h2>Analysis History</h2>
          <p>Audit trail of all requested satellite queries, deterministic results, and evidence packages.</p>
        </div>
        <button
          type="button"
          className="refresh-btn"
          onClick={onRefresh}
          disabled={loading}
        >
          {loading ? 'Refreshing…' : '↻ Refresh'}
        </button>
      </div>

      <div className="history-controls-row">
        <div className="search-box">
          <input
            type="text"
            placeholder="Search queries or operations…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <div className="filter-group">
          <button
            type="button"
            className={`filter-btn ${statusFilter === 'all' ? 'active' : ''}`}
            onClick={() => setStatusFilter('all')}
          >
            All ({items.length})
          </button>
          <button
            type="button"
            className={`filter-btn ${statusFilter === 'completed' ? 'active' : ''}`}
            onClick={() => setStatusFilter('completed')}
          >
            Completed ({items.filter((i) => i.status === 'completed').length})
          </button>
          <button
            type="button"
            className={`filter-btn ${statusFilter === 'failed' ? 'active' : ''}`}
            onClick={() => setStatusFilter('failed')}
          >
            Failed ({items.filter((i) => i.status === 'failed').length})
          </button>
        </div>
      </div>

      {error && (
        <div className="history-error-banner">
          <span>Error loading history: {error}</span>
        </div>
      )}

      {loading ? (
        <div className="history-loading-state">
          <span className="spinner-dot" />
          <span>Loading historical queries…</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="history-empty-card">
          <p>No historical records match your filter.</p>
        </div>
      ) : (
        <div className="history-table-card">
          <table className="history-records-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Query / Question</th>
                <th>Operation</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.id}>
                  <td>
                    <span className={`status-pill status-${item.status}`}>
                      {item.status}
                    </span>
                  </td>
                  <td className="query-cell">
                    <strong>{item.query}</strong>
                  </td>
                  <td className="op-cell">
                    <span className="op-chip">{item.operation || 'general'}</span>
                  </td>
                  <td className="date-cell">
                    {item.created ? new Date(item.created).toLocaleString() : '—'}
                  </td>
                  <td className="actions-cell">
                    <button
                      type="button"
                      className="open-analysis-btn"
                      onClick={() => onSelect(item.id)}
                    >
                      Open in Map
                    </button>
                    <button
                      type="button"
                      className="delete-item-btn"
                      onClick={() => onDelete(item.id)}
                      title="Delete record"
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
