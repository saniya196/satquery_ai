export type Operation = 'change_detection' | 'index_stats' | 'time_series' | 'land_cover' | 'sar_backscatter' | 'optical_sar_fusion'
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
  sensor?: string | null
  collection?: string | null
  preview_url?: string | null
  coverage_fraction?: number | null
  resolution_m?: number | null
  processing_level?: string | null
  data_available?: boolean | null
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
  provider?: string | null
  collection?: string | null
  platform?: string | null
  coverage_fraction?: number | null
  sensor?: string | null
  sensor_identity?: 'sentinel-2' | 'other' | 'unknown'
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
  coverage?: {
    status?: 'full' | 'partial' | 'unknown' | string
    fraction?: number | null
    note?: string | null
  } | null
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
  n_dates_requested?: number | null
  n_dates_included?: number | null
  n_dates_usable?: number | null
  n_dates_skipped_low_valid?: number | null
  n_dates_skipped_load_error?: number | null
  insufficient_observations?: boolean
  status?: string | null
  message?: string | null
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
  coverage?: {
    status?: 'full' | 'partial' | 'unknown' | string
    fraction?: number | null
    note?: string | null
  } | null
}

export interface ChangeHotspotEvidenceRef {
  baseline_scene_id?: string | null
  comparison_scene_id?: string | null
  baseline_date?: string | null
  comparison_date?: string | null
  index?: string | null
  formula?: string | null
  bands?: string | string[] | null
  change_thresholds?: Record<string, unknown>
  preprocessing?: string[]
  global_valid_pixel_fraction?: number | null
  coverage?: unknown
}

export interface ChangeHotspot {
  id: number | string
  class?: string
  class_code?: number
  direction?: string | null
  pixels: number | null
  valid_pixel_count?: number | null
  area_km2: number | null
  mean_diff: number | null
  median_diff?: number | null
  std_diff?: number | null
  min_diff?: number | null
  max_diff?: number | null
  bbox_rowcol?: [number, number, number, number]
  bbox_lonlat?: [number, number, number, number] | null
  centroid_rowcol?: [number, number]
  centroid_lonlat?: [number, number] | null
  evidence?: ChangeHotspotEvidenceRef
}

export interface HistorySummary {
  id: string
  created: string
  query: string
  status: JobStatus
  operation: Operation
  sensor_identity?: 'sentinel-2' | 'other' | 'unknown'
  sensor?: string | null
  acquisition_dates?: string[]
  aoi_area_km2?: number | null
}

export interface HistoryRecord extends HistorySummary {
  structured_query: Record<string, unknown>
  aoi: PolygonGeometry
  result: AnalysisResult | { error: { code: string; message: string } } | null
}

export interface SarScene {
  item_id: string
  datetime: string
  provider: string
  collection: string
  platform: string | null
  processing_level: string | null
  product_type: string | null
  instrument_mode: string | null
  orbit_state: string | null
  relative_orbit: number | null
  polarizations: string[]
  coverage_fraction: number
  required_polarizations_available: boolean
  analysis_supported: boolean
}

export interface SarBandStats {
  mean: number
  median: number
  minimum: number
  maximum: number
  standard_deviation: number
}

export interface SarAnalysisResult {
  facts: {
    operation: 'sar_backscatter'
    measurement: string
    unit: string
    valid_pixel_fraction: number
    valid_pixel_count: number
    vv: SarBandStats
    vh: SarBandStats
  }
  evidence: {
    operation: 'sar_backscatter'
    scenes: Array<SceneEvidence & {
      orbit_state?: string | null
      relative_orbit?: number | null
      polarizations?: string[]
    }>
    aoi_area_km2: number | null
    bands: string[]
    preprocessing: string[]
    valid_pixel_fraction: number
    metrics: Record<string, number>
  }
}

export interface SarAnalysisResponse {
  job_id: string
  status: 'completed'
  result: SarAnalysisResult
}

