import React, { useEffect, useState } from 'react'
import { ApiError, getLayerUrl, getLayers } from '../api/client'
import type { ChangeHotspot, HistoryRecord, HistorySummary, LayerLegend } from '../types/analysis'

type Props = {
  record: HistoryRecord | null
  selectedHotspot?: ChangeHotspot | null
  onSelectHotspot?: (hotspot: ChangeHotspot) => void
  onClearSelectedHotspot?: () => void
  recentAnalyses?: HistorySummary[]
  onChooseHistory?: (id: string) => void
}
const LABELS: Record<string, string> = {
  significant_decrease: 'Significant decrease (red)',
  moderate_decrease: 'Moderate decrease (red)',
  stable: 'Little or no change (grey)',
  moderate_increase: 'Moderate increase (green)',
  significant_increase: 'Significant increase (green)',
}
const COLORS: Record<string, string> = { significant_decrease: '#b2182b', moderate_decrease: '#ef8a62', stable: '#d1d5db', moderate_increase: '#67a9cf', significant_increase: '#1a9850' }

function isChange(record: HistoryRecord | null): boolean { return record?.status === 'completed' && record.result !== null && !('error' in record.result) && record.result.facts.operation === 'change_detection' }
export function classPercent(fraction: number | null): string { return fraction === null || !Number.isFinite(fraction) ? '—' : `${(fraction * 100).toFixed(1)}%` }

function hasValidBbox(bbox: ChangeHotspot['bbox_lonlat']): bbox is [number, number, number, number] {
  return Array.isArray(bbox) && bbox.length === 4 && bbox.every((v) => typeof v === 'number' && Number.isFinite(v)) && bbox[0] <= bbox[2] && bbox[1] <= bbox[3]
}
function hasValidCentroid(centroid: ChangeHotspot['centroid_lonlat']): centroid is [number, number] {
  return Array.isArray(centroid) && centroid.length === 2 && centroid.every((v) => typeof v === 'number' && Number.isFinite(v)) && centroid[0] >= -180 && centroid[0] <= 180 && centroid[1] >= -90 && centroid[1] <= 90
}
export function hotspotMappable(hotspot: ChangeHotspot): boolean {
  return hasValidBbox(hotspot.bbox_lonlat) || hasValidCentroid(hotspot.centroid_lonlat)
}

