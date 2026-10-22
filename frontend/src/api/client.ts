import type {
  CompareResponse,
  AoiValidationResponse,
  HistoryRecord,
  HistorySummary,
  ImageryScene,
  JobResponse,
  LayersResponse,
  PlaceSearchResult,
  PolygonGeometry,
  RunAnalysisResponse,
} from '../types/analysis'

const API_BASE = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export function getLayerUrl(jobId: string, layer: string): string {
  return `${API_BASE}/analysis/${encodeURIComponent(jobId)}/layer/${encodeURIComponent(layer)}.png`
}

export class ApiError extends Error {
  code: string
  rawMessage: string

  constructor(code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.rawMessage = message
  }
}

export function friendlyApiError(error: unknown): { message: string; suggestion: string; code?: string } {
  if (!(error instanceof ApiError)) {
    return { message: error instanceof Error ? error.message : 'Something went wrong.', suggestion: 'Check your connection and try again.' }
  }
  const messages: Record<string, { message: string; suggestion: string }> = {
    no_imagery: { message: 'No suitable satellite images were found.', suggestion: 'Try a wider date range or a higher cloud limit.' },
    insufficient_valid_pixels: { message: 'Too few clear pixels were available for this analysis.', suggestion: 'Try a different date range or a larger area.' },
    invalid_aoi: { message: 'That area could not be used.', suggestion: 'Draw a non-crossing polygon or upload a valid GeoJSON Polygon.' },
    aoi_too_large: { message: 'Please select a smaller area.', suggestion: 'The maximum area is 200 km².' },
    model_unavailable: { message: 'The land-cover model is not available.', suggestion: 'Check that the model files are mounted in the configured model folder.' },
    unsupported_query: { message: 'This question is not supported yet.', suggestion: 'Try an index, vegetation change, time trend, or land-cover question.' },
    internal_error: { message: 'The analysis could not be completed.', suggestion: 'Try again later. The technical error code is shown below.' },
  }
  const mapped = messages[error.code] ?? { message: error.rawMessage, suggestion: 'Review the details and adjust the request.' }
  return { ...mapped, code: error.code }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (response.status === 204) return undefined as T
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const body = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {}
    const detail = body.detail
    const code = detail && typeof detail === 'object' && 'code' in detail ? String(detail.code) : `http_${response.status}`
    const message = typeof detail === 'string'
      ? detail
      : detail && typeof detail === 'object' && 'message' in detail
        ? String(detail.message)
        : `Request failed (${response.status}).`
    throw new ApiError(code, message)
  }
  return payload as T
}

export function startAnalysis(query: string, aoi: PolygonGeometry): Promise<RunAnalysisResponse> {
  return request('/analysis/run', {
    method: 'POST',
    body: JSON.stringify({ query, aoi, reference_date: new Date().toISOString().slice(0, 10) }),
  })
}

export function getJob(id: string): Promise<JobResponse> {
  return request(`/jobs/${encodeURIComponent(id)}`)
}

export function getHistory(): Promise<HistorySummary[]> {
  return request<{ items: HistorySummary[] }>('/history').then((body) => body.items)
}

export function getHistoryRecord(id: string): Promise<HistoryRecord> {
  return request(`/history/${encodeURIComponent(id)}`)
}

export function deleteHistoryRecord(id: string): Promise<void> {
  return request(`/history/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function compareAnalysis(query: string, aoiA: PolygonGeometry, aoiB: PolygonGeometry): Promise<CompareResponse> {
  return request('/analysis/compare', {
    method: 'POST',
    body: JSON.stringify({ query, aoi_a: aoiA, aoi_b: aoiB, reference_date: new Date().toISOString().slice(0, 10) }),
  })
}

export function getLayers(jobId: string): Promise<LayersResponse> {
  return request(`/analysis/${encodeURIComponent(jobId)}/layers`)
}

export async function downloadExport(jobId: string, format: 'csv' | 'geojson'): Promise<void> {
  const response = await fetch(`${API_BASE}/analysis/${encodeURIComponent(jobId)}/export.${format}`)
  if (!response.ok) throw new Error(`Export failed (${response.status}).`)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${jobId}.${format}`
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function validateAoi(aoi: PolygonGeometry): Promise<AoiValidationResponse> {
  return request('/aoi/validate', { method: 'POST', body: JSON.stringify({ aoi }) })
}

export function getImageryScenes(aoi: PolygonGeometry, start: string, end: string, maxCloud: number): Promise<ImageryScene[]> {
  return request('/imagery/scenes', {
    method: 'POST',
    body: JSON.stringify({ aoi, start, end, max_cloud: maxCloud }),
  })
}

export async function searchPlaces(query: string): Promise<PlaceSearchResult[]> {
  const params = new URLSearchParams({ format: 'jsonv2', limit: '5', q: query })
  const response = await fetch(`https://nominatim.openstreetmap.org/search?${params}`)
  if (!response.ok) throw new Error(`Place search failed (${response.status}).`)
  return response.json() as Promise<PlaceSearchResult[]>
}