export interface FusionPair {
  optical: { item_id: string; datetime: string; cloud_cover: number | null; coverage_fraction: number | null }
  sar: { item_id: string; datetime: string; coverage_fraction: number | null; polarizations: string[] }
  temporal_separation_hours: number
  max_temporal_separation_days: number
}

export interface FusionResult {
  operation: 'optical_sar_fusion'
  product: string
  valid_overlapping_pixel_count: number
  overlap_fraction: number
  temporal_separation_hours: number
  mean_ndvi: number
  mean_rvi: number
  common_crs: string
  resolution_m: number
  evidence: Evidence
  limitations: string[]
}

export interface FusionResponse { job_id: string; status: 'completed'; result: FusionResult }

export interface CaptionResult {
  facts: {
    operation: 'image_captioning'
    caption: string
    source_scene_id: string
    acquisition_datetime: string
    model_name: string
    model_repository: string
    model_revision: string
    valid_pixel_fraction: number
    rendered_width: number
    rendered_height: number
  }
  evidence: {
    operation: 'image_captioning'
    scenes: SceneEvidence[]
    aoi_area_km2: number | null
    formula: string
    bands: string[]
    preprocessing: string[]
    thresholds: Record<string, number>
    valid_pixel_fraction: number
    metrics: Record<string, unknown>
    model: Record<string, unknown>
  }
  limitations: string[]
  model: Record<string, unknown>
  image_url: string
}

export interface CaptionResponse { job_id: string; status: 'completed'; result: CaptionResult; image_url: string }

export interface JobStage {
  name: string
  status: 'completed' | 'processing' | 'queued' | 'failed'
  duration?: string
}

export interface JobDataProvider {
  name: string
  tile?: string | null
  date?: string | null
  coverage?: {
    status?: 'full' | 'partial' | 'unknown' | string
    fraction?: number | null
    note?: string | null
  } | null
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

export type InvestigationTraceStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

export interface InvestigationPlanTool {
  tool: string
  purpose: string
  reason: string
  params: Record<string, unknown>
}

export interface InvestigationPlan {
  original_question: string
  parsed_intent: string
  operation?: string | null
  index?: string | null
  aoi_provided: boolean
  date_range: Record<string, unknown>
  selected_tools: InvestigationPlanTool[]
  missing_required_inputs: string[]
  expected_outputs: string[]
  can_execute: boolean
  notes: string[]
}

export interface InvestigationTraceEvent {
  id: string
  label: string
  status: InvestigationTraceStatus
  detail?: string | null
  tool?: string | null
  started_at?: string | null
  finished_at?: string | null
  error?: { code?: string; message?: string } | null
}

export interface InvestigationToolExecution {
  tool: string
  status: InvestigationTraceStatus
  purpose: string
  summary: Record<string, unknown>
  error?: { code?: string; message?: string } | null
  actual_result?: Record<string, unknown> | null
}

export interface InvestigationEvidenceCheck {
  check: string
  passed: boolean
  detail: string
}

export interface InvestigationResult {
  question_understood: string
  plan: InvestigationPlan
  trace: InvestigationTraceEvent[]
  tools_executed: InvestigationToolExecution[]
  actual_findings: Record<string, unknown>
  supporting_evidence: Array<Record<string, unknown>>
  data_quality_and_uncertainty: {
    checks?: InvestigationEvidenceCheck[]
    limitations?: string[]
    [k: string]: unknown
  }
  unsupported_conclusions: string[]
  suggested_next_investigations: string[]
  explanation: { text: string; source?: string; attempts?: number; validated?: boolean; [k: string]: unknown }
  status: 'completed' | 'partial' | 'needs_input' | 'failed'
}

export interface InvestigationRequest {
  query: string
  aoi?: PolygonGeometry | null
  reference_date?: string | null
  max_cloud?: number
  date_a?: { start: string; end: string } | null
  date_b?: { start: string; end: string } | null
  series_range?: { start: string; end: string } | null
}
