import React, { useEffect, useState } from 'react'
import { ApiError, getLayerUrl, getLayers } from '../api/client'
import type { ChangeHotspot, HistoryRecord, LayerLegend } from '../types/analysis'

type Props = { record: HistoryRecord | null }
const LABELS: Record<string, string> = { significant_decrease: 'Significant decrease', moderate_decrease: 'Moderate decrease', stable: 'Stable', moderate_increase: 'Moderate increase', significant_increase: 'Significant increase' }
const COLORS: Record<string, string> = { significant_decrease: '#b2182b', moderate_decrease: '#ef8a62', stable: '#f7f7f7', moderate_increase: '#67a9cf', significant_increase: '#1a9850' }

function isChange(record: HistoryRecord | null): boolean { return record?.status === 'completed' && record.result !== null && !('error' in record.result) && record.result.facts.operation === 'change_detection' }
export function classPercent(fraction: number | null): string { return fraction === null || !Number.isFinite(fraction) ? '—' : `${(fraction * 100).toFixed(1)}%` }

export const ChangeHotspotsView: React.FC<Props> = ({ record }) => {
  const [activeTab, setActiveTab] = useState<'analysis' | 'details'>('analysis')
  const [showHotspots, setShowHotspots] = useState(false)
  const [layers, setLayers] = useState<{ classes?: LayerLegend; hotspots?: LayerLegend } | null>(null)
  const [layerError, setLayerError] = useState<string | null>(null)

  useEffect(() => {
    setLayers(null); setLayerError(null)
    if (!record || !isChange(record)) return
    getLayers(record.id).then((response) => setLayers({ classes: response.layers.classes, hotspots: response.layers.hotspots })).catch((error: unknown) => setLayerError(error instanceof ApiError ? error.rawMessage : 'Change raster layers are unavailable.'))
  }, [record])

  if (!record) return <div className="empty-state"><h3>No completed change analysis selected</h3><p>Run or open a completed change-detection analysis to inspect real results.</p></div>
  if (record.result === null || 'error' in record.result) return <div className="empty-state"><h3>Change analysis is unavailable</h3><p>The selected history record has no completed result.</p></div>
  if (record.result.facts.operation !== 'change_detection' || !record.result.facts.change) return <div className="empty-state"><h3>This is not a change analysis</h3><p>Select a completed change-detection record.</p></div>

  const result = record.result
  const { facts, evidence } = result
  const change = facts.change
  if (!change) return <div className="empty-state"><h3>Change metrics are unavailable</h3><p>The selected result does not contain change-class metrics.</p></div>
  const canShowArea = evidence.scenes.every((scene) => typeof scene.resolution_m === 'number' && scene.resolution_m > 0)
  const hotspots = (result.hotspots ?? []) as unknown as ChangeHotspot[]
  const classEntries = Object.entries(change.classes)

  return <div className="change-hotspots-view-container">
    <div className="change-hotspots-grid">
      <div className="change-map-card">
        {layers?.classes ? <img className="change-raster-image" src={getLayerUrl(record.id, 'classes')} alt="Server-rendered change classes" /> : <div className="empty-state"><p>Change-class raster is not available for this result.</p></div>}
        {layers?.hotspots && <img className="change-hotspot-overlay" src={getLayerUrl(record.id, 'hotspots')} alt="Server-rendered change hotspots" />}
        {layerError && <p className="inline-message">{layerError}</p>}
      </div>
      <aside className="change-analysis-sidebar">
        <div className="change-tabs-row"><button type="button" className={`change-tab-btn ${activeTab === 'analysis' ? 'active' : ''}`} onClick={() => setActiveTab('analysis')}>Change Analysis</button><button type="button" className={`change-tab-btn ${activeTab === 'details' ? 'active' : ''}`} onClick={() => setActiveTab('details')}>Analysis Details</button></div>
        <div className="change-content-body">{activeTab === 'analysis' ? <>
          <div className="change-heading-block"><h3>Change Detection ({facts.date_a ?? '—'} – {facts.date_b ?? '—'})</h3><span className="sub-count">{classEntries.length} classes</span></div>
          <div className="classes-distribution-list">{classEntries.map(([name, metric]) => <div key={name} className="class-row-item"><div className="class-label-col"><span className="color-dot" style={{ backgroundColor: COLORS[name] ?? '#64748b' }} /><span className="class-name">{LABELS[name] ?? name}</span></div><div className="class-percent-col"><strong>{classPercent(metric.fraction_of_valid)}</strong>{canShowArea && metric.area_km2 !== null && <small>{metric.area_km2.toFixed(3)} km²</small>}</div></div>)}</div>
          <div className="hotspots-alert-card"><div className="hotspots-alert-header"><strong>{hotspots.length} significant-decrease hotspot{hotspots.length === 1 ? '' : 's'} detected</strong></div>{hotspots.length > 0 && <button type="button" className="view-details-btn" onClick={() => setShowHotspots(true)}>View Details</button>}</div>
        </> : <div className="analysis-details-scroll"><h4>Evidence</h4><div className="detail-stat-row"><span>Index</span><strong>{evidence.index ?? '—'}</strong></div><div className="detail-stat-row"><span>Scenes</span><strong>{evidence.scenes.map((scene) => scene.datetime.slice(0, 10)).join(' → ') || '—'}</strong></div><div className="detail-stat-row"><span>Valid pixels</span><strong>{classPercent(evidence.valid_pixel_fraction)}</strong></div><div className="detail-stat-row"><span>Analysed area</span><strong>{canShowArea && typeof facts.analysed_area_km2 === 'number' ? `${facts.analysed_area_km2.toFixed(3)} km²` : 'Unavailable from result metadata'}</strong></div><div className="detail-stat-row"><span>Thresholds</span><strong>{Object.entries(evidence.thresholds).map(([key, value]) => `${key}: ${value}`).join(', ') || '—'}</strong></div></div>}</div>
      </aside>
    </div>
    {showHotspots && <div className="modal-backdrop" onClick={() => setShowHotspots(false)}><div className="modal-card" onClick={(event) => event.stopPropagation()}><div className="modal-header"><h3>Detected hotspots ({hotspots.length})</h3><button type="button" className="close-modal-btn" onClick={() => setShowHotspots(false)}>×</button></div><div className="hotspots-table-wrapper"><table className="hotspots-table"><thead><tr><th>Cluster</th><th>Centroid (lon, lat)</th><th>Area</th><th>Mean NDVI change</th></tr></thead><tbody>{hotspots.map((hotspot) => <tr key={String(hotspot.id)}><td><strong>{hotspot.id}</strong></td><td>{hotspot.centroid_lonlat ? `${hotspot.centroid_lonlat[0].toFixed(5)}, ${hotspot.centroid_lonlat[1].toFixed(5)}` : 'Unavailable from result'}</td><td>{canShowArea && hotspot.area_km2 !== null ? `${(hotspot.area_km2 * 1e6).toFixed(0)} m²` : 'Unavailable from result'}</td><td>{hotspot.mean_diff === null ? '—' : hotspot.mean_diff.toFixed(3)}</td></tr>)}</tbody></table></div></div></div>}
  </div>
}
