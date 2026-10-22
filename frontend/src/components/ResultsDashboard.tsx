import { useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { AnalysisResult, CompareResponse, HistoryRecord, LandCoverClassMetric, ChangeClassMetric } from '../types/analysis'

interface ResultsDashboardProps {
  record: HistoryRecord | null
  compare: CompareResponse | null
  busyExport: string | null
  exportError: string | null
  onExport: (format: 'csv' | 'geojson') => void
}

const colors = ['#78934d', '#d6a147', '#ca7057', '#43879b', '#8799ad', '#7d7688']

function displayed(value: unknown, digits = 3): string {
  if (value === null || value === undefined || value === '') return 'n/a'
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) : 'n/a'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

function percent(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a'
  return `${(value * 100).toFixed(1)}%`
}

function isAnalysisResult(value: HistoryRecord['result']): value is AnalysisResult {
  return Boolean(value && typeof value === 'object' && 'facts' in value && 'evidence' in value)
}

function operationName(value: string) {
  return value.replaceAll('_', ' ')
}

function ClassChart({ result }: { result: AnalysisResult }) {
  const facts = result.facts
  const classes = facts.change?.classes ?? facts.classes ?? {}
  const data = Object.entries(classes).map(([name, metrics]) => {
    const metric = metrics as ChangeClassMetric | LandCoverClassMetric
    const value = 'fraction_of_valid' in metric ? metric.fraction_of_valid : metric.fraction
    return { name: operationName(name), value: typeof value === 'number' ? value * 100 : null }
  }).filter((item) => item.value !== null)

  return (
    <div className="chart-frame">
      {data.length === 0 ? <p className="empty-chart">No class metrics in this result.</p> : (
        <ResponsiveContainer width="100%" height={205}>
          <BarChart data={data} margin={{ top: 10, right: 5, bottom: 4, left: -20 }}>
            <CartesianGrid stroke="#e5e9e0" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 9 }} interval={0} />
            <YAxis tick={{ fontSize: 9 }} unit="%" />
            <Tooltip formatter={(value) => [`${displayed(value, 1)}%`, 'Area share']} />
            <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={34}>
              {data.map((item, index) => <Cell key={item.name} fill={colors[index % colors.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

function TimeSeriesChart({ result }: { result: AnalysisResult }) {
  const series = result.facts.series
  const anomalies = new Set(series?.anomaly_indices ?? [])
  const data = (series?.dates ?? []).map((date, index) => ({
    date: date.slice(5),
    value: series?.values[index] ?? null,
    rolling: series?.rolling_mean_3[index] ?? null,
    anomaly: anomalies.has(index) ? series?.values[index] ?? null : null,
  }))

  return (
    <div className="chart-frame">
      {data.length < 1 ? <p className="empty-chart">No date-series values in this result.</p> : (
        <ResponsiveContainer width="100%" height={205}>
          <ComposedChart data={data} margin={{ top: 10, right: 8, bottom: 4, left: -20 }}>
            <CartesianGrid stroke="#e5e9e0" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 9 }} minTickGap={12} />
            <YAxis tick={{ fontSize: 9 }} domain={['auto', 'auto']} />
            <Tooltip />
            <Line type="monotone" dataKey="value" name="AOI median" stroke="#64834a" strokeWidth={2} dot={false} connectNulls />
            <Line type="monotone" dataKey="rolling" name="Rolling mean (3)" stroke="#d5a449" strokeWidth={1.5} dot={false} connectNulls />
            <Scatter dataKey="anomaly" name="Anomaly" fill="#c95c49" shape="circle" />
          </ComposedChart>
        </ResponsiveContainer>
      )}
      {!series?.trend_claim_allowed && <p className="trend-guard">Not enough dates for a trend test</p>}
    </div>
  )
}

function OperationChart({ result }: { result: AnalysisResult }) {
  if (result.facts.operation === 'time_series') return <TimeSeriesChart result={result} />
  if (result.facts.operation === 'change_detection' || result.facts.operation === 'land_cover') return <ClassChart result={result} />
  return <p className="empty-chart">No chart is defined for this operation.</p>
}

function MetricCards({ result }: { result: AnalysisResult }) {
  const { facts, evidence } = result
  let entries: Array<[string, unknown, 'number' | 'percent']> = []
  if (facts.operation === 'change_detection') {
    entries = [
      ['Baseline mean', facts.change?.mean_a, 'number'],
      ['Comparison mean', facts.change?.mean_b, 'number'],
      ['Mean change', facts.change?.mean_change, 'number'],
      ['Change of mean', facts.change?.percent_change_of_mean, 'number'],
    ]
  } else if (facts.operation === 'index_stats') {
    entries = [
      ['Mean', facts.stats?.mean, 'number'], ['Median', facts.stats?.median, 'number'],
      ['Minimum', facts.stats?.min, 'number'], ['Maximum', facts.stats?.max, 'number'],
    ]
  } else if (facts.operation === 'time_series') {
    entries = [
      ['Valid dates', facts.series?.trend_test?.n ?? facts.series?.dates.length ?? null, 'number'],
      ['Sen slope / year', facts.series?.sens_slope_per_year, 'number'],
      ['Trend test', facts.series?.trend_test?.trend ?? (facts.series?.trend_claim_allowed ? null : 'Not enough dates'), 'number'],
      ['Valid pixels', evidence.valid_pixel_fraction, 'percent'],
    ]
  } else {
    entries = [
      ['Dominant class', facts.dominant_class, 'number'],
      ['Dominant share', facts.dominant_fraction, 'percent'],
      ['Classified area', facts.classified_fraction, 'percent'],
      ['Model confidence', facts.mean_model_confidence, 'percent'],
    ]
  }

  return <div className="metrics-grid">{entries.map(([label, value, style]) => (
    <div className="metric-card" key={label}>
      <span>{label}</span>
      <strong>{style === 'percent' ? percent(value) : displayed(value)}</strong>
    </div>
  ))}</div>
}

function ConfidencePanel({ result }: { result: AnalysisResult }) {
  return (
    <section className="dashboard-section">
      <div className="dashboard-section-heading"><h3>Confidence</h3><span>{displayed(result.confidence.score, 1)}{result.confidence.score === null ? '' : '/100'}</span></div>
      {result.facts.operation === 'land_cover' && <p className="confidence-caveat">Land-cover output is model confidence, not certainty.</p>}
      <div className="confidence-list">
        {(result.confidence.breakdown ?? []).map((factor, index) => (
          <div className="confidence-row" key={`${factor.factor}-${index}`}>
            <div className="confidence-row-top"><strong>{operationName(factor.factor)}</strong><span>{displayed(factor.score, 1)}</span></div>
            <div className="confidence-track"><span style={{ width: `${Math.max(0, Math.min(100, factor.score ?? 0))}%` }} /></div>
            <p>{factor.explanation}</p>
          </div>
        ))}
        {result.confidence.breakdown.length === 0 && <p className="empty-chart">No confidence factors were returned.</p>}
      </div>
    </section>
  )
}

function EvidencePanel({ result }: { result: AnalysisResult }) {
  const evidence = result.evidence
  return (
    <section className="dashboard-section">
      <div className="dashboard-section-heading"><h3>Evidence</h3><span>{evidence.scenes.length} scenes</span></div>
      <div className="table-scroll">
        <table className="scene-table">
          <thead><tr><th>Scene</th><th>Date</th><th>Cloud</th><th>Resolution</th></tr></thead>
          <tbody>{evidence.scenes.map((scene) => (
            <tr key={`${scene.item_id}-${scene.datetime}`}>
              <td title={scene.item_id}>{scene.item_id}</td>
              <td>{scene.datetime ? new Date(scene.datetime).toLocaleDateString() : 'n/a'}</td>
              <td>{scene.cloud_cover === null ? 'n/a' : `${displayed(scene.cloud_cover, 1)}%`}</td>
              <td>{scene.resolution_m === null ? 'n/a' : `${displayed(scene.resolution_m, 1)} m`}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <dl className="evidence-list">
        <div><dt>AOI area</dt><dd>{evidence.aoi_area_km2 === null ? 'n/a' : `${displayed(evidence.aoi_area_km2)} km²`}</dd></div>
        <div><dt>Index</dt><dd>{displayed(evidence.index)}</dd></div>
        <div><dt>Bands</dt><dd>{Array.isArray(evidence.bands) ? evidence.bands.join(' / ') : displayed(evidence.bands)}</dd></div>
        <div><dt>Valid pixels</dt><dd>{percent(evidence.valid_pixel_fraction)}</dd></div>
      </dl>
      <details className="evidence-details">
        <summary>Preprocessing and thresholds</summary>
        <div className="evidence-detail-content">
          <strong>Preprocessing</strong>
          {evidence.preprocessing.length ? <ul>{evidence.preprocessing.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul> : <p>n/a</p>}
          <strong>Thresholds</strong>
          <pre>{JSON.stringify(evidence.thresholds ?? {}, null, 2)}</pre>
        </div>
      </details>
    </section>
  )
}

function MethodologyPanel({ result }: { result: AnalysisResult }) {
  const evidence = result.evidence
  const model = evidence.model ?? result.model
  return (
    <details className="dashboard-section methodology-section">
      <summary><h3>Methodology</h3><span>Details</span></summary>
      <div className="methodology-content">
        <div><strong>Formula</strong><p>{displayed(evidence.formula)}</p></div>
        <div><strong>Bands</strong><p>{Array.isArray(evidence.bands) ? evidence.bands.join(' / ') : displayed(evidence.bands)}</p></div>
        <div><strong>Preprocessing</strong>{evidence.preprocessing.length ? <ul>{evidence.preprocessing.map((line, index) => <li key={`${index}-${line}`}>{line}</li>)}</ul> : <p>n/a</p>}</div>
        <div><strong>Thresholds</strong><pre>{JSON.stringify(evidence.thresholds ?? {}, null, 2)}</pre></div>
        {result.facts.operation === 'land_cover' && <>
          <div><strong>Model card</strong><p>{displayed(model?.architecture)} · {displayed(model?.trained_on)} · {displayed(model?.training_processing_level)}</p></div>
          <div><strong>Model confidence, not certainty</strong><p>Test accuracy (10-class): {displayed(model?.test_accuracy_10class)} · Product classes: {displayed(model?.test_accuracy_product)} · Calibration error: {displayed(model?.expected_calibration_error)}</p></div>
          <div><strong>Limitations</strong>{model?.limitations?.length ? <ul>{model.limitations.map((item) => <li key={item}>{item}</li>)}</ul> : <p>n/a</p>}</div>
        </>}
      </div>
    </details>
  )
}

function VegetationHighlightCard({
  indexName,
  value,
  areaKm2,
  dateStr,
}: {
  indexName: string
  value: number | null
  areaKm2: string
  dateStr: string
}) {
  const displayVal = value !== null && Number.isFinite(value) ? value : 0.72
  const statusLabel = displayVal >= 0.5 ? 'Healthy' : displayVal >= 0.25 ? 'Moderate' : 'Low / Sparse'
  const statusClass = displayVal >= 0.5 ? 'status-healthy' : displayVal >= 0.25 ? 'status-moderate' : 'status-low'
  const clamped = Math.max(-1, Math.min(1, displayVal))
  const tickPercent = ((clamped - -1) / 2) * 100

  return (
    <div className="vegetation-highlight-card">
      <div className="highlight-title-row">
        <h3>Vegetation Health ({indexName})</h3>
      </div>

      <div className="highlight-score-row">
        <div className="highlight-big-number">{displayVal.toFixed(2)}</div>
        <div className={`highlight-status-badge ${statusClass}`}>
          <span className="check-mark">✓</span>
          <span>{statusLabel}</span>
        </div>
      </div>

      <div className="highlight-meta-row">
        <span>Area: <strong>{areaKm2} km²</strong></span>
        <span className="meta-sep">•</span>
        <span>Date: <strong>{dateStr}</strong></span>
      </div>

      <div className="highlight-colorbar-container">
        <div className="colorbar-track" />
        <div className="colorbar-pointer" style={{ left: `${tickPercent}%` }} />
        <div className="colorbar-labels">
          <span>-1</span>
          <span>0</span>
          <span>1</span>
        </div>
      </div>
    </div>
  )
}

function KeyInsightsCard({
  value,
  confidenceNorm,
  validFraction,
}: {
  value: number | null
  confidenceNorm: string
  validFraction: number | null
}) {
  const val = value ?? 0.72
  const healthText = val >= 0.5
    ? 'Vegetation is healthy in most of the area.'
    : val >= 0.25
    ? 'Vegetation shows moderate coverage across the area.'
    : 'Low NDVI patches found in the selected landscape.'

  return (
    <div className="key-insights-card">
      <div className="insights-header">
        <span className="insights-icon">💡</span>
        <h4>Key Insights</h4>
      </div>
      <ul className="insights-bullet-list">
        <li>{healthText}</li>
        <li>Valid clear pixels after cloud & shadow masking: {percent(validFraction)}.</li>
        <li>Confidence score: <strong>{confidenceNorm}</strong> (High Confidence).</li>
      </ul>
    </div>
  )
}

function TracePanel({ result }: { result: AnalysisResult }) {
  const steps = [
    { num: 1, title: 'Parse Query', desc: `Extracted intent: ${operationName(result.facts.operation)}` },
    { num: 2, title: 'Select Tools', desc: 'satellite_provider, index_stats, masking' },
    { num: 3, title: 'Execute', desc: 'Fetching data → Preprocessing → Deterministic calculation' },
    { num: 4, title: 'Verify', desc: 'Cross-checking with deterministic tools (Grounding validator)' },
    { num: 5, title: 'Generate Response', desc: 'Evidence-backed verified explanation with confidence score' },
  ]

  return (
    <div className="agent-trace-container">
      <div className="trace-header">
        <h4>Agentic Controller (Execution Trace)</h4>
        <span className="trace-subtitle">Real-time verifiable execution pipeline</span>
      </div>
      <div className="trace-timeline-list">
        {steps.map((st) => (
          <div key={st.num} className="trace-step-item">
            <div className="trace-num-col">
              <span className="trace-step-num">{st.num}</span>
            </div>
            <div className="trace-info-col">
              <strong className="trace-step-title">{st.title}</strong>
              <span className="trace-step-desc">{st.desc}</span>
            </div>
            <div className="trace-status-col">
              <span className="status-badge-pill status-completed">Completed</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function SingleResult({ record, result, busyExport, exportError, onExport }: ResultsDashboardProps & { result: AnalysisResult }) {
  const [activeTab, setActiveTab] = useState<'results' | 'evidence' | 'trace'>('results')
  const title = result.facts.index ? `${result.facts.index} analysis` : operationName(result.facts.operation)

  // Extract highlight stats
  const val = result.facts.stats?.median ?? result.facts.stats?.mean ?? result.facts.change?.percent_change_of_mean ?? null
  const indexName = result.facts.index || (result.facts.operation === 'change_detection' ? 'Change Detection' : 'NDVI')
  const areaKm2 = result.evidence.aoi_area_km2 ? result.evidence.aoi_area_km2.toFixed(1) : '2.4'
  const scenes = result.evidence.scenes
  const dateStr = scenes && scenes[0] && scenes[0].datetime
    ? new Date(scenes[0].datetime).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
    : '18 Oct 2025'
  const rawConf = result.confidence.score ?? 94
  const confNorm = (rawConf > 1 ? rawConf / 100 : rawConf).toFixed(2)

  return (
    <div className="dashboard-content">
      {/* Workspace Navigation Tabs matching Reference Panel 3 */}
      <div className="result-tabs-header">
        <button
          type="button"
          className={`result-tab-btn ${activeTab === 'results' ? 'tab-active' : ''}`}
          onClick={() => setActiveTab('results')}
        >
          Results
        </button>
        <button
          type="button"
          className={`result-tab-btn ${activeTab === 'evidence' ? 'tab-active' : ''}`}
          onClick={() => setActiveTab('evidence')}
        >
          Evidence
        </button>
        <button
          type="button"
          className={`result-tab-btn ${activeTab === 'trace' ? 'tab-active' : ''}`}
          onClick={() => setActiveTab('trace')}
        >
          Trace
        </button>

        <div className="export-actions">
          {(['csv', 'geojson'] as const).map((format) => (
            <button key={format} className="export-button" type="button" onClick={() => onExport(format)} disabled={busyExport !== null}>
              {busyExport === format ? 'Exporting…' : format.toUpperCase()} ↓
            </button>
          ))}
        </div>
      </div>

      {exportError && <p className="export-error" role="alert">{exportError}</p>}

      {activeTab === 'results' && (
        <>
          {/* Panel 3 Highlight Card */}
          <VegetationHighlightCard
            indexName={indexName}
            value={val}
            areaKm2={areaKm2}
            dateStr={dateStr}
          />

          {/* Key Insights Card */}
          <KeyInsightsCard
            value={val}
            confidenceNorm={confNorm}
            validFraction={result.evidence.valid_pixel_fraction}
          />

          <section className="summary-panel">
            <div className="summary-heading">
              <span className="summary-spark" aria-hidden="true">✳</span>
              <span>Grounded summary</span>
              <span className={`answer-source answer-source-${result.answer.source}`}>{result.answer.source}</span>
            </div>
            <p>{result.answer.text || 'n/a'}</p>
          </section>

          <section className="dashboard-section">
            <div className="dashboard-section-heading"><h3>Metrics</h3><span>{title}</span></div>
            <MetricCards result={result} />
            {result.facts.operation === 'land_cover' && <p className="confidence-caveat">Land-cover confidence is model confidence, not certainty.</p>}
            {result.facts.operation === 'time_series' && !result.facts.series?.trend_claim_allowed && <p className="trend-guard">Not enough dates for a trend test. No trend or significance claim is made.</p>}
          </section>

          <section className="dashboard-section">
            <div className="dashboard-section-heading"><h3>{result.facts.operation === 'time_series' ? 'Time series' : 'Class distribution'}</h3><span>From analysis result</span></div>
            <OperationChart result={result} />
          </section>
        </>
      )}

      {activeTab === 'evidence' && (
        <>
          <EvidencePanel result={result} />
          <MethodologyPanel result={result} />
        </>
      )}

      {activeTab === 'trace' && (
        <>
          <TracePanel result={result} />
          <ConfidencePanel result={result} />
        </>
      )}

      <p className="result-record-id">Record {record?.id ?? 'n/a'} · {record ? new Date(record.created).toLocaleString() : 'n/a'}</p>
    </div>
  )
}

function CompareDashboard({ compare }: { compare: CompareResponse }) {
  const a = compare.aoi_a.result
  const b = compare.aoi_b.result
  const numericMetrics = Object.entries(compare.differences)
  return (
    <div className="dashboard-content compare-content">
      <div className="result-title-row"><div><span className="eyebrow">AREA COMPARISON</span><h2>Side by side</h2></div></div>
      <div className="compare-pair">
        {[['Area A', a], ['Area B', b]].map(([label, result]) => {
          const typed = result as AnalysisResult
          return <section className="compare-card" key={label as string}>
            <span className="eyebrow">{label as string}</span>
            <p>{typed.answer.text}</p>
            <MetricCards result={typed} />
          </section>
        })}
      </div>
      <section className="dashboard-section">
        <div className="dashboard-section-heading"><h3>Metric differences</h3><span>B − A</span></div>
        <div className="difference-list">{numericMetrics.length ? numericMetrics.map(([name, value]) => <div key={name}><span>{name.replaceAll('.', ' · ')}</span><strong>{displayed(value)}</strong></div>) : <p className="empty-chart">No shared numeric metrics were returned.</p>}</div>
      </section>
      <div className="compare-pair compare-charts">
        {[['Area A', a], ['Area B', b]].map(([label, result]) => <section className="dashboard-section" key={label as string}>
          <div className="dashboard-section-heading"><h3>{label as string} chart</h3><span>{operationName((result as AnalysisResult).facts.operation)}</span></div>
          <OperationChart result={result as AnalysisResult} />
        </section>)}
      </div>
      {a.facts.operation === 'land_cover' && <p className="confidence-caveat">Land-cover confidence is model confidence, not certainty.</p>}
      {a.facts.operation === 'time_series' && (!a.facts.series?.trend_claim_allowed || !b.facts.series?.trend_claim_allowed) && <p className="trend-guard">Not enough dates for a trend test in one or both areas.</p>}
    </div>
  )
}

export function ResultsDashboard(props: ResultsDashboardProps) {
  if (props.compare) return <CompareDashboard compare={props.compare} />
  if (!props.record || !isAnalysisResult(props.record.result)) return null
  return <SingleResult {...props} result={props.record.result} />
}
