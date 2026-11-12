import type {
  CompareResponse,
  AoiValidationResponse,
  HistoryRecord,
  HistorySummary,
  ImageryScene,
  InvestigationRequest,
  InvestigationResult,
  JobResponse,
  LayersResponse,
  PlaceSearchResult,
  PolygonGeometry,
  RunAnalysisResponse,
  SarAnalysisResponse,
  SarScene,
  FusionPair,
  FusionResponse,
  CaptionResponse,
} from '../types/analysis'

export interface LandCoverEvaluationReport {
  dataset: string
  test_samples: number
  source: string
  reported_artifact_only: boolean
  reproduced_by_this_endpoint: boolean
  results: {
    accuracy_10_class: number
    macro_f1_10_class: number
    accuracy_4_class: number
    macro_f1_4_class: number
    expected_calibration_error: number
    accuracy_gaussian_noise_sd_0_01: number
  }
  limitations: string[]
}

export const API_BASE = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')

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
    no_imagery: { message: 'No suitable satellite images were found for this area and time.', suggestion: 'Next step: try a wider date range or allow more cloud cover, then run again.' },
    insufficient_valid_pixels: { message: 'There was not enough clear image data to analyze this area.', suggestion: 'Next step: try a different date range or a larger area.' },
    invalid_aoi: { message: 'That selected area could not be used.', suggestion: 'Next step: draw a simple shape on the map (make sure the lines don’t cross), or upload a valid area file (GeoJSON Polygon).' },
    aoi_too_large: { message: 'The selected area is too large.', suggestion: 'Next step: draw or upload a smaller area (maximum 200 km²).' },
    model_unavailable: { message: 'The land-cover tool is not available right now.', suggestion: 'Next step: try a different question (for example, vegetation, water, or change), or try again later.' },
    unsupported_query: { message: 'This question is not supported yet.', suggestion: 'Next step: try asking about vegetation/water (NDVI/NDWI), change over time, trends, or land cover using one of the example questions.' },
    internal_error: { message: 'The analysis could not be completed.', suggestion: 'Next step: try again. If it keeps happening, check the technical details below.' },
  }
  const mapped = messages[error.code] ?? { message: error.rawMessage || 'Something went wrong.', suggestion: 'Next step: check the details and try again.' }
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

export function startAnalysis(query: string, aoi: PolygonGeometry, maxCloud = 40,
                              selectedSceneId?: string | null): Promise<RunAnalysisResponse> {
  return request('/analysis/run', {
    method: 'POST',
    body: JSON.stringify({
      query,
      aoi,
      reference_date: new Date().toISOString().slice(0, 10),
      max_cloud: maxCloud,
      ...(selectedSceneId ? { selected_scene_id: selectedSceneId } : {}),
    }),
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

export function compareAnalysis(query: string, aoiA: PolygonGeometry, aoiB: PolygonGeometry,
                                maxCloud = 40): Promise<CompareResponse> {
  return request('/analysis/compare', {
    method: 'POST',
    body: JSON.stringify({ query, aoi_a: aoiA, aoi_b: aoiB,
      reference_date: new Date().toISOString().slice(0, 10), max_cloud: maxCloud }),
  })
}

export function investigate(req: InvestigationRequest): Promise<InvestigationResult> {
  return request('/analysis/investigate', {
    method: 'POST',
    body: JSON.stringify({
      ...req,
      reference_date: req.reference_date ?? new Date().toISOString().slice(0, 10),
      max_cloud: req.max_cloud ?? 40,
    }),
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

export function getSarScenes(aoi: PolygonGeometry, start: string, end: string): Promise<SarScene[]> {
  return request('/sar/scenes', {
    method: 'POST',
    body: JSON.stringify({ aoi, start, end }),
  })
}

export function analyzeSarScene(aoi: PolygonGeometry, selectedSceneId: string, start: string, end: string): Promise<SarAnalysisResponse> {
  return request('/sar/analyze', {
    method: 'POST',
    body: JSON.stringify({ aoi, selected_scene_id: selectedSceneId, start, end }),
  })
}

export function getFusionPairs(aoi: PolygonGeometry, start: string, end: string, maxCloud: number): Promise<{ pairs: FusionPair[]; max_temporal_separation_days: number; note: string }> {
  return request('/fusion/scenes', { method: 'POST', body: JSON.stringify({ aoi, start, end, max_cloud: maxCloud }) })
}

export function analyzeFusion(aoi: PolygonGeometry, opticalSceneId: string, sarSceneId: string, start: string, end: string, maxCloud: number): Promise<FusionResponse> {
  return request('/fusion/analyze', { method: 'POST', body: JSON.stringify({ aoi, optical_scene_id: opticalSceneId, sar_scene_id: sarSceneId, start, end, max_cloud: maxCloud }) })
}

export function analyzeCaptionScene(aoi: PolygonGeometry, selectedSceneId: string, start: string, end: string, maxCloud: number): Promise<CaptionResponse> {
  return request('/caption/analyze', {
    method: 'POST',
    body: JSON.stringify({ aoi, selected_scene_id: selectedSceneId, start, end, max_cloud: maxCloud }),
  })
}

export function getCaptionImageUrl(jobId: string): string {
  return `${API_BASE}/caption/${encodeURIComponent(jobId)}/image.png`
}

export function getLandCoverEvaluation(): Promise<LandCoverEvaluationReport> {
  return request('/evaluation/land-cover')
}

export function searchPlaces(query: string): Promise<PlaceSearchResult[]> {
  // Nominatim does not send CORS headers, so browsers cannot call it directly.
  // The backend proxies the request and supplies the required User-Agent.
  const params = new URLSearchParams({ q: query, limit: '5' })
  return request(`/places/search?${params}`)
}
