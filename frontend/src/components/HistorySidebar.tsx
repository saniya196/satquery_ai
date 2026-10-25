import { useEffect, useRef, useState } from 'react'
import type { HistorySummary } from '../types/analysis'

interface HistorySidebarProps {
  items: HistorySummary[]
  activeId: string | null
  loading: boolean
  error: string | null
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onRefresh: () => void
}

function operationLabel(operation: string) {
  return operation.replaceAll('_', ' ')
}

export function HistorySidebar({ items, activeId, loading, error, onSelect, onDelete, onRefresh }: HistorySidebarProps) {
  const [collapsed, setCollapsed] = useState(true)
  const railRef = useRef<HTMLButtonElement>(null)
  const collapseRef = useRef<HTMLButtonElement>(null)
  const pendingFocus = useRef<'rail' | 'panel' | null>(null)

  useEffect(() => {
    const target = pendingFocus.current === 'rail' ? railRef.current : pendingFocus.current === 'panel' ? collapseRef.current : null
    if (!target) return
    pendingFocus.current = null
    target.focus()
  }, [collapsed])

  function toggle() {
    pendingFocus.current = collapsed ? 'panel' : 'rail'
    setCollapsed((value) => !value)
  }

  if (collapsed) {
    return (
      <aside className="history-sidebar history-sidebar-collapsed" aria-label="Analysis history">
        <button
          ref={railRef}
          className="history-rail-toggle"
          type="button"
          aria-expanded={false}
          title="Show analysis history"
          onClick={toggle}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h10" /></svg>
          <span>History</span>
          {items.length > 0 && <span className="history-rail-count">{items.length}<span className="visually-hidden"> stored analyses</span></span>}
        </button>
      </aside>
    )
  }

  return (
    <aside className="history-sidebar" aria-label="Analysis history">
      <div className="history-heading">
        <div>
          <span className="eyebrow">ARCHIVE</span>
          <h2>History</h2>
        </div>
        <div className="history-heading-actions">
          <button className="icon-button" type="button" title="Refresh history" aria-label="Refresh history" onClick={onRefresh} disabled={loading}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5" /><path d="M5.6 9a7 7 0 0 1 11.9-2L20 12M4 12l2.5 5a7 7 0 0 0 11.9-2" /></svg>
          </button>
          <button ref={collapseRef} className="icon-button" type="button" title="Hide analysis history" aria-label="Hide analysis history" aria-expanded={true} onClick={toggle}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5-7 7 7 7" /></svg>
          </button>
        </div>
      </div>
      {error && <p className="sidebar-error">{error}</p>}
      <div className="history-list" aria-live="polite">
        {loading && items.length === 0 && <p className="sidebar-empty">Loading history…</p>}
        {!loading && items.length === 0 && <p className="sidebar-empty">Completed analyses will appear here.</p>}
        {items.map((item) => (
          <article className={`history-item ${item.id === activeId ? 'history-item-active' : ''}`} key={item.id}>
            <button className="history-item-open" type="button" onClick={() => onSelect(item.id)}>
              <span className="history-item-topline">
                <span className={`status-dot status-${item.status}`} />
                <span>{operationLabel(item.operation)}</span>
                <time dateTime={item.created}>{new Date(item.created).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</time>
              </span>
              <span className="history-item-query">{item.query}</span>
            </button>
            <button className="history-delete" type="button" title="Delete from history" aria-label={`Delete ${item.query}`} onClick={() => onDelete(item.id)}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M5 7l1 13h12l1-13M9 7V4h6v3" /></svg>
            </button>
          </article>
        ))}
      </div>
      <div className="history-footnote"><span className="storage-glyph" aria-hidden="true">▤</span> Stored analysis records</div>
    </aside>
  )
}
