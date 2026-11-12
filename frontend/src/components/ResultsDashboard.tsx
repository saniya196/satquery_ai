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
import { getLayerUrl } from '../api/client'
import { downloadAnalysisPdf, downloadComparePdf } from '../utils/pdfReport'

interface ResultsDashboardProps {
  record: HistoryRecord | null
  compare: CompareResponse | null
  busyExport: string | null
  exportError: string | null
  onExport: (format: 'csv' | 'geojson') => void
}

const CHART_COLORS = ['#8fd8a2', '#f0b45c', '#e88a72', '#5fb3d4', '#9aa8c9', '#a58ab8']
const CHANGE_CLASS_COLORS: Record<string, string> = {
  significant_decrease: '#e05252', // red — decreased
  moderate_decrease: '#ef8a8a',
  stable: '#8b96a5', // grey — little or no change
  moderate_increase: '#7fd694',
  significant_increase: '#4ec66a', // green — increased
}
const AXIS_TICK = { fontSize: 9, fill: '#8b9cb3' } as const
const TOOLTIP_STYLE = {
  background: 'rgba(13, 21, 34, 0.96)',
  border: '1px solid #2d4059',
  borderRadius: 8,
  color: '#e8eef5',
  fontSize: 11,
  boxShadow: '0 8px 24px rgba(0, 0, 0, 0.45)',
} as const

export function displayed(value: unknown, digits = 3): string {
  if (value === null || value === undefined || value === '') return 'n/a'
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) : 'n/a'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

export function percent(value: unknown, alreadyPercent = false): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a'
  if (alreadyPercent) return `${value.toFixed(1)}%`
  return `${(value * 100).toFixed(1)}%`
}

function isAnalysisResult(value: HistoryRecord['result']): value is AnalysisResult {
  return Boolean(value && typeof value === 'object' && 'facts' in value && 'evidence' in value)
}

function operationName(value: string) {
  return value.replaceAll('_', ' ')
}

function resultText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function analysisLabel(result: AnalysisResult): string {
  const index = result.facts.index ?? (typeof result.evidence.index === 'string' ? result.evidence.index : null)
  if (result.facts.operation === 'change_detection') return `${friendlyIndexName(index) ?? 'Index'} change detection`
  if (result.facts.operation === 'index_stats') return `${friendlyIndexName(index) ?? 'Index'} statistics`
  if (result.facts.operation === 'time_series') return `${friendlyIndexName(index) ?? 'Index'} time series`
  return 'Land-cover classification'
}

function ExecutiveSummary({ record, result }: { record: HistoryRecord; result: AnalysisResult }) {
  const query = record.structured_query
  const aoiName = resultText(query.aoi_name) ?? resultText(query.place_name) ?? resultText(query.location) ?? 'Selected area'
  const dates = result.evidence.scenes.map((scene) => scene.datetime).filter(Boolean)
  const dateA = result.facts.date_a ?? dates[0] ?? null
  const dateB = result.facts.date_b ?? dates[1] ?? null
  const observationDates = dateA && dateB && dateA !== dateB
    ? `${formatObservationDate(dateA)} → ${formatObservationDate(dateB)}`
    : dateA ? formatObservationDate(dateA) : 'Dates unavailable'
  const change = result.facts.change
  const primaryMetrics = result.facts.operation === 'change_detection' && change
    ? [
      ['Baseline mean', displayed(change.mean_a), dateA ? formatObservationDate(dateA) : ''],
      ['Comparison mean', displayed(change.mean_b), dateB ? formatObservationDate(dateB) : ''],
      ['Mean change', displayed(change.mean_change), 'index units'],
      ['Usable pixels', percent(result.evidence.valid_pixel_fraction), 'after masking'],
    ]
    : [
      ['Selected area', displayed(result.evidence.aoi_area_km2, 2), 'km²'],
      ['Usable pixels', percent(result.evidence.valid_pixel_fraction), 'after masking'],
      ['Data quality score', result.confidence.score === null ? 'n/a' : displayed(result.confidence.score, 1), 'system score / 100'],
      ['Scenes used', displayed(result.evidence.scenes.length, 0), 'Sentinel-2 scenes'],
    ]

  return (
    <section className="executive-summary" aria-labelledby="executive-summary-title">
      <div className="executive-summary-heading">
        <div>
          <span className="eyebrow">EXECUTIVE SUMMARY</span>
          <h1 id="executive-summary-title">{analysisLabel(result)}</h1>
          <p>Measured satellite findings for <strong>{aoiName}</strong>. Values below are returned by the deterministic analysis pipeline.</p>
        </div>
        <div className="summary-context">
          <span>{observationDates}</span>
          <strong>{displayed(result.evidence.aoi_area_km2, 2)} km² AOI</strong>
        </div>
      </div>
      <div className="executive-metadata">
        <span><b>Analysis</b>{analysisLabel(result)}</span>
        <span><b>Observations</b>{observationDates}</span>
        <span><b>Evidence</b>{result.evidence.scenes.length} real Sentinel-2 scene{result.evidence.scenes.length === 1 ? '' : 's'}</span>
      </div>
      <div className="executive-metrics">
        {primaryMetrics.map(([label, value, note]) => (
          <div className="executive-metric" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
            <small>{note}</small>
          </div>
        ))}
      </div>
      <div className="measured-badge"><span aria-hidden="true">●</span> Measured values <em>AI explanation is shown separately below</em></div>
    </section>
  )
}

function DerivedLayerPanel({ record, result }: { record: HistoryRecord; result: AnalysisResult }) {
  const [available, setAvailable] = useState(true)
  const layer = result.facts.operation === 'change_detection' ? 'diff' : result.facts.operation === 'land_cover' ? 'classes' : 'index'
  const label = result.facts.operation === 'change_detection' ? 'Derived change layer' : 'Derived analysis layer'
  return (
    <section className="dashboard-section derived-layer-section">
      <div className="dashboard-section-heading">
        <div><h3>{label}</h3><p className="section-subtitle">Server-rendered from the actual analysis result</p></div>
        <span>{result.evidence.scenes.length} observation{result.evidence.scenes.length === 1 ? '' : 's'}</span>
      </div>
      {available ? (
        <div className="derived-layer-layout">
          <figure className="derived-layer-figure">
            <img
              src={getLayerUrl(record.id, layer)}
              alt={`${label} for the selected AOI`}
              onError={() => setAvailable(false)}
            />
            <figcaption>{result.facts.operation === 'change_detection' ? 'Difference layer: red indicates decrease, green indicates increase.' : 'Rendered analysis layer for the selected AOI.'}</figcaption>
          </figure>
          <div className="observation-pair">
            <h4>Observation dates</h4>
            {result.evidence.scenes.map((scene) => (
              <div className="observation-row" key={`${scene.item_id}-${scene.datetime}`}>
                <span>{safeDateLabel(scene.datetime) ?? scene.datetime}</span>
                <strong>{scene.item_id}</strong>
                <small>{scene.cloud_cover === null ? 'Cloud cover n/a' : `${displayed(scene.cloud_cover, 1)}% cloud cover`}</small>
              </div>
            ))}
            <p className="coverage-note">Raw Sentinel-2 RGB previews are not returned by the current analysis response. This view shows the available server-rendered analysis layer instead of a placeholder image.</p>
          </div>
        </div>
      ) : (
        <p className="empty-chart">No server-rendered layer is available for this completed result. The measured values and scene evidence remain available.</p>
      )}
    </section>
  )
}

function HotspotPanel({ result }: { result: AnalysisResult }) {
  const hotspots = result.hotspots ?? []
  const [selectedId, setSelectedId] = useState<string | number | null>(hotspots[0] ? (hotspots[0].id as string | number) : null)
  if (hotspots.length === 0) return null
  const selected = hotspots.find((hotspot) => hotspot.id === selectedId) ?? hotspots[0]
  return (
    <section className="dashboard-section hotspot-results-section">
      <div className="dashboard-section-heading"><div><h3>Highlighted areas</h3><p className="section-subtitle">Measured spatial clusters returned by the change analysis</p></div><span>{hotspots.length} cluster{hotspots.length === 1 ? '' : 's'}</span></div>
      <div className="hotspot-results-layout">
        <div className="hotspot-result-list" role="list" aria-label="Change hotspots">
          {hotspots.map((hotspot, index) => (
            <button type="button" className={`hotspot-result-item ${hotspot.id === selected.id ? 'hotspot-result-selected' : ''}`} key={String(hotspot.id ?? index)} onClick={() => setSelectedId(hotspot.id as string | number)}>
              <span>Hotspot {index + 1}</span>
              <strong>{friendlyClassName(String(hotspot.class ?? hotspot.direction ?? 'change'))}</strong>
              <small>{typeof hotspot.area_km2 === 'number' ? `${displayed(hotspot.area_km2, 2)} km² affected` : 'Area not returned'}</small>
            </button>
          ))}
        </div>
        <div className="hotspot-detail">
          <span className="eyebrow">SELECTED HOTSPOT</span>
          <h4>{friendlyClassName(String(selected.class ?? selected.direction ?? 'Change'))}</h4>
          <dl>
            <div><dt>Area</dt><dd>{typeof selected.area_km2 === 'number' ? `${displayed(selected.area_km2, 2)} km²` : 'Not returned'}</dd></div>
            <div><dt>Pixels</dt><dd>{typeof selected.pixels === 'number' ? displayed(selected.pixels, 0) : 'Not returned'}</dd></div>
            <div><dt>Mean difference</dt><dd>{typeof selected.mean_diff === 'number' ? displayed(selected.mean_diff) : 'Not returned'}</dd></div>
          </dl>
          <p className="coverage-note">Hotspot measurements identify spatial clusters in the returned index difference. They do not establish the cause of change.</p>
        </div>
      </div>
    </section>
  )
}

