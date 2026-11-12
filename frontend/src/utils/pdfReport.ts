import { jsPDF } from 'jspdf'
import { getLayerUrl } from '../api/client'
import type { AnalysisResult, CompareResponse, HistoryRecord } from '../types/analysis'

function isAnalysisResult(value: HistoryRecord['result']): value is AnalysisResult {
  return Boolean(value && typeof value === 'object' && 'facts' in value && 'evidence' in value)
}

function safe(v: unknown, digits = 4): string {
  if (v === null || v === undefined || v === '') return 'Unavailable'
  if (typeof v === 'number') return Number.isFinite(v) ? v.toLocaleString(undefined, { maximumFractionDigits: digits }) : 'Unavailable'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (Array.isArray(v)) return v.map((x) => safe(x, digits)).join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function pct(v: unknown): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return 'Unavailable'
  return `${(v * 100).toFixed(2)}%`
}

async function tryLoadImageDataUrl(jobId: string): Promise<string | null> {
  for (const layer of ['index', 'diff', 'classes']) {
    try {
      const res = await fetch(getLayerUrl(jobId, layer), { mode: 'cors' })
      if (!res.ok) continue
      const blob = await res.blob()
      if (!blob.type.startsWith('image/')) continue
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result))
        reader.onerror = () => reject(reader.error)
        reader.readAsDataURL(blob)
      })
      return dataUrl
    } catch {
      // try next layer
    }
  }
  return null
}

function addWrapped(doc: jsPDF, text: string, x: number, y: number, maxWidth: number, lineHeight = 5): number {
  const lines = doc.splitTextToSize(text || 'Unavailable', maxWidth)
  doc.text(lines, x, y)
  return y + lines.length * lineHeight
}

function addSection(doc: jsPDF, title: string, y: number): number {
  if (y > 260) { doc.addPage(); y = 18 }
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(12)
  doc.text(title, 14, y)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(10)
  return y + 7
}

function addKv(doc: jsPDF, label: string, value: string, y: number): number {
  if (y > 270) { doc.addPage(); y = 18 }
  doc.setFont('helvetica', 'bold')
  doc.text(`${label}:`, 14, y)
  doc.setFont('helvetica', 'normal')
  return addWrapped(doc, value, 62, y, 132, 4.8)
}

function reportFromResult(doc: jsPDF, result: AnalysisResult, record: HistoryRecord | null, compareLabel?: string): number {
  let y = 18
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.text('SatQuery AI — Analysis Report', 14, y)
  y += 8
  doc.setFontSize(10)
  doc.setFont('helvetica', 'normal')
  doc.text(`Generated: ${new Date().toLocaleString()}`, 14, y)
  y += 10

  y = addSection(doc, compareLabel ? `Analysis (${compareLabel})` : 'Analysis summary', y)
  y = addKv(doc, 'Report title', 'Satellite analysis report (based on actual stored results)', y)
  if (record) {
    y = addKv(doc, 'Analysis ID', record.id, y)
    y = addKv(doc, 'Created', record.created ? new Date(record.created).toLocaleString() : 'Unavailable', y)
    y = addKv(doc, 'Status', record.status, y)
    y = addKv(doc, 'Query', record.query || 'Unavailable', y)
  }
  y = addKv(doc, 'Operation', safe(result.facts.operation), y)
  y = addKv(doc, 'Index / method', safe(result.facts.index ?? result.evidence.index), y)
  if (result.facts.date) y = addKv(doc, 'Date', safe(result.facts.date), y)
  if (result.facts.date_a || result.facts.date_b) y = addKv(doc, 'Date range', `${safe(result.facts.date_a)} to ${safe(result.facts.date_b)}`, y)
  y = addKv(doc, 'AOI area (km²)', safe(result.evidence.aoi_area_km2), y)
  if (record?.aoi?.coordinates?.[0]?.[0]) {
    const ring = record.aoi.coordinates[0]
    const lons = ring.map((c) => c[0]).filter(Number.isFinite)
    const lats = ring.map((c) => c[1]).filter(Number.isFinite)
    if (lons.length && lats.length) {
      const bounds = [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)].map((n) => n.toFixed(5)).join(', ')
      y = addKv(doc, 'AOI bounds (lon/lat)', `[${bounds}]`, y)
    }
  }
  y += 2

  y = addSection(doc, 'Computed results and statistics (actual)', y)
  const facts = result.facts as Record<string, unknown>
  const stats = facts.stats as Record<string, unknown> | undefined
  if (stats) {
    for (const [k, v] of Object.entries(stats)) y = addKv(doc, k.replaceAll('_', ' '), safe(v), y)
  }
  const change = facts.change as Record<string, unknown> | undefined
  if (change) {
    for (const [k, v] of Object.entries(change)) {
      if (k === 'classes') continue
      y = addKv(doc, k.replaceAll('_', ' '), safe(v), y)
    }
  }
  if (facts.dominant_class !== undefined) y = addKv(doc, 'Dominant class', `${safe(facts.dominant_class)} (${safe(facts.dominant_fraction)})`, y)
  if (result.facts.series) {
    const s = result.facts.series
    y = addKv(doc, 'Time series dates', s.dates?.length ? `${s.dates.length} dates` : 'Unavailable', y)
    y = addKv(doc, 'Trend test', safe(s.trend_test?.trend ?? s.status), y)
    y = addKv(doc, "Sen's slope / yr", safe(s.sens_slope_per_year), y)
  }
  y += 2

  y = addSection(doc, 'Data quality and uncertainty', y)
  y = addKv(doc, 'Valid pixel fraction', pct(result.evidence.valid_pixel_fraction), y)
  y = addKv(doc, 'Confidence score', safe(result.confidence?.score), y)
  y = addKv(doc, 'Confidence method', safe(result.confidence?.method), y)
  if (result.coverage) y = addKv(doc, 'Coverage', `${safe(result.coverage.status)} ${safe(result.coverage.fraction)} ${safe(result.coverage.note)}`.trim(), y)
  if (result.evidence.coverage) y = addKv(doc, 'Evidence coverage', `${safe(result.evidence.coverage.status)} ${safe(result.evidence.coverage.fraction)} ${safe(result.evidence.coverage.note)}`.trim(), y)
  y += 2

  y = addSection(doc, 'Evidence', y)
  y = addKv(doc, 'Scenes', result.evidence.scenes?.length ? `${result.evidence.scenes.length} scene(s): ${result.evidence.scenes.map((s) => s.datetime?.slice(0, 10) || s.item_id).join('; ')}` : 'Unavailable', y)
  y = addKv(doc, 'Bands', safe(result.evidence.bands), y)
  y = addKv(doc, 'Formula', safe(result.evidence.formula), y)
  y = addKv(doc, 'Preprocessing', result.evidence.preprocessing?.length ? result.evidence.preprocessing.join('; ') : 'Unavailable', y)
  y += 2

  if (result.hotspots && Array.isArray(result.hotspots) && result.hotspots.length > 0) {
    y = addSection(doc, 'Change hotspots (actual)', y)
    y = addWrapped(doc, `${result.hotspots.length} hotspot(s) reported. Showing up to 10.`, 14, y, 180)
    y += 2
    for (const h of result.hotspots.slice(0, 10) as Array<Record<string, unknown>>) {
      y = addWrapped(doc, `- id=${safe(h.id)} class=${safe(h.class)} pixels=${safe(h.pixels)} area_km2=${safe(h.area_km2)} mean_diff=${safe(h.mean_diff)}`, 14, y, 180, 4.5)
    }
    y += 2
  }

  y = addSection(doc, 'Explanation and limitations', y)
  y = addWrapped(doc, `System explanation (${result.answer?.source || 'unknown'}): ${result.answer?.text || 'Unavailable'}`, 14, y, 180)
  y += 3
  const limitations = [
    'This report contains only values present in the stored analysis result/evidence. Unavailable items are shown as Unavailable.',
    'Interpretation should consider data quality, cloud/valid-pixel coverage, date availability, and method limitations.',
    ...(result.evidence.model?.limitations || []),
  ]
  for (const lim of limitations) y = addWrapped(doc, `- ${lim}`, 14, y, 180, 4.5)
  return y
}

