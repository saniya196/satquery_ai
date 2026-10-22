import React, { useEffect, useState } from 'react'
import { ApiError, getLayerUrl, getLayers } from '../api/client'
import type { HistoryRecord, LayerLegend } from '../types/analysis'

type Props = { record: HistoryRecord | null }
type SubTab = 'indices' | 'change' | 'trend'
type SensorSelection = 'optical' | 'sar' | 'both'

export const MultiSensorView: React.FC<Props> = ({ record }) => {
  const [activeTab, setActiveTab] = useState<SubTab>('indices')
  const [sensorMode, setSensorMode] = useState<SensorSelection>('optical')
  const [layers, setLayers] = useState<{ index?: LayerLegend; diff?: LayerLegend } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const result = record?.result && !('error' in record.result) ? record.result : null
  const isSentinel2 = result?.evidence.scenes.some((scene) => scene.source?.toLowerCase().includes('sentinel-2') || scene.processing_level !== null) ?? false

  useEffect(() => {
    setLayers(null); setError(null)
    if (!record || !result || record.status !== 'completed') return
    getLayers(record.id).then((response) => setLayers({ index: response.layers.index, diff: response.layers.diff })).catch((reason: unknown) => setError(reason instanceof ApiError ? reason.rawMessage : 'Raster layer is unavailable.'))
  }, [record, result])

  const showOptical = sensorMode === 'optical' || sensorMode === 'both'
  const showSar = sensorMode === 'sar' || sensorMode === 'both'
  return <div className="multisensor-view-container">
    <div className="multisensor-top-tabs"><button type="button" className={`sub-tab-btn ${activeTab === 'indices' ? 'active' : ''}`} onClick={() => setActiveTab('indices')}>Indices</button><button type="button" className={`sub-tab-btn ${activeTab === 'change' ? 'active' : ''}`} onClick={() => setActiveTab('change')}>Change Detection</button><button type="button" className={`sub-tab-btn ${activeTab === 'trend' ? 'active' : ''}`} onClick={() => setActiveTab('trend')}>Trend Analysis</button></div>
    <div className="multisensor-layout-grid"><aside className="sensor-controls-card"><div className="control-group"><h4>Data source</h4><label className="sensor-radio-label"><input type="radio" name="sensorSelection" checked={sensorMode === 'optical'} onChange={() => setSensorMode('optical')} /><span>Optical (Sentinel-2)</span></label><label className="sensor-radio-label"><input type="radio" name="sensorSelection" checked={sensorMode === 'sar'} onChange={() => setSensorMode('sar')} /><span>SAR (Sentinel-1 — unavailable)</span></label><label className="sensor-radio-label"><input type="radio" name="sensorSelection" checked={sensorMode === 'both'} onChange={() => setSensorMode('both')} /><span>Optical + SAR (unavailable)</span></label></div><div className="fusion-notes-box"><span className="notes-kicker">Integration status</span><p>Sentinel-1 SAR fusion, image VQA, image captioning, and text-guided visual grounding are unavailable. This view currently shows Sentinel-2 results only.</p></div></aside>
      <div className="sensor-displays-row">{showOptical && <div className="sensor-display-card"><div className="display-card-header"><h3>Sentinel-2 analysis</h3><span className="sensor-meta-badge optical-badge">Real result only</span></div>{!record || !result || !isSentinel2 ? <div className="empty-state"><p>No completed Sentinel-2 result is selected.</p></div> : <><div className="display-map-canvas">{layers?.[activeTab === 'change' ? 'diff' : 'index'] && <img className="raster-preview-image" src={getLayerUrl(record.id, activeTab === 'change' ? 'diff' : 'index')} alt="Server-rendered Sentinel-2 analysis raster" />}{!layers?.[activeTab === 'change' ? 'diff' : 'index'] && <p>No server-rendered raster is available for this result.</p>}</div><p>{result.facts.index ?? 'Sentinel-2'} · {result.evidence.scenes.map((scene) => scene.datetime.slice(0, 10)).join(', ')}</p></>}</div>}{showSar && <div className="sensor-display-card"><div className="display-card-header"><h3>Sentinel-1 SAR</h3><span className="sensor-meta-badge sar-badge">Unavailable</span></div><div className="empty-state"><p>Sentinel-1 acquisition, co-registration, fusion, and SAR visualization are not implemented.</p></div></div>}</div>
    </div>{error && <p className="inline-message">{error}</p>}
  </div>
}