function questionFocus(query: string, result: AnalysisResult): string {
  const text = query.toLowerCase()
  const index = result.facts.index ?? (typeof result.evidence.index === 'string' ? result.evidence.index : null)
  if (/(vegetation|green|ndvi|plant|crop)/.test(text)) return 'Vegetation evidence'
  if (/(water|wetland|ndwi|mndwi|river|lake)/.test(text)) return 'Water evidence'
  if (/(built|urban|city|development|ndbi)/.test(text)) return 'Built-up evidence'
  return index ? `${friendlyIndexName(index) ?? index} evidence` : 'Returned satellite evidence'
}

function AiAnalysisPanel({ record, result }: { record: HistoryRecord; result: AnalysisResult }) {
  const score = result.confidence.score
  const hasScore = typeof score === 'number' && Number.isFinite(score)
  const scorePercent = hasScore ? (score > 1 ? score : score * 100) : null
  const focus = questionFocus(record.query, result)
  const limitation = result.facts.operation === 'time_series' && !result.facts.series?.trend_claim_allowed
    ? 'There are not enough usable observation dates for a reliable trend claim.'
    : result.evidence.valid_pixel_fraction !== null && result.evidence.valid_pixel_fraction < 0.7
      ? 'Some pixels were excluded by masking, so the result should be treated with added caution.'
      : null

  return (
    <section className="ai-analysis-panel" aria-labelledby="ai-analysis-title">
      <div className="ai-analysis-heading">
        <div>
          <span className="eyebrow">AI ANALYSIS</span>
          <h3 id="ai-analysis-title">What the returned evidence indicates</h3>
          <p>Interpretation of measured satellite results for <strong>{focus}</strong>. The AI does not add measurements beyond the evidence below.</p>
        </div>
        {hasScore && scorePercent !== null && (
          <div className={`ai-confidence-badge ${scorePercent < 60 ? 'ai-confidence-low' : ''}`}>
            <span>System confidence</span>
            <strong>{scorePercent.toFixed(0)}%</strong>
          </div>
        )}
      </div>
      <p className="ai-analysis-answer">{result.answer.text || 'No interpretation was returned. Review the measured values and evidence details below.'}</p>
      <div className="ai-analysis-footer">
        <span className={`answer-source answer-source-${result.answer.source}`}>Explanation method: {result.answer.source}</span>
        {hasScore && scorePercent !== null
          ? <span>{scorePercent < 60 ? 'Lower confidence: review masking, coverage, and scene details.' : 'Confidence reflects the system’s returned data-quality factors, not verified real-world accuracy.'}</span>
          : <span>Confidence was not returned for this analysis.</span>}
      </div>
      {limitation && <p className="ai-analysis-limitation">{limitation}</p>}
    </section>
  )
}

const INDEX_FRIENDLY: Record<string, { name: string; plain: string }> = {
  NDVI: { name: 'Greenery', plain: 'A measure related to green vegetation (how much healthy plant cover appears in the image).' },
  NDWI: { name: 'Water', plain: 'A measure related to surface water presence.' },
  MNDWI: { name: 'Water', plain: 'A measure related to surface water presence (modified water index).' },
  NDBI: { name: 'Built-up areas', plain: 'A measure related to built-up or developed surfaces.' },
  SAVI: { name: 'Vegetation (soil-adjusted)', plain: 'A measure related to vegetation that adjusts for soil brightness.' },
  EVI: { name: 'Vegetation', plain: 'A measure related to vegetation (enhanced vegetation index).' },
}

export function friendlyIndexName(index: string | null | undefined): string | null {
  if (!index) return null
  const info = INDEX_FRIENDLY[index.toUpperCase()]
  return info ? `${info.name} (${index})` : index
}

export function indexPlainExplanation(index: string | null | undefined): string | null {
  if (!index) return null
  return INDEX_FRIENDLY[index.toUpperCase()]?.plain ?? `A satellite-derived index (${index}) calculated from image bands.`
}

const CLASS_LABELS: Record<string, string> = {
  significant_decrease: 'Significant decrease (red)',
  moderate_decrease: 'Moderate decrease (red)',
  stable: 'Little or no change (grey)',
  moderate_increase: 'Moderate increase (green)',
  significant_increase: 'Significant increase (green)',
  vegetation: 'Vegetation',
  water: 'Water',
  bare_soil: 'Bare soil',
  built_up: 'Built-up areas',
  cropland: 'Cropland',
  forest: 'Forest',
  grassland: 'Grassland',
  shrubland: 'Shrubland',
  wetland: 'Wetland',
}

function friendlyClassName(name: string, compact = false): string {
  const base = CLASS_LABELS[name] ?? operationName(name)
  if (!compact) return base
  const short: Record<string, string> = {
    'Significant decrease (red)': 'Sig. decrease ↓',
    'Moderate decrease (red)': 'Mod. decrease ↓',
    'Significant increase (green)': 'Sig. increase ↑',
    'Moderate increase (green)': 'Mod. increase ↑',
    'Little or no change (grey)': 'Little/no change',
  }
  return short[base] ?? (base.length > 16 ? `${base.slice(0, 15)}…` : base)
}