export const ChangeHotspotsView: React.FC<Props> = ({ record, selectedHotspot = null, onSelectHotspot, onClearSelectedHotspot, recentAnalyses = [], onChooseHistory }) => {
  const [activeTab, setActiveTab] = useState<'analysis' | 'details'>('analysis')
  const [showHotspots, setShowHotspots] = useState(false)
  const [layers, setLayers] = useState<{ classes?: LayerLegend; hotspots?: LayerLegend } | null>(null)
  const [layerError, setLayerError] = useState<string | null>(null)
  const [mapNavMessage, setMapNavMessage] = useState<string | null>(null)

  useEffect(() => {
    setLayers(null); setLayerError(null)
    if (!record || !isChange(record)) return
    getLayers(record.id).then((response) => setLayers({ classes: response.layers.classes, hotspots: response.layers.hotspots })).catch((error: unknown) => setLayerError(error instanceof ApiError ? error.rawMessage : 'Change raster layers are unavailable.'))
  }, [record])

  if (!record) return <div className="page-content empty-page"><h2>Change Hotspots</h2><p>See where greenery or land changed the most.</p><div className="empty-state"><h3>No completed change analysis selected</h3><p>Open a completed change-detection analysis to inspect real results.</p><div className="recent-analysis-cards">{recentAnalyses.filter((item) => item.status === 'completed' && item.operation === 'change_detection').slice(0, 6).map((item) => <article className="recent-analysis-card" key={item.id}><strong>{item.query}</strong><small>{item.created ? new Date(item.created).toLocaleString() : 'Completed analysis'}</small><button type="button" className="open-analysis-btn" onClick={() => onChooseHistory?.(item.id)}>Open</button></article>)}</div>{recentAnalyses.filter((item) => item.status === 'completed' && item.operation === 'change_detection').length === 0 && <p>No completed change analyses yet. Run one in Map Mode first.</p>}</div></div>
  if (record.result === null || 'error' in record.result) return <div className="page-content empty-page"><div className="empty-state"><h3>Change analysis is unavailable</h3><p>The selected history record has no completed result.</p></div></div>
  if (record.result.facts.operation !== 'change_detection' || !record.result.facts.change) return <div className="page-content empty-page"><div className="empty-state"><h3>This is not a change analysis</h3><p>Select a completed change-detection record.</p></div></div>

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
        {layers?.classes ? <img className="change-raster-image" src={getLayerUrl(record.id, 'classes')} alt="Map showing change categories by color" /> : <div className="empty-state"><p>Change map is not available for this result.</p></div>}
        {layers?.hotspots && <img className="change-hotspot-overlay" src={getLayerUrl(record.id, 'hotspots')} alt="Map overlay showing detected change hotspots" />}
        {layerError && <p className="inline-message">{layerError}</p>}
      </div>
      <aside className="change-analysis-sidebar">
        <div className="change-tabs-row"><button type="button" className={`change-tab-btn ${activeTab === 'analysis' ? 'active' : ''}`} onClick={() => setActiveTab('analysis')}>Change summary</button><button type="button" className={`change-tab-btn ${activeTab === 'details' ? 'active' : ''}`} onClick={() => setActiveTab('details')}>Evidence details</button></div>
        <div className="change-content-body">{activeTab === 'analysis' ? <>
          <div className="change-heading-block"><h3>Measured change ({facts.date_a ?? '—'} to {facts.date_b ?? '—'})</h3><span className="sub-count">{classEntries.length} categories</span></div>
          <p className="confidence-caveat">Colors/text show measured index change categories: <strong>green = increased</strong>, <strong>red = decreased</strong>, <strong>grey = little or no change</strong>. These are not direct proof of cause.</p>
          <div className="classes-distribution-list">{classEntries.map(([name, metric]) => <div key={name} className="class-row-item"><div className="class-label-col"><span className="color-dot" style={{ backgroundColor: COLORS[name] ?? '#64748b' }} aria-hidden="true" /><span className="class-name">{LABELS[name] ?? name.replaceAll('_', ' ')}</span></div><div className="class-percent-col"><strong>{classPercent(metric.fraction_of_valid)}</strong>{canShowArea && metric.area_km2 !== null && <small>{metric.area_km2.toFixed(3)} km²</small>}</div></div>)}</div>
          <div className="hotspots-alert-card"><div className="hotspots-alert-header"><strong>{hotspots.length} area{hotspots.length === 1 ? '' : 's'} with notable measured decrease</strong></div><p className="hotspot-class-note">A hotspot is a cluster of pixels where the measured index decreased significantly compared to the baseline (based on the analysis thresholds). It shows <em>where</em> and <em>how much</em> the index changed, not why it changed.</p>{hotspots.length > 0 && <button type="button" className="view-details-btn" onClick={() => setShowHotspots(true)}>View hotspot details</button>}</div>
        </> : <div className="analysis-details-scroll"><h4>Evidence</h4><div className="detail-stat-row"><span>Measured indicator</span><strong>{evidence.index ?? '—'}</strong></div><div className="detail-stat-row"><span>Image dates</span><strong>{evidence.scenes.map((scene) => scene.datetime.slice(0, 10)).join(' → ') || '—'}</strong></div><div className="detail-stat-row"><span>Usable pixels</span><strong>{classPercent(evidence.valid_pixel_fraction)}</strong></div><div className="detail-stat-row"><span>Analyzed area</span><strong>{canShowArea && typeof facts.analysed_area_km2 === 'number' ? `${facts.analysed_area_km2.toFixed(3)} km²` : 'Unavailable from result metadata'}</strong></div><div className="detail-stat-row"><span>Thresholds (technical)</span><strong>{Object.entries(evidence.thresholds).map(([key, value]) => `${key}: ${value}`).join(', ') || '—'}</strong></div></div>}</div>
      </aside>
    </div>
    {showHotspots && <div className="modal-backdrop" onClick={() => { setShowHotspots(false); setMapNavMessage(null) }}><div className="modal-card hotspot-detail-modal" onClick={(event) => event.stopPropagation()}><div className="modal-header"><h3>Hotspot details ({hotspots.length})</h3><div>{selectedHotspot && onClearSelectedHotspot && <button type="button" className="close-modal-btn" onClick={() => { onClearSelectedHotspot(); setMapNavMessage(null) }} title="Clear hotspot selection on the map">Clear map selection</button>}<button type="button" className="close-modal-btn" onClick={() => { setShowHotspots(false); setMapNavMessage(null) }} aria-label="Close">×</button></div></div>{mapNavMessage && <p className="inline-message" role="status">{mapNavMessage}</p>}<p className="hotspot-evidence-note">Each hotspot is a cluster where the measured index decreased significantly. Direction and magnitude come from the analysis evidence. Use <strong>Show on map</strong> to locate it (when coordinates are available).</p><div className="hotspots-table-wrapper"><table className="hotspots-table hotspot-evidence-table"><thead><tr><th>Hotspot</th><th>Change (direction &amp; indicator)</th><th>Area (if available)</th><th>Measured change (mean / median)</th><th>Pixels in cluster</th><th>Image dates</th><th>Location / map</th><th>Evidence (technical)</th></tr></thead><tbody>{hotspots.map((hotspot) => {
        const ev = hotspot.evidence
        const dates = ev?.baseline_date || ev?.comparison_date ? `${ev?.baseline_date ?? '—'} → ${ev?.comparison_date ?? '—'}` : (facts.date_a && facts.date_b ? `${facts.date_a} → ${facts.date_b}` : '—')
        const idx = ev?.index ?? evidence.index ?? facts.index ?? 'index'
        const mean = hotspot.mean_diff === null || hotspot.mean_diff === undefined ? '—' : Number(hotspot.mean_diff).toFixed(3)
        const median = hotspot.median_diff === null || hotspot.median_diff === undefined ? '—' : Number(hotspot.median_diff).toFixed(3)
        const bboxText = hotspot.bbox_lonlat && hotspot.bbox_lonlat.length === 4
          ? `Box: ${hotspot.bbox_lonlat[0].toFixed(5)}, ${hotspot.bbox_lonlat[1].toFixed(5)} to ${hotspot.bbox_lonlat[2].toFixed(5)}, ${hotspot.bbox_lonlat[3].toFixed(5)}`
          : (hotspot.centroid_lonlat ? `Centre point: ${hotspot.centroid_lonlat[0].toFixed(5)}, ${hotspot.centroid_lonlat[1].toFixed(5)}` : 'Location not available')
        const mappable = hotspotMappable(hotspot)
        const validPx = hotspot.valid_pixel_count ?? hotspot.pixels
        const cls = hotspot.class ? hotspot.class.replaceAll('_', ' ') : 'significant decrease'
        const isSelected = selectedHotspot !== null && String(selectedHotspot.id) === String(hotspot.id)
        return <tr key={String(hotspot.id)} className={isSelected ? 'hotspot-row-selected' : undefined} aria-selected={isSelected || undefined}><td><strong>#{hotspot.id}</strong><div className="hotspot-class-note">{cls}</div></td><td>{hotspot.direction ? `${hotspot.direction} (${idx})` : `${cls} (${idx})`}</td><td>{canShowArea && hotspot.area_km2 !== null ? `${(Number(hotspot.area_km2) * 1e6).toFixed(0)} m²` : 'Not available'}</td><td>{mean} / {median}</td><td>{typeof validPx === 'number' ? validPx.toLocaleString() : '—'}</td><td title={ev?.baseline_scene_id && ev?.comparison_scene_id ? `${ev.baseline_scene_id} → ${ev.comparison_scene_id}` : undefined}>{dates}</td><td><div>{bboxText}</div>{mappable ? <button type="button" className="view-details-btn hotspot-show-map-btn" onClick={() => { setMapNavMessage(null); onSelectHotspot?.(hotspot) }} title="Show this hotspot on the map">Show on map</button> : <div className="hotspot-class-note" role="status">Cannot show on map: coordinates are not available for this hotspot.</div>}</td><td><details><summary>Evidence refs</summary><div className="hotspot-evidence-refs">{ev?.baseline_scene_id || ev?.comparison_scene_id ? <div>Scenes: {ev?.baseline_scene_id ?? '—'} → {ev?.comparison_scene_id ?? '—'}</div> : null}<div>Index/formula: {idx}{ev?.formula ? ` (${ev.formula})` : (evidence.formula ? ` (${evidence.formula})` : '')}</div><div>Thresholds: {JSON.stringify(ev?.change_thresholds ?? evidence.thresholds ?? {})}</div><div>Global usable pixels: {classPercent(typeof ev?.global_valid_pixel_fraction === 'number' ? ev.global_valid_pixel_fraction : evidence.valid_pixel_fraction)}</div></div></details></td></tr>
      })}</tbody></table></div><p className="hotspot-evidence-note">These values describe measured index differences from the analysis evidence. They do not indicate the cause of the change.</p></div></div>}
  </div>
}