export async function downloadAnalysisPdf(record: HistoryRecord): Promise<void> {
  if (!isAnalysisResult(record.result)) {
    throw new Error('No completed analysis result is available for a PDF report.')
  }
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  let y = reportFromResult(doc, record.result, record)
  const img = await tryLoadImageDataUrl(record.id)
  if (img) {
    if (y > 180) { doc.addPage(); y = 18 }
    y = addSection(doc, 'Evidence map image (server-rendered, if available)', y)
    try {
      doc.addImage(img, 'PNG', 14, y, 120, 90, undefined, 'FAST')
      y += 94
    } catch {
      addWrapped(doc, 'Map image could not be embedded in this PDF.', 14, y, 180)
    }
  } else {
    if (y > 265) { doc.addPage(); y = 18 }
    y = addSection(doc, 'Evidence map image', y)
    addWrapped(doc, 'No server-rendered map image could be loaded for this report (unavailable or inaccessible).', 14, y, 180)
  }
  const datePart = record.created ? record.created.slice(0, 10) : new Date().toISOString().slice(0, 10)
  doc.save(`satquery-report-${record.id.slice(0, 8)}-${datePart}.pdf`)
}

export async function downloadComparePdf(compare: CompareResponse): Promise<void> {
  const a = compare.aoi_a?.result
  const b = compare.aoi_b?.result
  if (!a || !b) throw new Error('Both Area A and Area B results are required for a comparison PDF.')
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const fakeA: HistoryRecord = { id: 'A', created: new Date().toISOString(), query: String(compare.structured_query?.raw_query ?? ''), status: 'completed', operation: a.facts.operation, structured_query: compare.structured_query, aoi: { type: 'Polygon', coordinates: [] }, result: a }
  const fakeB: HistoryRecord = { id: 'B', created: fakeA.created, query: fakeA.query, status: 'completed', operation: b.facts.operation, structured_query: compare.structured_query, aoi: { type: 'Polygon', coordinates: [] }, result: b }
  reportFromResult(doc, a, fakeA, 'Area A')
  doc.addPage()
  reportFromResult(doc, b, fakeB, 'Area B')
  doc.addPage()
  let y = addSection(doc, 'Comparison differences (B − A, actual)', 18)
  for (const [k, v] of Object.entries(compare.differences || {})) y = addKv(doc, k.replaceAll('_', ' '), safe(v), y)
  y = addKv(doc, 'Generated', new Date().toLocaleString(), y + 2)
  addWrapped(doc, 'Differences are taken from the comparison response. No values were fabricated.', 14, y + 2, 180)
  doc.save(`satquery-compare-report-${new Date().toISOString().slice(0, 10)}.pdf`)
}