function ClassChart({ result, compact = false }: { result: AnalysisResult; compact?: boolean }) {
  const facts = result.facts
  const classes = facts.change?.classes ?? facts.classes ?? {}
  const data = Object.entries(classes).map(([name, metrics]) => {
    const metric = metrics as ChangeClassMetric | LandCoverClassMetric
    const value = 'fraction_of_valid' in metric ? metric.fraction_of_valid : metric.fraction
    const pct = typeof value === 'number' && Number.isFinite(value) ? value * 100 : null
    return { key: name, name: friendlyClassName(name, compact), fullName: CLASS_LABELS[name] ?? operationName(name), value: pct }
  }).filter((item) => item.value !== null)

  const height = compact ? 210 : 230
  const bottom = compact ? 52 : 40
  const angle = compact ? -35 : -25
  const isChange = facts.operation === 'change_detection'
  const shareLabel = facts.operation === 'land_cover'
    ? 'Share of classified area'
    : 'Share of valid pixels'

  return (
    <div className="chart-frame">
      {isChange && data.length > 0 && (
        <p className="chart-accessibility-note">Change categories (also shown by text): green = increased, red = decreased, grey = little or no change. These are measured index-class changes, not direct proof of cause or land-cover area.</p>
      )}
      {data.length === 0 ? <p className="empty-chart">No class breakdown was returned for this result.</p> : (
        <ResponsiveContainer width="100%" height={height}>
          <BarChart data={data} margin={{ top: 8, right: 8, bottom, left: compact ? -14 : -10 }}>
            <CartesianGrid stroke="#22344d" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: compact ? 8 : 9, fill: AXIS_TICK.fill }} interval={0} angle={angle} textAnchor="end" height={compact ? 72 : 65} />
            <YAxis tick={{ fontSize: compact ? 8 : 9, fill: AXIS_TICK.fill }} unit="%" width={compact ? 28 : 34} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              cursor={{ fill: 'rgba(53, 213, 242, 0.06)' }}
              labelFormatter={(_, payload) => {
                const p = payload?.[0]?.payload as { fullName?: string } | undefined
                return p?.fullName ?? ''
              }}
              formatter={(value: any) => [`${displayed(value, 1)}%`, shareLabel]}
            />
            <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={compact ? 28 : 38}>
              {data.map((item, index) => <Cell key={item.key} fill={CHANGE_CLASS_COLORS[item.key] ?? CHART_COLORS[index % CHART_COLORS.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

export function formatObservationDate(date: string): string {
  const parsed = Date.parse(date)
  if (Number.isNaN(parsed)) return date || 'Unknown date'
  return new Date(parsed).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function formatObservationTick(value: number, fallbackDates: string[]): string {
  if (!Number.isFinite(value)) return ''
  const idx = Math.round(value)
  // categorical fallback mode uses integer index as x
  if (idx >= 0 && idx < fallbackDates.length && Math.abs(value - idx) < 1e-6) {
    const d = fallbackDates[idx]
    return d ? d.slice(5, 10) : ''
  }
  return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function TimeSeriesChart({ result, compact = false }: { result: AnalysisResult; compact?: boolean }) {
  const series = result.facts.series
  const anomalies = new Set(series?.anomaly_indices ?? [])
  const dates = series?.dates ?? []
  const timestamps = dates.map((d) => {
    const t = Date.parse(d)
    return Number.isFinite(t) ? t : null
  })
  const hasValidTimeAxis = dates.length > 0 && timestamps.every((t): t is number => t !== null)

  const data = dates.map((date, index) => {
    const time = timestamps[index]
    return {
      // x: numeric timestamp for proportional spacing; fallback to index preserves order without inventing dates
      x: hasValidTimeAxis && time !== null ? time : index,
      date, // original date string preserved
      value: series?.values?.[index] ?? null, // original value preserved
      rolling: series?.rolling_mean_3?.[index] ?? null,
      anomaly: anomalies.has(index) ? (series?.values?.[index] ?? null) : null,
    }
  })

  const hasObsSummary = series && (
    typeof series.n_dates_requested === 'number' ||
    typeof series.n_dates_included === 'number' ||
    typeof series.n_dates_skipped_low_valid === 'number' ||
    typeof series.n_dates_skipped_load_error === 'number'
  )
  const xDomain: [number | 'dataMin', number | 'dataMax'] = hasValidTimeAxis ? ['dataMin', 'dataMax'] : [0, Math.max(0, dates.length - 1)]

  return (
    <div className="chart-frame">
      {data.length < 1 ? <p className="empty-chart">No date-series values in this result.</p> : (
        <ResponsiveContainer width="100%" height={compact ? 190 : 205}>
          <ComposedChart data={data} margin={{ top: 8, right: 6, bottom: 2, left: compact ? -24 : -20 }}>
            <CartesianGrid stroke="#22344d" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="x"
              type="number"
              scale={hasValidTimeAxis ? 'time' : 'linear'}
              domain={xDomain}
              tick={{ fontSize: compact ? 8 : 9, fill: AXIS_TICK.fill }}
              minTickGap={compact ? 18 : 12}
              tickFormatter={(v) => formatObservationTick(Number(v), dates)}
            />
            <YAxis tick={{ fontSize: compact ? 8 : 9, fill: AXIS_TICK.fill }} domain={['auto', 'auto']} width={compact ? 28 : 34} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              cursor={{ stroke: 'rgba(53, 213, 242, 0.25)' }}
              labelFormatter={(label, payload) => {
                const p = payload?.[0]?.payload as { date?: string } | undefined
                return formatObservationDate(p?.date ?? String(label))
              }}
              formatter={(value: any, name: any) => [displayed(value, 3), name === 'value' ? 'AOI median' : name === 'rolling' ? 'Rolling mean (3)' : name === 'anomaly' ? 'Anomaly' : String(name ?? '')]}
            />
            <Line type="monotone" dataKey="value" name="AOI median" stroke="#5fd3a1" strokeWidth={2} dot={false} connectNulls />
            <Line type="monotone" dataKey="rolling" name="Rolling mean (3)" stroke="#f0b45c" strokeWidth={1.5} dot={false} connectNulls />
            <Scatter dataKey="anomaly" name="Anomaly" fill="#f87171" shape="circle" />
          </ComposedChart>
        </ResponsiveContainer>
      )}
      {!hasValidTimeAxis && data.length > 0 && <p className="gap-note">Actual observation dates were unavailable for proportional spacing; observations are shown in original order.</p>}
      {data.length > 0 && <p className="gap-note">Gaps show dates without usable observations (not interpolated values).</p>}
      {hasObsSummary && (
        <p className="observation-summary" title="Skipped observations are excluded from the series; values are not interpolated or replaced.">
          Observations: requested {series?.n_dates_requested ?? 'n/a'}, included {series?.n_dates_included ?? series?.n_dates_usable ?? 'n/a'}, skipped (low valid pixels) {series?.n_dates_skipped_low_valid ?? 'n/a'}, skipped (load failed) {series?.n_dates_skipped_load_error ?? 'n/a'}.
        </p>
      )}
      {!series?.trend_claim_allowed && <p className="trend-guard">Not enough dates for a trend test</p>}
    </div>
  )
}

export function OperationChart({ result, compact = false }: { result: AnalysisResult; compact?: boolean }) {
  if (result.facts.operation === 'time_series') return <TimeSeriesChart result={result} compact={compact} />
  if (result.facts.operation === 'change_detection' || result.facts.operation === 'land_cover') return <ClassChart result={result} compact={compact} />
  return <p className="empty-chart">No chart is defined for this operation.</p>
}

export function MetricCards({ result }: { result: AnalysisResult }) {
  const { facts, evidence } = result
  const idx = friendlyIndexName(facts.index ?? evidence.index as string | null) ?? 'index'
  let entries: Array<[string, unknown, 'number' | 'percent' | 'percent_already']> = []
  if (facts.operation === 'change_detection') {
    entries = [
      [`Baseline average ${idx}`, facts.change?.mean_a, 'number'],
      [`Comparison average ${idx}`, facts.change?.mean_b, 'number'],
      ['Average change (index units)', facts.change?.mean_change, 'number'],
      ['Relative change (of baseline mean)', facts.change?.percent_change_of_mean, 'percent_already'],
    ]
  } else if (facts.operation === 'index_stats') {
    entries = [
      [`Average ${idx}`, facts.stats?.mean, 'number'],
      [`Middle value (median) ${idx}`, facts.stats?.median, 'number'],
      ['Lowest value', facts.stats?.min, 'number'],
      ['Highest value', facts.stats?.max, 'number'],
    ]
  } else if (facts.operation === 'time_series') {
    entries = [
      ['Observation dates used in trend test', facts.series?.trend_test?.n ?? facts.series?.dates.length ?? null, 'number'],
      ['Yearly rate (Sen’s slope)', facts.series?.sens_slope_per_year, 'number'],
      ['Trend test result', facts.series?.trend_test?.trend ?? (facts.series?.trend_claim_allowed ? null : 'Not enough dates'), 'number'],
      ['Usable image pixels', evidence.valid_pixel_fraction, 'percent'],
    ]
  } else {
    entries = [
      ['Largest predicted class', facts.dominant_class ? friendlyClassName(String(facts.dominant_class)) : facts.dominant_class, 'number'],
      ['Largest class share of classified area', facts.dominant_fraction, 'percent'],
      ['AOI area classified', facts.classified_fraction, 'percent'],
      ['Average model confidence (prediction)', facts.mean_model_confidence, 'percent'],
    ]
  }

  return <div className="metrics-grid">{entries.map(([label, value, style]) => (
    <div className="metric-card" key={label}>
      <span>{label}</span>
      <strong>{style === 'percent' ? percent(value) : style === 'percent_already' ? percent(value, true) : displayed(value)}</strong>
    </div>
  ))}</div>
}

export function DataQualitySection({ result }: { result: AnalysisResult }) {
  const { evidence, facts } = result
  const coverage = evidence.coverage || (result as any).coverage
  const vp = evidence.valid_pixel_fraction
  const clouds = evidence.scenes.map((s) => s.cloud_cover).filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
  const avgCloud = clouds.length ? clouds.reduce((a, b) => a + b, 0) / clouds.length : null
  const s = facts.series
  const hasSeries = facts.operation === 'time_series' && s
  const usableObs = s?.n_dates_included ?? s?.n_dates_usable ?? (s?.dates?.length ?? null)
  return (
    <section className="dashboard-section">
      <div className="dashboard-section-heading"><h3>Data quality &amp; uncertainty</h3><span>Based on available image data</span></div>
      <ul className="compare-summary-list">
        <li><strong>Usable imagery in selected area:</strong> {typeof vp === 'number' ? `${percent(vp)} of pixels were usable after masking (clear data).` : 'Not available.'}{typeof vp === 'number' && vp < 0.7 ? ' Clouds or missing observations may have reduced usable data.' : ''}</li>
        <li><strong>Scene coverage:</strong> {coverage ? `${coverage.status === 'full' ? 'Full coverage of the selected area' : coverage.status === 'partial' ? 'Partial coverage of the selected area' : 'Coverage status unknown'}${typeof coverage.fraction === 'number' && Number.isFinite(coverage.fraction) ? ` (about ${(coverage.fraction * 100).toFixed(1)}% footprint coverage)` : ''}.` : 'Not available.'} {coverage?.status === 'partial' ? 'Measurements may represent only the covered portion.' : ''}</li>
        <li><strong>Cloud information:</strong> {avgCloud !== null ? `Average reported cloud cover across scenes: ${avgCloud.toFixed(1)}%.` : 'Cloud cover details were not fully available for all scenes.'} See the scene table below for per-image details.</li>
        {hasSeries && <li><strong>Observation coverage (time series):</strong> {usableObs !== null ? `${usableObs} observation date(s) included` : 'Observation count unavailable'}{typeof s?.n_dates_requested === 'number' ? ` out of ${s.n_dates_requested} requested` : ''}. {s?.trend_claim_allowed ? 'There were enough usable dates for the trend test shown (if any).' : 'There were not enough usable observations for a reliable trend claim.'}</li>}
      </ul>
      <p className="confidence-caveat">Data quality describes the available imagery and analysis conditions. It is different from a model’s prediction confidence and different from verified real-world accuracy.</p>
    </section>
  )
}

export function ConfidencePanel({ result }: { result: AnalysisResult }) {
  return (
    <section className="dashboard-section">
      <div className="dashboard-section-heading"><h3>Data quality factors (system score)</h3><span>{displayed(result.confidence.score, 1)}{result.confidence.score === null ? '' : '/100'}</span></div>
      <p className="confidence-caveat">This score is calculated from available data/analysis factors returned by the system. It is not a verified accuracy rating and should not be read as High/Medium/Low unless such categories are explicitly provided by the data source (not shown here).</p>
      {result.facts.operation === 'land_cover' && <p className="confidence-caveat">For land cover, also check “Average model confidence (prediction)” in measured values. Model confidence is different from verified accuracy.</p>}
      <div className="confidence-list">
        {(result.confidence.breakdown ?? []).map((factor, index) => (
          <div className="confidence-row" key={`${factor.factor}-${index}`}>
            <div className="confidence-row-top"><strong>{operationName(factor.factor)}</strong><span>{displayed(factor.score, 1)}</span></div>
            <div className="confidence-track"><span style={{ width: `${Math.max(0, Math.min(100, factor.score ?? 0))}%` }} /></div>
            <p>{factor.explanation}</p>
          </div>
        ))}
        {result.confidence.breakdown.length === 0 && <p className="empty-chart">No data quality factors were returned.</p>}
      </div>
    </section>
  )
}

export function EvidencePanel({ result }: { result: AnalysisResult }) {
  const evidence = result.evidence
  const coverage = evidence.coverage || (result as any).coverage
  return (
    <section className="dashboard-section">
      <div className="dashboard-section-heading"><h3>Images and measurements used</h3><span>{evidence.scenes.length} scene{evidence.scenes.length === 1 ? '' : 's'}</span></div>
      <div className="table-scroll">
        <table className="scene-table">
          <thead><tr><th>Image (scene ID)</th><th>Date</th><th>Cloud cover</th><th>Resolution</th></tr></thead>
          <tbody>{evidence.scenes.map((scene) => (
            <tr key={`${scene.item_id}-${scene.datetime}`}>
              <td title={scene.item_id}>{scene.item_id}</td>
              <td>{scene.datetime ? safeDateLabel(scene.datetime) ?? scene.datetime : 'n/a'}</td>
              <td>{scene.cloud_cover === null ? 'n/a' : `${displayed(scene.cloud_cover, 1)}%`}</td>
              <td>{scene.resolution_m === null ? 'n/a' : `${displayed(scene.resolution_m, 1)} m`}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <dl className="evidence-list">
        <div><dt>Selected area size</dt><dd>{evidence.aoi_area_km2 === null ? 'n/a' : `${displayed(evidence.aoi_area_km2)} km²`}</dd></div>
        <div><dt>Measured indicator</dt><dd>{friendlyIndexName(evidence.index as string | null) ?? displayed(evidence.index)}</dd></div>
        <div><dt>Image bands used</dt><dd>{Array.isArray(evidence.bands) ? evidence.bands.join(', ') : displayed(evidence.bands)}</dd></div>
        <div><dt>Usable pixels (after masking)</dt><dd>{percent(evidence.valid_pixel_fraction)}</dd></div>
        <div><dt>Image coverage of selected area</dt><dd title="How much of the selected area the image footprint covers (different from usable pixels after cloud/mask removal)">{coverage ? `${coverage.status === 'full' ? 'Full' : coverage.status === 'partial' ? 'Partial' : 'Unknown'}${typeof coverage.fraction === 'number' && Number.isFinite(coverage.fraction) ? ` (about ${(coverage.fraction * 100).toFixed(1)}%)` : ''}` : 'n/a'}</dd></div>
      </dl>
      {coverage?.status === 'partial' && (
        <p className="coverage-note">Partial image coverage: measurements may represent only the part of the selected area covered by the image.</p>
      )}
      <details className="evidence-details">
        <summary>Technical details (processing and thresholds)</summary>
        <div className="evidence-detail-content">
          <strong>Indicator (technical)</strong>
          <p>{displayed(evidence.index)}</p>
          <strong>Preprocessing steps</strong>
          {evidence.preprocessing.length ? <ul>{evidence.preprocessing.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul> : <p>n/a</p>}
          <strong>Thresholds (as returned)</strong>
          <pre>{JSON.stringify(evidence.thresholds ?? {}, null, 2)}</pre>
        </div>
      </details>
    </section>
  )
}

export function MethodologyPanel({ result }: { result: AnalysisResult }) {
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

const SUPPORTED_HEALTH_INDICES = new Set(['NDVI', 'SAVI', 'EVI'])

export function safeDateLabel(value: string | null | undefined): string | null {
  if (!value) return null
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

function VegetationHighlightCard({
  indexName,
  value,
  areaKm2,
  dateStr,
  result,
}: {
  indexName: string | null
  value: number | null
  areaKm2: string | null
  dateStr: string | null
  result?: AnalysisResult | null
}) {
  const idxLabel = friendlyIndexName(indexName) ?? (indexName ?? 'Index')
  const idxPlain = indexPlainExplanation(indexName)

  if (result?.facts.operation === 'change_detection') {
    const change = result.facts.change
    const pct = change?.percent_change_of_mean
    const pctStr = typeof pct === 'number' && Number.isFinite(pct) ? `${pct.toFixed(1)}%` : 'n/a'
    const baseline = change?.mean_a !== null && change?.mean_a !== undefined ? change.mean_a.toLocaleString(undefined, { maximumFractionDigits: 3 }) : 'n/a'
    const comparison = change?.mean_b !== null && change?.mean_b !== undefined ? change.mean_b.toLocaleString(undefined, { maximumFractionDigits: 3 }) : 'n/a'
    const meanCh = change?.mean_change !== null && change?.mean_change !== undefined ? change.mean_change.toLocaleString(undefined, { maximumFractionDigits: 3 }) : 'n/a'
    const dateA = safeDateLabel(result.facts.date_a) ?? safeDateLabel(result.evidence.scenes[0]?.datetime)
    const dateB = safeDateLabel(result.facts.date_b) ?? safeDateLabel(result.evidence.scenes[1]?.datetime)
    const meanChange = typeof change?.mean_change === 'number' && Number.isFinite(change.mean_change) ? change.mean_change : null
    const direction = meanChange === null ? 'Change (value unavailable)' : meanChange > 0 ? 'Measured index increased' : meanChange < 0 ? 'Measured index decreased' : 'Little or no measured change'
    return (
      <div className="vegetation-highlight-card">
        <div className="highlight-title-row">
          <h3>Change summary: {idxLabel}</h3>
        </div>
        {idxPlain && <p className="highlight-explain">{idxPlain} This shows a measured change in the index value, not a direct measurement of tree count, land area lost, or cause.</p>}
        <div className="highlight-score-row">
          <div className={`highlight-big-number ${meanChange !== null && meanChange >= 0 ? 'change-positive' : 'change-negative'}`}>{pctStr}</div>
          <div className="highlight-status-badge">
            <span>{direction}</span>
          </div>
        </div>
        <p className="highlight-explain">Relative change shown is the percent change of the baseline mean (as returned by the analysis).</p>
        <div className="change-metrics-grid">
          <div className="change-metric">
            <span className="change-metric-label">Baseline value{dateA ? ` (${dateA})` : ''}</span>
            <strong className="change-metric-value">{baseline}</strong>
          </div>
          <div className="change-metric">
            <span className="change-metric-label">Comparison value{dateB ? ` (${dateB})` : ''}</span>
            <strong className="change-metric-value">{comparison}</strong>
          </div>
          <div className="change-metric">
            <span className="change-metric-label">Mean change (index units)</span>
            <strong className={`change-metric-value ${meanChange !== null && meanChange >= 0 ? 'change-positive' : 'change-negative'}`}>{meanCh}</strong>
          </div>
          <div className="change-metric">
            <span className="change-metric-label">Selected area</span>
            <strong className="change-metric-value">{areaKm2 ?? 'n/a'} km²</strong>
          </div>
        </div>
        <details className="evidence-details"><summary>Technical details</summary><div className="evidence-detail-content"><p><strong>Index:</strong> {indexName ?? 'n/a'}</p></div></details>
      </div>
    )
  }

  if (value === null || !Number.isFinite(value) || areaKm2 === null || dateStr === null) {
    return (
      <div className="vegetation-highlight-card">
        <div className="highlight-title-row"><h3>Summary</h3></div>
        <p className="empty-chart">Summary values are unavailable for this result. The available measurements are shown in the sections below when present.</p>
      </div>
    )
  }

  const displayVal = value
  const upper = (indexName ?? '').toUpperCase()
  const supportsHealth = SUPPORTED_HEALTH_INDICES.has(upper)

  if (!supportsHealth) {
    return (
      <div className="vegetation-highlight-card">
        <div className="highlight-title-row"><h3>Summary: {idxLabel}</h3></div>
        {idxPlain && <p className="highlight-explain">{idxPlain}</p>}
        <div className="highlight-score-row">
          <div className="highlight-big-number">{displayVal.toLocaleString(undefined, { maximumFractionDigits: 3 })}</div>
        </div>
        <p className="highlight-explain">This is the measured index value for the selected area and date. It is not a count of plants or a direct area measurement.</p>
        <div className="highlight-meta-row">
          <span>Selected area: <strong>{areaKm2} km²</strong></span>
          <span className="meta-sep">•</span>
          <span>Date: <strong>{dateStr}</strong></span>
        </div>
        {indexName && <details className="evidence-details"><summary>Technical details</summary><div className="evidence-detail-content"><p><strong>Index:</strong> {indexName}</p></div></details>}
      </div>
    )
  }

  const statusLabel = displayVal >= 0.5 ? 'Higher vegetation index' : displayVal >= 0.25 ? 'Moderate vegetation index' : displayVal < 0 ? 'Negative index value' : 'Lower vegetation index'
  const statusClass = displayVal >= 0.5 ? 'status-healthy' : displayVal >= 0.25 ? 'status-moderate' : 'status-low'
  const clamped = Math.max(-1, Math.min(1, displayVal))
  const tickPercent = ((clamped + 1) / 2) * 100

  return (
    <div className="vegetation-highlight-card">
      <div className="highlight-title-row"><h3>Summary: {idxLabel}</h3></div>
      {idxPlain && <p className="highlight-explain">{idxPlain}</p>}
      <div className="highlight-score-row">
        <div className="highlight-big-number">{displayVal.toLocaleString(undefined, { maximumFractionDigits: 3 })}</div>
        <div className={`highlight-status-badge ${statusClass}`}>
          <span>{statusLabel}</span>
        </div>
      </div>
      <p className="highlight-explain">This is a measured vegetation index value for the selected area and date. It helps indicate vegetation greenness in the image, but it does not directly measure the number of plants or the area of tree cover.</p>
      <div className="highlight-meta-row">
        <span>Selected area: <strong>{areaKm2} km²</strong></span>
        <span className="meta-sep">•</span>
        <span>Date: <strong>{dateStr}</strong></span>
      </div>
      <div className="highlight-colorbar-container" aria-label="Index scale from -1 to 1">
        <div className="colorbar-track" />
        <div className="colorbar-pointer" style={{ left: `${tickPercent}%` }} />
        <div className="colorbar-labels"><span>-1</span><span>0</span><span>1</span></div>
      </div>
      {indexName && <details className="evidence-details"><summary>Technical details</summary><div className="evidence-detail-content"><p><strong>Index:</strong> {indexName}</p></div></details>}
    </div>
  )
}

function KeyInsightsCard({
  value,
  confidenceNorm,
  validFraction,
  operation,
  indexName,
  changeFacts,
  dateA,
  dateB,
  result,
}: {
  value: number | null
  confidenceNorm: string
  validFraction: number | null
  operation: string
  indexName: string | null
  changeFacts?: import('../types/analysis').ChangeFacts | null
  dateA?: string | null
  dateB?: string | null
  result?: AnalysisResult | null
}) {
  const bullets: string[] = []
  const friendly = friendlyIndexName(indexName) ?? indexName
  if (value !== null && Number.isFinite(value)) {
    if (operation === 'index_stats') {
      bullets.push(friendly ? `Measured ${friendly} value (median/mean as reported): ${value.toLocaleString(undefined, { maximumFractionDigits: 3 })}.` : `Measured index value (median/mean as reported): ${value.toLocaleString(undefined, { maximumFractionDigits: 3 })}.`)
    } else if (operation === 'change_detection') {
      if (changeFacts) {
        const pct = changeFacts.percent_change_of_mean
        const pctStr = typeof pct === 'number' && Number.isFinite(pct) ? `${pct.toFixed(1)}%` : 'n/a'
        bullets.push(`Measured ${friendly ?? 'index'} values: baseline ${changeFacts.mean_a !== null && changeFacts.mean_a !== undefined ? changeFacts.mean_a.toLocaleString(undefined, { maximumFractionDigits: 3 }) : 'n/a'}${dateA ? ` (${dateA})` : ''}, comparison ${changeFacts.mean_b !== null && changeFacts.mean_b !== undefined ? changeFacts.mean_b.toLocaleString(undefined, { maximumFractionDigits: 3 }) : 'n/a'}${dateB ? ` (${dateB})` : ''}. Mean change ${changeFacts.mean_change !== null && changeFacts.mean_change !== undefined ? changeFacts.mean_change.toLocaleString(undefined, { maximumFractionDigits: 3 }) : 'n/a'} (relative change of baseline mean: ${pctStr}).`)
      } else {
        bullets.push(`Measured mean change reported: ${value.toLocaleString(undefined, { maximumFractionDigits: 3 })} (index units).`)
      }
    } else if (operation === 'time_series') {
      bullets.push(`Time-series values are shown below using the measurements returned by the analysis.`)
    } else if (operation === 'land_cover') {
      const dom = result?.facts.dominant_class ? friendlyClassName(String(result.facts.dominant_class)) : null
      bullets.push(dom ? `Land-cover model result: largest class is ${dom} (based on model classification).` : 'Land-cover results come from a model classification of the image.')
    } else {
      bullets.push(`Reported value: ${value.toLocaleString(undefined, { maximumFractionDigits: 3 })}.`)
    }
  } else if (operation !== 'time_series' && operation !== 'land_cover') {
    bullets.push('A primary numeric summary was not available for this result. See the detailed measurements below.')
  }
  if (validFraction !== null && Number.isFinite(validFraction)) {
    const vp = validFraction * 100
    const note = vp < 50 ? ' Clouds or missing observations may have reduced usable data.' : vp < 80 ? ' Some pixels were excluded (for example, clouds or missing data).' : ''
    bullets.push(`Usable image pixels in the selected area (after masking): ${percent(validFraction)}.${note}`)
  } else {
    bullets.push('Usable-pixel information was not available for this result.')
  }
  if (confidenceNorm !== 'n/a') {
    bullets.push(`Data quality summary score (0–1 scale shown): ${confidenceNorm}. This reflects data/analysis factors returned by the system, not verified real-world accuracy.`)
  } else {
    bullets.push('A data quality summary score was not available for this result.')
  }

  return (
    <div className="key-insights-card">
      <div className="insights-header">
        <span className="insights-icon" aria-hidden="true">💡</span>
        <h4>Key details (from this analysis)</h4>
      </div>
      <ul className="insights-bullet-list">
        {bullets.map((bullet, index) => (
          <li key={`${index}-${bullet}`}>{bullet}</li>
        ))}
      </ul>
    </div>
  )
}

export function whatThisMeansLines(result: AnalysisResult): { lines: string[]; insufficient: boolean } {
  const { facts, evidence } = result
  const idx = friendlyIndexName(facts.index ?? evidence.index as string | null) ?? 'the measured indicator'
  const coverage = evidence.coverage || (result as any).coverage
  const vp = evidence.valid_pixel_fraction
  const lines: string[] = []
  let insufficient = false

  if (facts.operation === 'change_detection' && facts.change) {
    const c = facts.change
    const da = safeDateLabel(facts.date_a) ?? safeDateLabel(evidence.scenes[0]?.datetime) ?? 'the baseline date'
    const db = safeDateLabel(facts.date_b) ?? safeDateLabel(evidence.scenes[1]?.datetime) ?? 'the comparison date'
    const meanA = c.mean_a
    const meanB = c.mean_b
    const meanCh = c.mean_change
    const pct = c.percent_change_of_mean
    if (typeof meanA === 'number' && typeof meanB === 'number' && typeof meanCh === 'number') {
      const dir = meanCh > 0 ? 'increased' : meanCh < 0 ? 'decreased' : 'showed little or no net change'
      const pctTxt = typeof pct === 'number' && Number.isFinite(pct) ? ` (${pct.toFixed(1)}% relative to the baseline mean, as returned)` : ''
      lines.push(`Between ${da} and ${db}, the measured ${idx} value for the selected area ${dir}: baseline mean ${meanA.toLocaleString(undefined, { maximumFractionDigits: 3 })}, comparison mean ${meanB.toLocaleString(undefined, { maximumFractionDigits: 3 })}, mean change ${meanCh.toLocaleString(undefined, { maximumFractionDigits: 3 })}${pctTxt}.`)
      lines.push('This describes a change in the satellite index measurement. It does not directly prove the cause (such as rainfall, farming, or construction) and it does not directly measure tree count or hectares of loss.')
    } else {
      insufficient = true
      lines.push('The change values needed to explain this result clearly were not fully available.')
    }
  } else if (facts.operation === 'index_stats') {
    const date = safeDateLabel(facts.date) ?? safeDateLabel(evidence.scenes[0]?.datetime)
    const mean = facts.stats?.mean
    const median = facts.stats?.median
    if (typeof mean === 'number' || typeof median === 'number') {
      const parts = [typeof median === 'number' ? `median ${median.toLocaleString(undefined, { maximumFractionDigits: 3 })}` : null, typeof mean === 'number' ? `mean ${mean.toLocaleString(undefined, { maximumFractionDigits: 3 })}` : null].filter(Boolean).join(', ')
      lines.push(`For the selected area${date ? ` on ${date}` : ''}, the measured ${idx} value is ${parts}.`)
      lines.push('This is an index value from the satellite image. Higher or lower values can be related to what the index measures (for example, greenery or water), but the value is not a direct count of plants or a direct land-area measurement.')
    } else {
      insufficient = true
      lines.push('The index statistics needed to explain this result clearly were not fully available.')
    }
  } else if (facts.operation === 'time_series') {
    const s = facts.series
    if (s?.trend_claim_allowed && s.trend_test?.trend) {
      const slope = typeof s.sens_slope_per_year === 'number' ? ` (Sen’s slope about ${s.sens_slope_per_year.toLocaleString(undefined, { maximumFractionDigits: 4 })} per year, as returned)` : ''
      lines.push(`Across the available observation dates, the analysis reports a trend test result: ${String(s.trend_test.trend)}${slope}.`)
      lines.push('This is a statistical result from the available measurements. It does not identify the cause of any change.')
    } else if (s?.insufficient_observations || !s?.trend_claim_allowed) {
      insufficient = true
      lines.push('There are not enough usable observation dates to make a reliable trend claim for this time series. The chart below shows the available measurements only.')
    } else {
      lines.push('The time series shows the measured values returned for the selected area over time. Look at the dates and values in the chart for the actual observations.')
    }
  } else if (facts.operation === 'land_cover') {
    const dom = facts.dominant_class ? friendlyClassName(String(facts.dominant_class)) : null
    const share = typeof facts.dominant_fraction === 'number' && Number.isFinite(facts.dominant_fraction)
      ? percent(facts.dominant_fraction)
      : null
    const classified = typeof facts.classified_fraction === 'number' && Number.isFinite(facts.classified_fraction)
      ? percent(facts.classified_fraction)
      : null
    if (dom) {
      lines.push(`Among the classified area, ${dom} was the largest class${share ? ` (about ${share} of classified area)` : ''}.`)
    } else {
      lines.push('The model produced land-cover classification results for the selected area.')
    }
    if (classified) lines.push(`The classified pixels cover about ${classified} of the entire area of interest.`)
    lines.push('Land-cover results are model predictions based on the image. They show model confidence, not verified real-world accuracy or certainty.')
  }

  if (typeof vp === 'number' && Number.isFinite(vp) && vp < 0.7) {
    lines.push(`Note: only about ${percent(vp)} of the selected area had usable image pixels after masking. Clouds or missing observations may affect the result.`)
    insufficient = insufficient || vp < 0.4
  }
  if (coverage?.status === 'partial') {
    lines.push('Note: image coverage was partial for the selected area, so measurements may represent only the covered portion.')
    insufficient = true
  }
  if (lines.length === 0) {
    insufficient = true
    lines.push('There is not enough information in this result to provide a clear plain-language explanation. The measured values and evidence are shown below.')
  }
  return { lines, insufficient }
}

function WhatThisMeansSection({ result }: { result: AnalysisResult }) {
  const { lines, insufficient } = whatThisMeansLines(result)
  return (
    <section className="dashboard-section what-this-means-section">
      <div className="dashboard-section-heading"><h3>What this means</h3><span>Plain-language summary from measured values</span></div>
      {insufficient && <p className="coverage-note">Some evidence is limited. Read the details below before drawing conclusions.</p>}
      <ul className="compare-summary-list">
        {lines.map((line, i) => <li key={`${i}-${line.slice(0, 24)}`}>{line}</li>)}
      </ul>
    </section>
  )
}

function TracePanel({ result }: { result: AnalysisResult }) {
  // Backend AnalysisResult does not expose per-step trace data.
  // Only report overall completion if the result object is present and validated as a result.
  void result

  return (
    <div className="agent-trace-container">
      <div className="trace-header">
        <h4>Execution Trace</h4>
        <span className="trace-subtitle">Overall execution status</span>
      </div>
      <div className="trace-timeline-list">
        <div className="trace-step-item">
          <div className="trace-num-col">
            <span className="trace-step-num">•</span>
          </div>
          <div className="trace-info-col">
            <strong className="trace-step-title">Analysis completed</strong>
            <span className="trace-step-desc">Result returned from completed analysis.</span>
          </div>
        </div>
      </div>
    </div>
  )
}

function SingleResult({ record, result, busyExport, exportError, onExport }: ResultsDashboardProps & { result: AnalysisResult }) {
  const [activeTab, setActiveTab] = useState<'results' | 'evidence' | 'trace'>('results')
  const [pdfBusy, setPdfBusy] = useState(false)
  const [pdfError, setPdfError] = useState<string | null>(null)
  const indexName = result.facts.index ?? (typeof result.evidence.index === 'string' ? result.evidence.index : null)
  const friendlyTitle = indexName ? friendlyIndexName(indexName) : null
  const title = friendlyTitle ? `${friendlyTitle} analysis` : operationName(result.facts.operation)

  const val = result.facts.stats?.median
  ?? result.facts.stats?.mean
  ?? result.facts.change?.mean_change
  ?? null
  const areaKm2 = typeof result.evidence.aoi_area_km2 === 'number' && Number.isFinite(result.evidence.aoi_area_km2) ? result.evidence.aoi_area_km2.toFixed(1) : null
  const scenes = result.evidence.scenes
  const dateStr = scenes && scenes.length > 0 && scenes[0]?.datetime
    ? safeDateLabel(scenes[0].datetime)
    : null
  const rawConf = result.confidence.score
  const confNorm = typeof rawConf === 'number' && Number.isFinite(rawConf) ? (rawConf > 1 ? (rawConf / 100).toFixed(2) : rawConf.toFixed(2)) : 'n/a'

  return (
    <div className="dashboard-content">
      {record && <ExecutiveSummary record={record} result={result} />}
      {record && <DerivedLayerPanel record={record} result={result} />}
      <HotspotPanel result={result} />
      {record && <AiAnalysisPanel record={record} result={result} />}
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
          Evidence &amp; data
        </button>
        <button
          type="button"
          className={`result-tab-btn ${activeTab === 'trace' ? 'tab-active' : ''}`}
          onClick={() => setActiveTab('trace')}
        >
          Details
        </button>

        <div className="export-actions">
          {(['csv', 'geojson'] as const).map((format) => (
            <button key={format} className="export-button" type="button" onClick={() => onExport(format)} disabled={busyExport !== null} title={`Download ${format.toUpperCase()} export`}>
              {busyExport === format ? 'Exporting…' : format.toUpperCase()} ↓
            </button>
          ))}
          {record && (
            <button
              className="export-button"
              type="button"
              onClick={() => { void (async () => { try { setPdfBusy(true); setPdfError(null); await downloadAnalysisPdf(record) } catch (e) { setPdfError(e instanceof Error ? e.message : 'PDF export failed.') } finally { setPdfBusy(false) } })() }}
              disabled={busyExport !== null || pdfBusy}
              title="Download PDF report (from actual stored analysis data)"
            >
              {pdfBusy ? 'Building PDF…' : 'PDF'} ↓
            </button>
          )}
        </div>
      </div>

      {(exportError || pdfError) && <p className="export-error" role="alert">{exportError || pdfError}</p>}

      {activeTab === 'results' && (
        <>
          <VegetationHighlightCard
            indexName={indexName}
            value={val}
            areaKm2={areaKm2}
            dateStr={dateStr}
            result={result}
          />

          <WhatThisMeansSection result={result} />

          <KeyInsightsCard
            value={val}
            confidenceNorm={confNorm}
            validFraction={result.evidence.valid_pixel_fraction}
            operation={result.facts.operation}
            indexName={indexName}
            changeFacts={result.facts.change}
            dateA={result.facts.date_a ?? null}
            dateB={result.facts.date_b ?? null}
            result={result}
          />

          <section className="dashboard-section">
            <div className="dashboard-section-heading"><h3>Measured values</h3><span>{title}</span></div>
            <MetricCards result={result} />
            {result.facts.operation === 'land_cover' && <p className="confidence-caveat">Land-cover results are model predictions. The model’s confidence is not the same as verified real-world accuracy or certainty.</p>}
            {result.facts.operation === 'time_series' && !result.facts.series?.trend_claim_allowed && <p className="trend-guard">Not enough usable observation dates for a reliable trend test. No trend or significance claim is made.</p>}
          </section>

          <section className="dashboard-section">
            <div className="dashboard-section-heading"><h3>{result.facts.operation === 'time_series' ? 'Values over time' : result.facts.operation === 'change_detection' ? 'Change by category' : 'Breakdown by category'}</h3><span>From measured/classified results</span></div>
            <OperationChart result={result} />
          </section>
        </>
      )}

      {activeTab === 'evidence' && (
        <>
          <DataQualitySection result={result} />
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

type CompareMetricRow = {
  key: string
  label: string
  a: string
  b: string
  diff: string
  note?: string
}

function fmtNum(value: unknown, digits = 3, unit = ''): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a'
  const n = value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 })
  return unit ? `${n} ${unit}` : n
}

function fmtPctValue(value: unknown, digits = 1, alreadyPercent = false): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a'
  const v = alreadyPercent ? value : value * 100
  return `${v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 })}%`
}

function fmtSignedNum(value: unknown, digits = 3, unit = ''): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a'
  const sign = value > 0 ? '+' : ''
  const n = value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 })
  return unit ? `${sign}${n} ${unit}` : `${sign}${n}`
}

function fmtSignedPctValue(value: unknown, digits = 1, alreadyPercent = false): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a'
  const v = alreadyPercent ? value : value * 100
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 })}%`
}

function getDiff(differences: Record<string, number>, key: string): number | null {
  const v = differences[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function changeClassMetric(facts: AnalysisResult['facts'], key: string): ChangeClassMetric | null {
  const cls = facts.change?.classes?.[key]
  if (!cls || typeof cls !== 'object') return null
  return cls as ChangeClassMetric
}

function buildCompareMetricRows(compare: CompareResponse): CompareMetricRow[] {
  const a = compare.aoi_a.result
  const b = compare.aoi_b.result
  const d = compare.differences
  const rows: CompareMetricRow[] = []
  const index = a.facts.index || b.facts.index || a.evidence.index || b.evidence.index
  const indexLabel = typeof index === 'string' && index ? (friendlyIndexName(index) ?? index) : 'measured indicator'
  const op = a.facts.operation

  if (op === 'change_detection' && (a.facts.change || b.facts.change)) {
    rows.push({
      key: 'baseline_mean',
      label: `Baseline mean ${indexLabel}`,
      a: fmtNum(a.facts.change?.mean_a),
      b: fmtNum(b.facts.change?.mean_a),
      diff: fmtSignedNum(getDiff(d, 'change.mean_a')),
    })
    rows.push({
      key: 'comparison_mean',
      label: `Comparison mean ${indexLabel}`,
      a: fmtNum(a.facts.change?.mean_b),
      b: fmtNum(b.facts.change?.mean_b),
      diff: fmtSignedNum(getDiff(d, 'change.mean_b')),
    })
    rows.push({
      key: 'mean_change',
      label: `Mean ${indexLabel} change`,
      a: fmtNum(a.facts.change?.mean_change),
      b: fmtNum(b.facts.change?.mean_change),
      diff: fmtSignedNum(getDiff(d, 'change.mean_change')),
    })
    rows.push({
      key: 'relative_change',
      label: 'Relative change',
      a: fmtPctValue(a.facts.change?.percent_change_of_mean, 1, true),
      b: fmtPctValue(b.facts.change?.percent_change_of_mean, 1, true),
      diff: fmtSignedPctValue(getDiff(d, 'change.percent_change_of_mean'), 1, true),
      note: 'Percent change of baseline mean (as returned).',
    })
    for (const [clsKey, label] of [
      ['significant_decrease', 'Significant decrease (share of valid pixels)'],
      ['significant_increase', 'Significant increase (share of valid pixels)'],
      ['stable', 'Little or no change (share of valid pixels)'],
    ] as const) {
      const ca = changeClassMetric(a.facts, clsKey)
      const cb = changeClassMetric(b.facts, clsKey)
      if (ca || cb) {
        rows.push({
          key: `class_${clsKey}`,
          label,
          a: `${fmtPctValue(ca?.fraction_of_valid)}${typeof ca?.area_km2 === 'number' ? ` (${fmtNum(ca.area_km2, 2, 'km²')})` : ''}`,
          b: `${fmtPctValue(cb?.fraction_of_valid)}${typeof cb?.area_km2 === 'number' ? ` (${fmtNum(cb.area_km2, 2, 'km²')})` : ''}`,
          diff: fmtSignedPctValue(getDiff(d, `change.classes.${clsKey}.fraction_of_valid`)),
          note: 'Share of usable (valid) pixels in this category; area shown where available. Red = decrease, green = increase, grey = little/no change (by category). B−A is the difference in share.',
        })
      }
    }
  } else if (op === 'index_stats') {
    rows.push({
      key: 'mean_index',
      label: `Mean ${indexLabel}`,
      a: fmtNum(a.facts.stats?.mean),
      b: fmtNum(b.facts.stats?.mean),
      diff: fmtSignedNum(getDiff(d, 'stats.mean')),
    })
    rows.push({
      key: 'median_index',
      label: `Median ${indexLabel}`,
      a: fmtNum(a.facts.stats?.median),
      b: fmtNum(b.facts.stats?.median),
      diff: fmtSignedNum(getDiff(d, 'stats.median')),
    })
    rows.push({
      key: 'valid_pixels',
      label: 'Valid pixels',
      a: fmtPctValue(a.facts.stats?.valid_fraction ?? a.evidence.valid_pixel_fraction),
      b: fmtPctValue(b.facts.stats?.valid_fraction ?? b.evidence.valid_pixel_fraction),
      diff: fmtSignedPctValue(getDiff(d, 'stats.valid_fraction')),
    })
  } else if (op === 'land_cover') {
    rows.push({
      key: 'dominant_class',
      label: 'Dominant class',
      a: String(a.facts.dominant_class ?? 'n/a'),
      b: String(b.facts.dominant_class ?? 'n/a'),
      diff: a.facts.dominant_class === b.facts.dominant_class ? 'Same' : 'Different',
    })
    rows.push({
      key: 'dominant_share',
      label: 'Dominant class share',
      a: fmtPctValue(a.facts.dominant_fraction),
      b: fmtPctValue(b.facts.dominant_fraction),
      diff: fmtSignedPctValue(getDiff(d, 'dominant_fraction')),
    })
  } else if (op === 'time_series') {
    rows.push({
      key: 'sens_slope',
      label: 'Sen’s slope (per year)',
      a: fmtNum(a.facts.series?.sens_slope_per_year),
      b: fmtNum(b.facts.series?.sens_slope_per_year),
      diff: fmtSignedNum(getDiff(d, 'series.sens_slope_per_year')),
    })
    rows.push({
      key: 'trend',
      label: 'Trend test',
      a: String(a.facts.series?.trend_test?.trend ?? (a.facts.series?.trend_claim_allowed ? 'n/a' : 'Not enough dates')),
      b: String(b.facts.series?.trend_test?.trend ?? (b.facts.series?.trend_claim_allowed ? 'n/a' : 'Not enough dates')),
      diff: '—',
      note: 'Trend tests are area-specific; no numeric B−A difference is shown.',
    })
  }

  // Always-prioritized common metrics (when present in responses)
  rows.push({
    key: 'data_quality',
    label: 'Data quality score (system-calculated)',
    a: fmtNum(a.confidence?.score, 1, '/100'),
    b: fmtNum(b.confidence?.score, 1, '/100'),
    diff: fmtSignedNum(getDiff(d, 'data_quality_score') ?? getDiff(d, 'confidence.score'), 1),
    note: 'Reflects data/analysis factors returned by the system, not verified real-world accuracy.',
  })
  rows.push({
    key: 'aoi_area',
    label: 'Selected area size',
    a: fmtNum(a.evidence?.aoi_area_km2, 2, 'km²'),
    b: fmtNum(b.evidence?.aoi_area_km2, 2, 'km²'),
    diff: fmtSignedNum(getDiff(d, 'evidence.aoi_area_km2') ?? getDiff(d, 'aoi_area_km2'), 2, 'km²'),
    note: 'Area sizes may differ; interpret area-dependent metrics using shares/percentages where shown.',
  })

  // Raw pixel counts: show with denominators, not as blindly comparable equivalents.
  const nValidA = (a.facts as any)?.stats?.n_valid
  const nValidB = (b.facts as any)?.stats?.n_valid
  const nTotalA = (a.facts as any)?.stats?.n_total ?? (a.facts as any)?.stats?.n_aoi_pixels
  const nTotalB = (b.facts as any)?.stats?.n_total ?? (b.facts as any)?.stats?.n_aoi_pixels
  if (typeof nValidA === 'number' || typeof nValidB === 'number') {
    rows.push({
      key: 'pixel_counts',
      label: 'Valid pixel counts',
      a: typeof nValidA === 'number' ? `${fmtNum(nValidA, 0)}${typeof nTotalA === 'number' ? ` / ${fmtNum(nTotalA, 0)}` : ''}` : 'n/a',
      b: typeof nValidB === 'number' ? `${fmtNum(nValidB, 0)}${typeof nTotalB === 'number' ? ` / ${fmtNum(nTotalB, 0)}` : ''}` : 'n/a',
      diff: fmtSignedNum(getDiff(d, 'stats.n_valid'), 0),
      note: 'Counts (valid / total where available). AOI sizes may differ, so raw counts are not directly equivalent.',
    })
  }

  return rows
}

function buildCompareSummary(compare: CompareResponse): string[] {
  const a = compare.aoi_a.result
  const b = compare.aoi_b.result
  const index = (a.facts.index || b.facts.index || a.evidence.index || b.evidence.index || 'index') as string
  const idxFriendly = friendlyIndexName(index) ?? index
  const op = a.facts.operation
  const bullets: string[] = []

  if (op === 'change_detection' && (a.facts.change || b.facts.change)) {
    const ra = a.facts.change?.percent_change_of_mean
    const rb = b.facts.change?.percent_change_of_mean
    const ma = a.facts.change?.mean_change
    const mb = b.facts.change?.mean_change
    if (typeof ra === 'number' && typeof rb === 'number' && Number.isFinite(ra) && Number.isFinite(rb)) {
      if (Math.abs(ra - rb) < 1e-9) bullets.push(`Both areas show the same relative ${idxFriendly} change (${fmtPctValue(ra, 1, true)}), based on the returned values.`)
      else bullets.push(`Area ${rb > ra ? 'B' : 'A'} shows the larger relative ${idxFriendly} change (${fmtPctValue(rb > ra ? rb : ra, 1, true)} vs ${fmtPctValue(rb > ra ? ra : rb, 1, true)}).`)
      const dir = (v: number) => v > 0 ? 'increased' : v < 0 ? 'decreased' : 'showed little or no net change'
      if ((ra > 0 && rb > 0) || (ra < 0 && rb < 0) || (ra === 0 && rb === 0)) bullets.push(`In both areas, the measured ${idxFriendly} value ${dir(ra)} (index change, not a direct measure of cause or tree/land area).`)
      else bullets.push(`Area A ${dir(ra)} while Area B ${dir(rb)} in the measured ${idxFriendly} value.`)
    } else if (typeof ma === 'number' && typeof mb === 'number' && Number.isFinite(ma) && Number.isFinite(mb)) {
      bullets.push(`Mean ${idxFriendly} change: Area A ${fmtSignedNum(ma)}, Area B ${fmtSignedNum(mb)} (B−A ${fmtSignedNum(mb - ma)}).`)
    }
    const sigDecDiff = getDiff(compare.differences, 'change.classes.significant_decrease.fraction_of_valid')
    const sigIncDiff = getDiff(compare.differences, 'change.classes.significant_increase.fraction_of_valid')
    if (typeof sigDecDiff === 'number' && Math.abs(sigDecDiff) >= 0.001) bullets.push(`The share of pixels classified as significant decrease differs by ${fmtSignedPctValue(sigDecDiff)} (B−A).`)
    if (typeof sigIncDiff === 'number' && Math.abs(sigIncDiff) >= 0.001) bullets.push(`The share of pixels classified as significant increase differs by ${fmtSignedPctValue(sigIncDiff)} (B−A).`)
  } else if (op === 'index_stats') {
    const ma = a.facts.stats?.mean
    const mb = b.facts.stats?.mean
    if (typeof ma === 'number' && typeof mb === 'number' && Number.isFinite(ma) && Number.isFinite(mb)) {
      bullets.push(`Mean ${idxFriendly}: Area A ${fmtNum(ma)}, Area B ${fmtNum(mb)} (B−A ${fmtSignedNum(mb - ma)}).`)
      if (Math.abs(mb - ma) >= 1e-9) bullets.push(`Area ${mb > ma ? 'B' : 'A'} has the higher mean ${idxFriendly} value in the returned results.`)
    }
  } else if (op === 'land_cover') {
    const da = a.facts.dominant_class ? friendlyClassName(String(a.facts.dominant_class)) : a.facts.dominant_class
    const db = b.facts.dominant_class ? friendlyClassName(String(b.facts.dominant_class)) : b.facts.dominant_class
    if (da || db) bullets.push(`Largest predicted class: Area A ${String(da ?? 'n/a')}, Area B ${String(db ?? 'n/a')}${da && db && String(a.facts.dominant_class) === String(b.facts.dominant_class) ? ' (same)' : ''}. Model predictions, not verified accuracy.`)
  } else if (op === 'time_series') {
    const sa = a.facts.series?.sens_slope_per_year
    const sb = b.facts.series?.sens_slope_per_year
    if (typeof sa === 'number' && typeof sb === 'number' && Number.isFinite(sa) && Number.isFinite(sb)) {
      bullets.push(`Yearly trend rate (Sen’s slope): Area A ${fmtNum(sa)}, Area B ${fmtNum(sb)} (B−A ${fmtSignedNum(sb - sa)}).`)
    }
  }

  const qa = a.confidence?.score
  const qb = b.confidence?.score
  if (typeof qa === 'number' && typeof qb === 'number' && Number.isFinite(qa) && Number.isFinite(qb) && Math.abs(qb - qa) >= 0.1) {
    bullets.push(`Data quality scores differ (Area A ${fmtNum(qa, 1)}/100, Area B ${fmtNum(qb, 1)}/100).`)
  }
  const aa = a.evidence?.aoi_area_km2
  const ab = b.evidence?.aoi_area_km2
  if (typeof aa === 'number' && typeof ab === 'number' && Number.isFinite(aa) && Number.isFinite(ab) && Math.abs(ab - aa) / Math.max(aa, ab, 1e-9) > 0.05) {
    bullets.push(`Selected area sizes differ (A ${fmtNum(aa, 2, 'km²')}, B ${fmtNum(ab, 2, 'km²')}); compare share-based metrics when sizes differ.`)
  }

  if (bullets.length === 0) bullets.push('No comparison summary is available from the returned metrics.')
  bullets.push('Summary is based on returned values only; it does not indicate cause.')
  return bullets
}

function compareSceneLabel(result: AnalysisResult): string {
  const scenes = result.evidence?.scenes ?? []
  if (!scenes.length) return 'No image/scene details returned'
  return scenes.map((s) => `${s.item_id}${s.datetime ? ` (${safeDateLabel(s.datetime) ?? new Date(s.datetime).toLocaleDateString()})` : ''}`).join(', ')
}

function CompareDashboard({ compare }: { compare: CompareResponse }) {
  const a = compare.aoi_a.result
  const b = compare.aoi_b.result
  const metricRows = buildCompareMetricRows(compare)
  const summary = buildCompareSummary(compare)
  const opName = operationName(a.facts.operation)
  const index = (a.facts.index || b.facts.index || a.evidence.index || b.evidence.index || '') as string
  const indexLabel = friendlyIndexName(typeof index === 'string' ? index : null) ?? index
  const [pdfBusy, setPdfBusy] = useState(false)
  const [pdfError, setPdfError] = useState<string | null>(null)

  return (
    <div className="dashboard-content compare-content">
      <div className="result-title-row compare-title-row">
        <div><span className="eyebrow">AREA COMPARISON</span><h2>{indexLabel ? `${indexLabel} comparison` : 'Comparison of two areas'}</h2></div>
        <div className="compare-title-actions">
          <span className="compare-op-badge">{opName}</span>
          <button
            className="export-button"
            type="button"
            onClick={() => { void (async () => { try { setPdfBusy(true); setPdfError(null); await downloadComparePdf(compare) } catch (e) { setPdfError(e instanceof Error ? e.message : 'PDF export failed.') } finally { setPdfBusy(false) } })() }}
            disabled={pdfBusy}
            title="Download comparison PDF report (from actual comparison data)"
          >
            {pdfBusy ? 'Building PDF…' : 'PDF'} ↓
          </button>
        </div>
      </div>
      {pdfError && <p className="export-error" role="alert">{pdfError}</p>}

      <section className="dashboard-section compare-summary-section">
        <div className="dashboard-section-heading"><h3>Comparison summary</h3><span>Based on measured values (not causes)</span></div>
        <ul className="compare-summary-list">
          {summary.map((line, i) => <li key={`${i}-${line.slice(0, 24)}`}>{line}</li>)}
        </ul>
      </section>

      <div className="compare-pair">
        {[['Area A', a] as const, ['Area B', b] as const].map(([label, result]) => (
          <section className="compare-card" key={label}>
            <div className="compare-card-header">
              <span className="eyebrow compare-area-tag">{label}</span>
              <span className="compare-area-meta" title="Selected area size and data quality score (system-calculated)">Area: {fmtNum(result.evidence?.aoi_area_km2, 2, 'km²')} · Data quality: {fmtNum(result.confidence?.score, 1, '')}/100</span>
            </div>
            <p className="compare-scene-line" title={compareSceneLabel(result)}><strong>Comparison dates/images:</strong> {compareSceneLabel(result)}</p>
            <MetricCards result={result} />
          </section>
        ))}
      </div>

      <section className="dashboard-section">
        <div className="dashboard-section-heading"><h3>Key differences</h3><span>B − A (Area B minus Area A)</span></div>
        <p className="compare-diff-note">Values shown use the actual results returned for each area. When area sizes differ, compare share/percentage metrics carefully. Missing metrics are shown as n/a. This comparison does not explain why differences occurred.</p>
        {metricRows.length ? (
          <div className="table-scroll">
            <table className="compare-diff-table">
              <thead><tr><th>Metric</th><th>Area A</th><th>Area B</th><th>Difference (B − A)</th></tr></thead>
              <tbody>
                {metricRows.map((row) => (
                  <tr key={row.key}>
                    <td>
                      <div className="compare-metric-label">{row.label}</div>
                      {row.note && <div className="compare-metric-note">{row.note}</div>}
                    </td>
                    <td>{row.a}</td>
                    <td>{row.b}</td>
                    <td className="compare-diff-value">{row.diff}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="empty-chart">No shared metrics were returned for comparison.</p>}
        {Object.keys(compare.differences || {}).length > 0 && (
          <details className="compare-raw-diffs">
            <summary>Advanced: raw backend difference fields (technical)</summary>
            <div className="difference-list compare-raw-list">
              {Object.entries(compare.differences).map(([name, value]) => <div key={name}><span>{name}</span><strong>{fmtSignedNum(value)}</strong></div>)}
            </div>
          </details>
        )}
      </section>

      <div className="compare-pair compare-charts">
        {[['Area A', a] as const, ['Area B', b] as const].map(([label, result]) => (
          <section className="dashboard-section" key={label}>
            <div className="dashboard-section-heading"><h3>{label} chart</h3><span>{friendlyIndexName(result.facts.index ?? result.evidence.index as string | null) ?? operationName(result.facts.operation)}</span></div>
            <OperationChart result={result} compact />
          </section>
        ))}
      </div>
      {a.facts.operation === 'land_cover' && <p className="confidence-caveat">Land-cover results are model predictions. Model confidence is not the same as verified real-world accuracy.</p>}
      {a.facts.operation === 'time_series' && (!a.facts.series?.trend_claim_allowed || !b.facts.series?.trend_claim_allowed) && <p className="trend-guard">Not enough usable observation dates for a reliable trend test in one or both areas.</p>}
      {indexLabel && typeof index === 'string' && index && <details className="evidence-details"><summary>Technical details</summary><div className="evidence-detail-content"><p><strong>Index:</strong> {index}</p></div></details>}
    </div>
  )
}

export function ResultsDashboard(props: ResultsDashboardProps) {
  if (props.compare) return <CompareDashboard compare={props.compare} />
  if (!props.record || !isAnalysisResult(props.record.result)) return null
  return <SingleResult {...props} result={props.record.result} />
}
