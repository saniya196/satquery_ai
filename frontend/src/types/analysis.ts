export type Operation = 'change_detection' | 'index_stats' | 'time_series' | 'land_cover'
export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed'

export interface PolygonGeometry {
  type: 'Polygon'
  coordinates: number[][][]
}

export interface AoiValidationResponse {
  valid: boolean
  bounds: [number, number, number, number]
  geometry_type: string
  area_km2: number
  centre: { lat: number; lon: number }
}

export interface ImageryScene {
  item_id: string
  datetime: string
  cloud_cover: number | null
}

export interface PlaceSearchResult {
  display_name: string
  lat: string
  lon: string
}

export interface SceneEvidence {
  item_id: string
  datetime: string
  cloud_cover: number | null
  resolution_m: number | null
  crs: string | null
  processing_level?: string | null
  source?: string | null
}

export interface Evidence {
  operation: Operation
  scenes: SceneEvidence[]
  aoi_area_km2: number | null
  index?: string | null
  formula?: string | null
  bands: string | string[] | null
  preprocessing: string[]
  thresholds: Record<string, number | string | boolean | null>
  valid_pixel_fraction: number | null
  metrics: Record<string, unknown>
  model?: {
    architecture?: string | null
    bands?: string[] | string | null
    trained_on?: string | null
    training_processing_level?: string | null
    test_accuracy_10class?: number | null
    test_accuracy_product?: number | null
    expected_calibration_error?: number | null
    limitations?: string[]
  } | null
}

export interface ConfidenceFactor {
  factor: string
  value: number | string | null
  score: number | null
  weight: number | null
  normalised_weight: number | null
  explanation: string
}

export interface Confidence {
  score: number | null
  breakdown: ConfidenceFactor[]
  method?: string | null
}

export interface ChangeClassMetric {
  pixels: number | null
  fraction_of_valid: number | null
  area_km2: number | null
}

export interface ChangeFacts {
  mean_a: number | null
  mean_b: number | null
  mean_change: number | null
  percent_change_of_mean: number | null
  classes: Record<string, ChangeClassMetric>
}

export interface IndexStats {
  mean: number | null
  median: number | null
  min: number | null
  max: number | null
  std: number | null
  valid_fraction: number | null
  coverage_fraction: number | null
}

export interface TimeSeriesFacts {
  dates: string[]
  values: Array<number | null>
  rolling_mean_3: Array<number | null>
  anomaly_indices: number[]
  trend_claim_allowed: boolean
  trend_test: {
    trend: string | null
    p_value: number | null
    significant: boolean | null
    z: number | null
    n: number | null
  } | null
  sens_slope_per_year: number | null
  caveat: string | null
}

export interface LandCoverClassMetric {
  fraction: number | null
  area_km2: number | null
}

export interface AnalysisFacts {
  operation: Operation
  index?: string
  date?: string
  date_a?: string
  date_b?: string
  change?: ChangeFacts
  stats?: IndexStats
  series?: TimeSeriesFacts
  dominant_class?: string
  dominant_fraction?: number | null
  classes?: Record<string, LandCoverClassMetric | ChangeClassMetric>
  classified_fraction?: number | null
  mean_model_confidence?: number | null
  model_test_accuracy?: number | null
  [key: string]: unknown
}

export interface AnalysisAnswer {
  text: string
  source: 'llm' | 'template' | string
  attempts: number | null
}

export interface AnalysisResult {
  evidence: Evidence
  confidence: Confidence
  facts: AnalysisFacts
  answer: AnalysisAnswer
  hotspots?: Array<Record<string, unknown>>
  distribution?: Record<string, unknown>
  model?: Evidence['model']
}

export interface ChangeHotspot {
  id: number | string
  pixels: number | null
  area_km2: number | null
  mean_diff: number | null
  centroid_rowcol?: [number, number]
  centroid_lonlat?: [number, number]
}

export interface HistorySummary {
  id: string
  created: string
  query: string
  status: JobStatus
  operation: Operation
}

export interface HistoryRecord extends HistorySummary {
  structured_query: Record<string, unknown>
  aoi: PolygonGeometry
  result: AnalysisResult | { error: { code: string; message: string } } | null
}

export interface JobStage {
  name: string
  status: 'completed' | 'processing' | 'queued' | 'failed'
  duration?: string
}

export interface JobDataProvider {
  name: string
  tile?: string
  date?: string
}

export interface JobResponse {
  job_id: string
  status: JobStatus
  created?: string
  structured_query?: Record<string, unknown>
  result?: AnalysisResult
  error?: { code: string; message: string }
  stages?: JobStage[]
  provider_info?: JobDataProvider
}

export interface RunAnalysisResponse {
  status: 'queued' | 'needs_clarification'
  job_id?: string
  message?: string
}

export interface LayerColor {
  value: number
  label?: string
  hex: string
}

export interface LayerLegend {
  value_range: [number, number]
  colors: LayerColor[]
}

export interface LayersResponse {
  bounds: [[number, number], [number, number]]
  layers: Record<string, LayerLegend>
}

export interface CompareResponse {
  structured_query: Record<string, unknown>
  aoi_a: { result: AnalysisResult }
  aoi_b: { result: AnalysisResult }
  differences: Record<string, number>
}
