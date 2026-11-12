import { useEffect, useRef, useState } from 'react'
import { ApiError, friendlyApiError, getLayers, searchPlaces, validateAoi } from '../api/client'
import type { AoiValidationResponse, ImageryScene, InvestigationResult, LayersResponse, PolygonGeometry } from '../types/analysis'
import type { DrawTarget } from './MapWorkspace'
import { radiusPolygon } from './MapWorkspace'
import { savedAoiStorageNote } from '../utils/savedAois'

const AOI_RADIUS_OPTIONS = [
  { metres: 500, label: '500 m (approximate)' },
  { metres: 1000, label: '1 km (approximate)' },
  { metres: 2000, label: '2 km (approximate)' },
  { metres: 5000, label: '5 km (approximate)' },
] as const

function formatCloud(cloud: number | null): string {
  return cloud === null ? 'Not available' : `${cloud.toFixed(1)}%`
}

function formatSceneDate(datetime: string): string {
  const parsed = new Date(datetime)
  return Number.isNaN(parsed.getTime())
    ? 'Not available'
    : parsed.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function SceneGallery({ scenes, selectedSceneId, onSelect, onClear, onPreview }: {
  scenes: ImageryScene[]
  selectedSceneId: string | null
  onSelect: (id: string) => void
  onClear: () => void
  onPreview: (scene: ImageryScene) => void
}) {
  return (
    <div className="scene-gallery" aria-label="Available Sentinel-2 scenes">
      {scenes.map((scene) => {
        const selected = scene.item_id === selectedSceneId
        const previewUrl = typeof scene.preview_url === 'string' && scene.preview_url ? scene.preview_url : null
        const unavailable = scene.data_available === false
        return (
          <article className={`scene-gallery-item ${selected ? 'scene-selected' : ''}`} key={scene.item_id}>
            <button
              className="scene-gallery-select"
              type="button"
              aria-pressed={selected}
              disabled={unavailable}
              onClick={() => onSelect(scene.item_id)}
            >
              <span className="scene-gallery-preview">
                {previewUrl
                  ? <img src={previewUrl} alt="" loading="lazy" referrerPolicy="no-referrer" />
                  : <span className="scene-gallery-no-preview">{unavailable ? 'Analysis data unavailable' : 'Preview not available'}</span>}
              </span>
              <span className="scene-gallery-information">
                <strong>{formatSceneDate(scene.datetime)}</strong>
                <span>Sensor: {scene.sensor || 'Not available'}</span>
                <span>Cloud cover: {formatCloud(scene.cloud_cover)}</span>
                <span>AOI coverage: {scene.coverage_fraction == null ? 'Not available' : `${(scene.coverage_fraction * 100).toFixed(1)}%`}</span>
                <span>Resolution: {scene.resolution_m == null ? 'Not available' : `${scene.resolution_m} m`}</span>
                <span>Processing level: {scene.processing_level || 'Not available'}</span>
                <small title={scene.item_id}>{scene.item_id}</small>
                <span className="scene-gallery-selection">{selected ? 'Selected for analysis' : 'Select this scene'}</span>
              </span>
            </button>
            <div className="scene-gallery-actions">
              {previewUrl && <button type="button" className="filter-btn" onClick={() => onPreview(scene)}>Open larger preview</button>}
              {selected && <button type="button" className="filter-btn" onClick={onClear}>Clear selection</button>}
            </div>
          </article>
        )
      })}
    </div>
  )
}

function ScenePreviewDialog({ scene, onClose }: { scene: ImageryScene | null; onClose: () => void }) {
  if (!scene?.preview_url) return null
  return (
    <div className="scene-preview-backdrop" role="dialog" aria-modal="true" aria-label={`Scene preview ${scene.item_id}`} onClick={onClose}>
      <div className="scene-preview-dialog" onClick={(event) => event.stopPropagation()}>
        <div className="scene-preview-dialog-heading">
          <strong>{formatSceneDate(scene.datetime)} · {scene.sensor || 'Not available'}</strong>
          <button type="button" className="filter-btn" onClick={onClose}>Close preview</button>
        </div>
        <img src={scene.preview_url} alt={`Provider preview for scene ${scene.item_id}`} referrerPolicy="no-referrer" />
        <p>{scene.item_id}</p>
      </div>
    </div>
  )
}

const EXPLORE_STEPS = [
  { id: 'choose', label: 'Method' },
  { id: 'location', label: 'Location' },
  { id: 'define-aoi', label: 'AOI' },
  { id: 'imagery', label: 'Imagery' },
  { id: 'ask', label: 'Ask' },
] as const

function StageProgress({ stage }: { stage: 'search' | 'map-pick' | 'define-aoi' | 'imagery' | 'ask' }) {
  const activeIndex = stage === 'search' || stage === 'map-pick' ? 1 : stage === 'define-aoi' ? 2 : stage === 'imagery' ? 3 : 4
  return (
    <ol className="stage-progress" aria-label="Progress">
      {EXPLORE_STEPS.map((item, index) => (
        <li key={item.id} className={index <= activeIndex ? 'stage-progress-step is-active' : 'stage-progress-step'}>
          <span className="stage-progress-dot" aria-hidden="true" />
          {item.label}
        </li>
      ))}
    </ol>
  )
}

interface ExplorePanelProps {
  aoi: PolygonGeometry | null
  aoiA: PolygonGeometry | null
  aoiB: PolygonGeometry | null
  compareMode: boolean
  investigationMode: boolean
  drawTarget: DrawTarget | null
  onDrawTarget: (target: DrawTarget | null) => void
  onAoiDrawn: (target: DrawTarget, aoi: PolygonGeometry) => void
  aoiInfo: AoiValidationResponse | null
  aoiError: string | null
  aoiErrorDetails: string | null
  aoiValidationLoading: boolean
  jobId: string | null
  layerInfo: LayersResponse | null
  visibleLayers: string[]
  setVisibleLayers: (value: string[]) => void
  opacity: number
  setOpacity: (value: number) => void
  // Question form
  query: string
  setQuery: (value: string) => void
  queryStart: string
  setQueryStart: (value: string) => void
  queryEnd: string
  setQueryEnd: (value: string) => void
  // Imagery filters
  imageStart: string
  setImageStart: (value: string) => void
  imageEnd: string
  setImageEnd: (value: string) => void
  maxCloud: number
  setMaxCloud: (value: number) => void
  // Scenes
  scenes: ImageryScene[]
  scenesLoading: boolean
  scenesError: string | null
  scenesErrorDetails: string | null
  sceneSelectionMessage: string | null
  selectedSceneId: string | null
  setSelectedSceneId: (id: string | null) => void
  // Submission
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void
  jobBusy: boolean
  investigationLoading: boolean
  comparisonLoading: boolean
  // Errors
  clarification: string | null
  requestError: string | null
  requestErrorDetails: { code: string; raw: string } | null
  failedFriendly: { message: string; suggestion: string; code?: string } | null
  investigationResult: InvestigationResult | null
  // Retry handlers
  retryCompare: () => void
  retryInvestigation: () => void
  retryFailedAnalysis: () => void
  submitting: boolean
  // Saved AOIs
  savedAois: Array<{ id: string; name: string; geometry: PolygonGeometry; createdAt: string }>
  saveAoiName: string
  setSaveAoiName: (value: string) => void
  savedAoiMessage: string | null
  handleSaveAoi: (geometry: PolygonGeometry | null, label: string) => void
  handleRestoreAoi: (item: { id: string; name: string; geometry: PolygonGeometry; createdAt: string }, target: DrawTarget) => void
  handleDeleteAoi: (item: { id: string; name: string; geometry: PolygonGeometry; createdAt: string }) => void
  // Voice
  voiceStatus: 'idle' | 'listening' | 'processing' | 'unsupported' | 'denied' | 'error' | 'no-result'
  startVoiceInput: () => void
  setVoiceStatus: (value: 'idle' | 'listening' | 'processing' | 'unsupported' | 'denied' | 'error' | 'no-result') => void
  // Examples
  examples: string[]
  // Mode toggles
  comparing: boolean
  investigating: boolean
  onToggleInvestigation: () => void
  onToggleCompare: () => void
  // Compare months
  compareMonthA: string
  compareMonthB: string
  setCompareMonthA: (value: string) => void
  setCompareMonthB: (value: string) => void
  applyCompareMonths: () => void
  // Export
  onExport: (format: 'csv' | 'geojson') => void
  exporting: string | null
  exportError: string | null
  // Active record for retry
  activeRecord: { aoi: PolygonGeometry | null; query: string | null } | null
  // Staged location-selection flow (optional; defaults to the full analysis panel).
  stage?: 'search' | 'map-pick' | 'define-aoi' | 'imagery' | 'ask'
  selectedLocation?: { label: string; lat: number; lon: number } | null
  onLocationSelected?: (location: { label: string; lat: number; lon: number }) => void
  onBack?: () => void
  onContinue?: () => void
  continueDisabled?: boolean
  onNewExploration?: () => void
}

export function ExplorePanel(props: ExplorePanelProps) {
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState<Array<{ display_name: string; lat: string; lon: string }>>([])
  const [searchMessage, setSearchMessage] = useState<string | null>(null)
  const [searching, setSearching] = useState(false)
  const [selectedPlace, setSelectedPlace] = useState<string | null>(null)
  const [selectedCentre, setSelectedCentre] = useState<{ lat: number; lon: number } | null>(null)
  const [radiusMetres, setRadiusMetres] = useState(1000)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadErrorDetails, setUploadErrorDetails] = useState<string | null>(null)
  const [uploadTarget, setUploadTarget] = useState<DrawTarget>('main')
  const [coordinateText, setCoordinateText] = useState('')
  const [coordinateError, setCoordinateError] = useState<string | null>(null)
  const [previewScene, setPreviewScene] = useState<ImageryScene | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const searchQueueRef = useRef<Promise<void>>(Promise.resolve())
  const searchDebounceRef = useRef<number | null>(null)
  const lastNominatimAtRef = useRef(0)

  function todayIso() { return new Date().toISOString().slice(0, 10) }

  // Result layer selection (moved out of the map into this side panel).
  useEffect(() => {
    if (!props.jobId) {
      props.setVisibleLayers([])
      return
    }
    let cancelled = false
    getLayers(props.jobId).then((info) => {
      if (!cancelled) {
        props.setVisibleLayers(Object.keys(info.layers).slice(0, 1))
      }
    }).catch(() => {
      if (!cancelled) props.setVisibleLayers([])
    })
    return () => { cancelled = true }
  }, [props.jobId])

  async function searchPlacesRateLimited(query: string) {
    const task = searchQueueRef.current.then(async () => {
      const delay = Math.max(0, 1000 - (Date.now() - lastNominatimAtRef.current))
      if (delay > 0) await new Promise((resolve) => window.setTimeout(resolve, delay))
      lastNominatimAtRef.current = Date.now()
      return searchPlaces(query)
    })
    searchQueueRef.current = task.then(() => undefined, () => undefined)
    return task
  }

  async function searchForPlace(query: string) {
    const trimmed = query.trim()
    if (!trimmed) return
    setSearch(trimmed)
    setSearching(true)
    setSearchMessage(null)
    setSearchResults([])
    try {
      const results = await searchPlacesRateLimited(trimmed)
      setSearchResults(results.slice(0, 5))
      if (results.length === 0) setSearchMessage('No place found. Try a different name, or enter coordinates as latitude, longitude.')
    } catch (error) {
      setSearchMessage(error instanceof Error ? error.message : 'Place search failed. Try again, or enter coordinates.')
    } finally {
      setSearching(false)
    }
  }

  function handleSearchInput(value: string) {
    setSearch(value)
    setSearchResults([])
    setSearchMessage(null)
    if (searchDebounceRef.current !== null) window.clearTimeout(searchDebounceRef.current)
    if (value.trim().length < 3) return
    searchDebounceRef.current = window.setTimeout(() => {
      void searchForPlace(value)
    }, 500)
  }

  function choosePlace(place: { display_name: string; lat: string; lon: string }): boolean {
    const lat = Number(place.lat)
    const lon = Number(place.lon)
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      setSearchMessage('This place returned invalid coordinates. Try another location.')
      return false
    }
    setSelectedPlace(place.display_name)
    setSelectedCentre({ lat, lon })
    setSearch(place.display_name)
    setSearchResults([])
    setSearchMessage(null)
    props.onLocationSelected?.({ label: place.display_name, lat, lon })
    return true
  }

  async function applyRadiusAoi(latitude: number, longitude: number, metres: number, placeName = selectedPlace ?? 'selected location') {
    const geometry = radiusPolygon(latitude, longitude, metres)
    try {
      await validateAoi(geometry)
      props.onAoiDrawn('main', geometry)
      setSearchMessage(`${placeName} selected with a ${AOI_RADIUS_OPTIONS.find((option) => option.metres === metres)?.label ?? `${metres} m`} radius. You can now ask a question.`)
    } catch (error) {
      const friendly = friendlyApiError(error)
      setSearchMessage(`${friendly.message} ${friendly.suggestion}`)
    }
  }

  function changeRadius(event: React.ChangeEvent<HTMLSelectElement>) {
    const metres = Number(event.target.value)
    setRadiusMetres(metres)
    if (selectedCentre) void applyRadiusAoi(selectedCentre.lat, selectedCentre.lon, metres)
  }

  function changeRadiusOnly(event: React.ChangeEvent<HTMLSelectElement>) {
    setRadiusMetres(Number(event.target.value))
  }

  function handleSearchSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void searchForPlace(search)
  }

  function useMyLocation() {
    setSearchMessage(null)
    if (!navigator.geolocation) {
      setSearchMessage('Location is not available in this browser. Search for a place or enter coordinates, then draw an area.')
      return
    }
    setSearchMessage('Getting your location… Allow browser permission if asked.')
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords
        setSelectedPlace('Your location')
        setSelectedCentre({ lat: latitude, lon: longitude })
        props.onLocationSelected?.({ label: 'Your location', lat: latitude, lon: longitude })
        setSearchMessage('Map centered on your location. Next step: draw an area on the map to analyze this place.')
      },
      (error) => {
        if (error.code === error.PERMISSION_DENIED) {
          setSearchMessage('Location permission was denied. Search for a place or enter coordinates, then draw an area.')
        } else if (error.code === error.POSITION_UNAVAILABLE) {
          setSearchMessage('Your location could not be determined right now. Search for a place or enter coordinates, then draw an area.')
        } else if (error.code === error.TIMEOUT) {
          setSearchMessage('Location request timed out. Search for a place or enter coordinates, then draw an area.')
        } else {
          setSearchMessage('Could not get your location. Search for a place or enter coordinates, then draw an area.')
        }
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    )
  }

  function goToCoordinates(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const [latText, lonText, ...extra] = coordinateText.split(',').map((part) => part.trim())
    const lat = Number(latText)
    const lon = Number(lonText)
    if (extra.length || !latText || !lonText || !Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      setCoordinateError('Enter coordinates as: latitude, longitude (for example: 28.6139, 77.2090).')
      return
    }
    setSelectedPlace(`${lat.toFixed(5)}, ${lon.toFixed(5)}`)
    setSelectedCentre({ lat, lon })
    props.onLocationSelected?.({ label: `${lat.toFixed(5)}, ${lon.toFixed(5)}`, lat, lon })
    setCoordinateError(null)
    setSearchMessage(`Map centered on ${lat.toFixed(5)}, ${lon.toFixed(5)}. Next step: draw an area on the map.`)
  }

  async function uploadAoi(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    setUploadError(null)
    setUploadErrorDetails(null)
    if (!file) return
    try {
      let root: Record<string, any>
      try {
        root = JSON.parse(await file.text()) as Record<string, any>
      } catch {
        throw new Error('This file is not valid JSON. Please upload a .geojson or .json file that contains an area (a Polygon).')
      }
      const geometry = root.type === 'Feature' ? root.geometry : root
      if (geometry?.type !== 'Polygon') throw new Error('This file does not contain a single area shape (Polygon).')
      await validateAoi(geometry)
      props.onAoiDrawn(uploadTarget, geometry)
      setUploadError(null)
    } catch (error) {
      if (error instanceof Error && !(error instanceof ApiError)) {
        setUploadError(`${error.message} Next step: try drawing the area on the map, or upload a valid GeoJSON Polygon file.`)
        return
      }
      const friendly = friendlyApiError(error)
      setUploadError(`${friendly.message} ${friendly.suggestion}`)
      setUploadErrorDetails(error instanceof ApiError ? `${error.code}: ${error.rawMessage}` : null)
    }
  }

  function dismissHint() {
    sessionStorage.setItem('satquery-map-hint-dismissed', 'true')
  }

  const stage = props.stage ?? 'ask'
  const aoiValidationStatus = props.aoiValidationLoading
    ? <p className="inline-message" role="status">Validating the selected area…</p>
    : props.aoiError
      ? <div className="map-feedback map-feedback-error" role="alert">
          {props.aoiError}
          {props.aoiErrorDetails && <details><summary>Error details</summary><code>{props.aoiErrorDetails}</code></details>}
        </div>
      : null
  const locationCentre = props.selectedLocation ? { lat: props.selectedLocation.lat, lon: props.selectedLocation.lon } : selectedCentre
  const locationLabel = props.selectedLocation?.label ?? selectedPlace ?? 'Selected location'

  if (stage !== 'ask') {
    const headerTitle = stage === 'search' ? 'Search for a location'
      : stage === 'map-pick' ? 'Select on Map'
        : stage === 'define-aoi' ? 'Define the analysis area'
          : 'Satellite imagery'
    const headerLead = stage === 'search' ? 'Find a city, village, lake, landmark or specific place by name.'
      : stage === 'map-pick' ? 'Click on the map to choose a location. This is a point, not an area.'
        : stage === 'define-aoi' ? 'Draw or upload the exact area to analyse. The whole searched city is not assumed.'
          : 'Review real Sentinel-2 scenes for the selected area and date range.'
    return (
      <aside className={`explore-panel explore-stage-${stage}`} aria-label="Location selection and area definition">
        <ScenePreviewDialog scene={previewScene} onClose={() => setPreviewScene(null)} />
        <div className="panel-header">
          {props.onBack && (
            <button type="button" className="panel-back-button" onClick={props.onBack} aria-label="Back to the previous step">
              ← Back
            </button>
          )}
          <h2>{headerTitle}</h2>
          <p className="panel-lead">{headerLead}</p>
          <StageProgress stage={stage} />
        </div>

        <div className="panel-scroll">
          {stage === 'search' && (
            <section className="panel-section">
              <form className="place-search" role="search" onSubmit={handleSearchSubmit}>
                <input
                  aria-label="Search a location"
                  value={search}
                  onChange={(event) => handleSearchInput(event.target.value)}
                  placeholder="City, village, lake, landmark or specific place"
                  autoComplete="off"
                />
                <button type="submit" disabled={searching || !search.trim()} title="Search location" aria-label="Search location">
                  {searching ? 'Searching…' : 'Search'}
                </button>
              </form>
              {searching && <p className="query-meta-help" role="status">Searching…</p>}
              {searchMessage && <p className="inline-message" role="status">{searchMessage}</p>}
              {searchResults.length > 0 && (
                <div className="place-results" role="listbox" aria-label="Search results">
                  {searchResults.map((place, index) => (
                    <button type="button" role="option" key={`${place.lat}-${place.lon}-${index}`} onClick={() => choosePlace(place)}>
                      <strong>{place.display_name.split(',').slice(0, 2).join(',')}</strong>
                      <span>{place.display_name}</span>
                    </button>
                  ))}
                </div>
              )}
              {!searching && !searchMessage && search.trim().length >= 3 && searchResults.length === 0 && search !== props.selectedLocation?.label && (
                <p className="query-meta-help" role="status">No results yet. Keep typing or try a different name.</p>
              )}
              {props.selectedLocation && (
                <div className="selected-location-card" role="status">
                  <span className="selected-location-kicker">Selected location</span>
                  <strong>{props.selectedLocation.label}</strong>
                  <span className="query-meta-help">Coordinates: {props.selectedLocation.lat.toFixed(5)}, {props.selectedLocation.lon.toFixed(5)}</span>
                  <p className="query-meta-help">Selecting a place only picks a location. You will define the analysis area on the next step.</p>
                </div>
              )}
            </section>
          )}

          {stage === 'map-pick' && (
            <section className="panel-section">
              <p className="query-meta-help">Click on the map to select a location. Clicking elsewhere updates the selected point. This does not create an area or radius.</p>
              {props.selectedLocation ? (
                <div className="selected-location-card" role="status">
                  <span className="selected-location-kicker">Selected point</span>
                  <strong>{props.selectedLocation.label}</strong>
                  <span className="query-meta-help">Coordinates: {props.selectedLocation.lat.toFixed(5)}, {props.selectedLocation.lon.toFixed(5)}</span>
                </div>
              ) : (
                <p className="inline-message" role="status">No point selected yet. Click the map to place a marker.</p>
              )}
            </section>
          )}

          {stage === 'define-aoi' && (
            <>
              {props.selectedLocation && (
                <section className="panel-section">
                  <div className="selected-location-card" role="status">
                    <span className="selected-location-kicker">Location context</span>
                    <strong>{props.selectedLocation.label}</strong>
                    <span className="query-meta-help">{props.selectedLocation.lat.toFixed(5)}, {props.selectedLocation.lon.toFixed(5)}</span>
                  </div>
                </section>
              )}
              <section className="panel-section">
                <div className="section-heading">Draw the analysis area</div>
                <div className="draw-toolbar" aria-label="Area drawing tools">
                  <button
                    className={`map-tool ${props.drawTarget === 'main-rectangle' ? 'map-tool-active' : ''}`}
                    type="button"
                    onClick={() => props.onDrawTarget(props.drawTarget === 'main-rectangle' ? null : 'main-rectangle')}
                    title="Draw a rectangle area on the map"
                  >
                    Draw rectangle
                  </button>
                  <button
                    className={`map-tool ${props.drawTarget === 'main' ? 'map-tool-active' : ''}`}
                    type="button"
                    onClick={() => props.onDrawTarget(props.drawTarget === 'main' ? null : 'main')}
                    title="Draw a custom shape (polygon) on the map"
                  >
                    Draw polygon
                  </button>
                  <button
                    className="map-tool map-tool-clear"
                    type="button"
                    disabled={!props.aoi}
                    onClick={() => props.onAoiDrawn('main', { type: 'Polygon', coordinates: [] })}
                    title="Clear the selected area"
                  >
                    Clear area
                  </button>
                  <button type="button" className="map-tool" onClick={() => { setUploadTarget('main'); fileRef.current?.click() }} title="Upload a GeoJSON boundary">
                    Upload GeoJSON boundary
                  </button>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".geojson,.json,application/geo+json,application/json"
                    className="visually-hidden"
                    onChange={uploadAoi}
                    aria-label="Upload a GeoJSON boundary"
                  />
                </div>
                {props.drawTarget && (
                  <p className="panel-draw-instruction" role="status">
                    {props.drawTarget === 'main'
                      ? 'Click on the map to place polygon points. Double-click the last point to finish.'
                      : 'Click and drag on the map to draw a rectangle.'}
                  </p>
                )}
                {uploadError && (
                  <div className="map-feedback map-feedback-error map-upload-error" role="alert">
                    {uploadError}{uploadErrorDetails && <details><summary>Error details</summary><code>{uploadErrorDetails}</code></details>}
                  </div>
                )}
              </section>

              <section className="panel-section">
                <div className="section-heading">Optional approximate radius</div>
                <p className="query-meta-help">A radius is an approximate circular area around the selected location, not an official boundary. Applying it replaces the drawn area.</p>
                <label className="radius-control">Approximate radius
                  <select aria-label="Approximate radius" value={radiusMetres} onChange={changeRadiusOnly} disabled={!locationCentre}>
                    {AOI_RADIUS_OPTIONS.map((option) => <option key={option.metres} value={option.metres}>{option.label}</option>)}
                  </select>
                </label>
                <button
                  type="button"
                  className="apply-place-button"
                  onClick={() => { if (locationCentre) void applyRadiusAoi(locationCentre.lat, locationCentre.lon, radiusMetres, locationLabel) }}
                  disabled={!locationCentre}
                >
                  Apply approximate radius
                </button>
                {searchMessage && <p className="inline-message" role="status">{searchMessage}</p>}
              </section>

              {aoiValidationStatus}
              {props.aoi && props.aoiInfo && (
                <section className="panel-section">
                  <div className="section-heading">AOI summary</div>
                  <div className="aoi-info-card">
                    <div><span>Area</span><strong>{props.aoiInfo.area_km2.toFixed(3)} km²</strong></div>
                    <div><span>Geometry</span><strong>{props.aoiInfo.geometry_type ?? 'Polygon'}</strong></div>
                    <div className="copy-center"><span>Centre</span><strong>{props.aoiInfo.centre.lat.toFixed(5)}, {props.aoiInfo.centre.lon.toFixed(5)}</strong></div>
                    <div><span>Bounds</span><strong>{props.aoiInfo.bounds.map((value) => value.toFixed(4)).join(', ')}</strong></div>
                  </div>
                  {props.aoiInfo.area_km2 < 0.41 && <p className="area-warning">This area is very small. Vegetation/water index and change analyses can still work; draw a larger area for land-cover results.</p>}
                  {props.aoiInfo.area_km2 > 100 && props.aoiInfo.area_km2 <= 200 && <p className="area-warning">This is a large area. Analysis may take longer than usual.</p>}
                  {props.aoiInfo.area_km2 > 200 && <p className="area-blocked">This area is too large to analyze (maximum 200 km²). Draw a smaller area.</p>}
                </section>
              )}
              {!props.aoi && <p className="inline-message" role="status">Draw a polygon or rectangle, apply an approximate radius, or upload a GeoJSON boundary to continue.</p>}
            </>
          )}

          {stage === 'imagery' && (
            <section className="panel-section panel-imagery" aria-label="Available satellite images">
              <div className="section-heading">Satellite images</div>
              <div className="imagery-heading">
                <div className="imagery-heading-left"><strong>Available satellite images</strong><span>{props.scenesLoading ? 'Searching…' : `${props.scenes.length} found`}</span></div>
              </div>
              <p className="scene-sensor-explanation"><strong>Sentinel-2 optical imagery</strong> records reflected light, including visible and near-infrared wavelengths used for vegetation indices.</p>
              <div className="imagery-date-row">
                <label>Images from<input aria-label="Find images from date" type="date" value={props.imageStart} max={props.imageEnd} onChange={(event) => props.setImageStart(event.target.value)} /></label>
                <label>Images to<input aria-label="Find images to date" type="date" value={props.imageEnd} min={props.imageStart} max={todayIso()} onChange={(event) => props.setImageEnd(event.target.value)} /></label>
              </div>
              <label className="cloud-control"><span>Allow up to <strong>{props.maxCloud}%</strong> cloud cover</span><input type="range" min="0" max="100" step="5" value={props.maxCloud} onChange={(event) => props.setMaxCloud(Number(event.target.value))} /></label>
              {props.scenesError && <div className="map-feedback map-feedback-error">{props.scenesError}{props.scenesErrorDetails && <details><summary>Error details</summary><code>{props.scenesErrorDetails}</code></details>}</div>}
              {props.sceneSelectionMessage && <p className="inline-message" role="status">{props.sceneSelectionMessage}</p>}
              {!props.aoi && <p className="no-scenes">Define an area on the map to see available satellite images.</p>}
              {props.aoi && !props.scenesLoading && !props.scenesError && props.scenes.length === 0 && <p className="no-scenes">No suitable satellite scenes found for this area and time period. Try a wider date range or a higher cloud limit.</p>}
              {props.scenes.length > 0 && (
                <SceneGallery scenes={props.scenes} selectedSceneId={props.selectedSceneId}
                  onSelect={props.setSelectedSceneId} onClear={() => props.setSelectedSceneId(null)}
                  onPreview={setPreviewScene} />
              )}
              {props.selectedSceneId && <p className="scene-selection-complete">The exact selected scene ID is preserved for analysis: {props.selectedSceneId}</p>}
            </section>
          )}
        </div>

        <div className="stage-nav-footer">
          {props.onBack && <button type="button" className="stage-nav-back" onClick={props.onBack}>Back</button>}
          {props.onContinue && (
            <button type="button" className="stage-nav-continue" onClick={props.onContinue} disabled={props.continueDisabled}>
              Continue
            </button>
          )}
        </div>

        <div className="panel-footer"><span>Sentinel-2 L2A via STAC</span></div>
      </aside>
    )
  }

  return (
    <aside className="explore-panel explore-stage-ask" aria-label="Analysis workspace">
      <ScenePreviewDialog scene={previewScene} onClose={() => setPreviewScene(null)} />
      <div className="panel-header">
        <div className="panel-header-top">
          <div className="panel-header-heading">
            {props.onBack && (
              <button type="button" className="panel-back-button" onClick={props.onBack} aria-label="Back to the previous step">
                ← Back
              </button>
            )}
            <h2>Ask your question</h2>
          </div>
          {props.onNewExploration && <button type="button" className="panel-link-btn" onClick={props.onNewExploration}>New exploration</button>}
        </div>
        <p className="panel-lead">Ask a plain-language question about the selected area, or refine the area and imagery below.</p>
        <StageProgress stage="ask" />
      </div>

      <div className="panel-scroll">
        {props.onBack && <button type="button" className="panel-back-link" onClick={props.onBack}>← Back to imagery</button>}
        {/* 1. Location and AOI information */}
        <section className="panel-section">
          <div className="section-heading">Location &amp; area</div>
          <form className="place-search" role="search" onSubmit={handleSearchSubmit}>
            <input
              aria-label="Search a place"
              value={search}
              onChange={(event) => handleSearchInput(event.target.value)}
              placeholder="Place, region or address"
              autoComplete="off"
            />
            <button type="submit" disabled={searching || !search.trim()} title="Search place" aria-label="Search place">
              {searching ? 'Searching…' : 'Search'}
            </button>
          </form>
          {searchMessage && <p className="inline-message" role="status">{searchMessage}</p>}
          {searchResults.length > 0 && <div className="place-results" role="listbox" aria-label="Search results">
            {searchResults.map((place, index) => (
              <button
                type="button"
                role="option"
                key={`${place.lat}-${place.lon}-${index}`}
                onClick={() => choosePlace(place)}
              >
                <strong>{place.display_name.split(',').slice(0, 2).join(',')}</strong>
                <span>{place.display_name}</span>
              </button>
            ))}
          </div>}
          {selectedPlace && (
            <div className="selected-place">
              <span>Selected location</span>
              <strong>{selectedPlace}</strong>
              <label className="radius-control">Analysis radius
                <select aria-label="Analysis radius" value={radiusMetres} onChange={changeRadius}>
                  {AOI_RADIUS_OPTIONS.map((option) => <option key={option.metres} value={option.metres}>{option.label}</option>)}
                </select>
              </label>
              <button
                type="button"
                className="apply-place-button"
                onClick={() => { if (selectedCentre) void applyRadiusAoi(selectedCentre.lat, selectedCentre.lon, radiusMetres) }}
                disabled={!selectedCentre}
              >
                Apply to map
              </button>
            </div>
          )}
        </section>

        <section className="panel-section">
          <div className="section-heading">Go to coordinates</div>
          <form className="coordinate-form" onSubmit={goToCoordinates}>
            <input
              aria-label="Latitude and longitude"
              value={coordinateText}
              onChange={(event) => setCoordinateText(event.target.value)}
              placeholder="lat, lon"
            />
            <button type="submit" title="Go to coordinates">Go</button>
          </form>
          {coordinateError && <p className="inline-message inline-message-error" role="alert">{coordinateError}</p>}
          <div className="map-action-row">
            <button type="button" title="Use your current location" onClick={useMyLocation}>Use my location</button>
          </div>
        </section>

        <section className="panel-section">
          <div className="section-heading">Draw an area</div>
          <div className="draw-toolbar" aria-label="Area drawing tools">
            {!props.comparing ? (
              <>
                <button
                  className={`map-tool ${props.drawTarget === 'main-rectangle' ? 'map-tool-active' : ''}`}
                  type="button"
                  onClick={() => props.onDrawTarget(props.drawTarget === 'main-rectangle' ? null : 'main-rectangle')}
                  title="Draw a rectangle area on the map"
                >
                  Draw rectangle
                </button>
                <button
                  className={`map-tool ${props.drawTarget === 'main' ? 'map-tool-active' : ''}`}
                  type="button"
                  onClick={() => props.onDrawTarget(props.drawTarget === 'main' ? null : 'main')}
                  title="Draw a custom shape (polygon) on the map"
                >
                  Draw polygon
                </button>
                <button
                  className="map-tool map-tool-clear"
                  type="button"
                  disabled={!props.aoi}
                  onClick={() => props.onAoiDrawn('main', { type: 'Polygon', coordinates: [] })}
                  title="Clear the selected area"
                >
                  Clear area
                </button>
                <button
                  className="map-tool"
                  type="button"
                  onClick={() => { setUploadTarget('main'); fileRef.current?.click() }}
                  title="Upload an area file (GeoJSON)"
                >
                  Upload area file (GeoJSON)
                </button>
              </>
            ) : (
              <>
                <button
                  className={`map-tool ${props.drawTarget === 'compare-a' ? 'map-tool-active' : ''}`}
                  type="button"
                  title="Draw Area A on the map"
                  onClick={() => props.onDrawTarget(props.drawTarget === 'compare-a' ? null : 'compare-a')}
                >
                  Draw Area A
                </button>
                <button
                  className={`map-tool ${props.drawTarget === 'compare-b' ? 'map-tool-active' : ''}`}
                  type="button"
                  title="Draw Area B on the map"
                  onClick={() => props.onDrawTarget(props.drawTarget === 'compare-b' ? null : 'compare-b')}
                >
                  Draw Area B
                </button>
              </>
            )}
            <input
              ref={fileRef}
              type="file"
              accept=".geojson,.json,application/geo+json,application/json"
              className="visually-hidden"
              onChange={uploadAoi}
              aria-label="Upload area file (GeoJSON)"
            />
          </div>
          {uploadError && (
            <div className="map-feedback map-feedback-error map-upload-error" role="alert">
              {uploadError}{uploadErrorDetails && <details><summary>Error details</summary><code>{uploadErrorDetails}</code></details>}
            </div>
          )}
        </section>

        {aoiValidationStatus}
        {props.aoi && props.aoiInfo && (
          <section className="panel-section">
            <div className="section-heading">Selected area</div>
            <div className="aoi-info-card">
              <div><span>Size</span><strong>{props.aoiInfo!.area_km2.toFixed(2)} km²</strong></div>
              <div className="copy-center"><span>Centre point</span><strong>{props.aoiInfo!.centre.lat.toFixed(5)}, {props.aoiInfo!.centre.lon.toFixed(5)}</strong>
                <button type="button" title="Copy centre coordinates" onClick={() => void navigator.clipboard.writeText(`${props.aoiInfo!.centre.lat.toFixed(6)}, ${props.aoiInfo!.centre.lon.toFixed(6)}`)}>Copy</button>
              </div>
              <div><span>Bounds (edges)</span><strong>{props.aoiInfo!.bounds.map((value) => value.toFixed(4)).join(', ')}</strong></div>
            </div>
            {props.aoiInfo!.area_km2 < 0.41 && <p className="area-warning">This area is very small. Vegetation/water index and change analyses can still work; draw a larger area for land-cover results.</p>}
            {props.aoiInfo!.area_km2 > 100 && props.aoiInfo!.area_km2 <= 200 && <p className="area-warning">This is a large area. Analysis may take longer than usual.</p>}
            {props.aoiInfo!.area_km2 > 200 && <p className="area-blocked">This area is too large to analyze (maximum 200 km²). Draw a smaller area.</p>}
          </section>
        )}

        {/* Mode toggles (Investigate / Compare) */}
        <section className="panel-section">
          <div className="section-heading">Analysis mode</div>
          <div className="mode-toggle-row">
            <button
              type="button"
              className={`mode-toggle-btn ${props.investigating ? 'mode-toggle-active' : ''}`}
              onClick={props.onToggleInvestigation}
              aria-pressed={props.investigating}
            >
              Investigate
            </button>
            <button
              type="button"
              className={`mode-toggle-btn ${props.comparing ? 'mode-toggle-active' : ''}`}
              onClick={props.onToggleCompare}
              aria-pressed={props.comparing}
            >
              Compare
            </button>
          </div>
          {props.investigating && <p className="panel-intro">Build an evidence-backed plan, execute available satellite tools, and inspect the measured findings.</p>}
          {props.comparing && <p className="panel-intro">Compare two areas side by side using the same index and date range.</p>}
          {props.comparing && <div className="compare-area-status" role="status" aria-live="polite"><span className={props.aoiA ? 'area-ready' : ''}>Area A: {props.aoiA ? 'drawn' : 'not drawn yet'}</span><span className={props.aoiB ? 'area-ready' : ''}>Area B: {props.aoiB ? 'drawn' : 'not drawn yet'}</span></div>}
          {props.comparing && (!props.aoiA || !props.aoiB) && <p className="inline-message" role="status">Next step: use <strong>Draw A</strong> and <strong>Draw B</strong> on the map, then ask your question below.</p>}
        </section>

        {/* Saved AOIs */}
        <details className="saved-aois-panel">
          <summary className="field-label" style={{ cursor: 'pointer' }}>Saved areas (reuse AOIs)</summary>
          <p className="query-meta-help" style={{ marginTop: 6 }}>{savedAoiStorageNote()}</p>
          <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
            <label><span className="field-label">Area name</span><input aria-label="Saved area name" type="text" value={props.saveAoiName} maxLength={80} onChange={(e) => props.setSaveAoiName(e.target.value)} placeholder="e.g., Farm block A" /></label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {props.comparing ? (
                <>
                  <button type="button" className="filter-btn" onClick={() => props.handleSaveAoi(props.aoiA, 'Area A')} disabled={!props.aoiA || !props.saveAoiName.trim()}>Save Area A</button>
                  <button type="button" className="filter-btn" onClick={() => props.handleSaveAoi(props.aoiB, 'Area B')} disabled={!props.aoiB || !props.saveAoiName.trim()}>Save Area B</button>
                </>
              ) : (
                <button type="button" className="filter-btn" onClick={() => props.handleSaveAoi(props.aoi, 'selected area')} disabled={!props.aoi || !props.saveAoiName.trim()}>Save selected area</button>
              )}
            </div>
            {props.savedAoiMessage && <p className="inline-message" role="status">{props.savedAoiMessage}</p>}
            {props.savedAois.length === 0 ? <p className="query-meta-help">No saved areas yet. Draw/select an area, enter a name, and save it.</p> : (
              <ul className="saved-aois-list" style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 6 }}>
                {props.savedAois.map((item) => (
                  <li key={item.id} style={{ border: '1px solid var(--border-soft)', borderRadius: 4, padding: 8, background: 'var(--surface-soft)' }}>
                    <div style={{ fontSize: 12, fontWeight: 600 }}>{item.name}</div>
                    <div className="query-meta-help" style={{ marginTop: 2 }}>Saved {new Date(item.createdAt).toLocaleString()}</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                      {props.comparing ? (
                        <>
                          <button type="button" className="filter-btn" onClick={() => props.handleRestoreAoi(item, 'compare-a')}>Restore to A</button>
                          <button type="button" className="filter-btn" onClick={() => props.handleRestoreAoi(item, 'compare-b')}>Restore to B</button>
                        </>
                      ) : (
                        <button type="button" className="filter-btn" onClick={() => props.handleRestoreAoi(item, 'main')}>Restore on map</button>
                      )}
                      <button type="button" className="filter-btn" onClick={() => props.handleDeleteAoi(item)} style={{ color: 'var(--danger)' }}>Delete</button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </details>

        {/* 2. Satellite scene discovery */}
        <section className="panel-section panel-imagery" aria-label="Available satellite images">
          {props.comparing ? (
            <>
              <div className="section-heading">Compare imagery</div>
              <p className="query-meta-help">Compare automatically finds Sentinel-2 observations with matching acquisition dates and verified coverage for both areas. The scene list and selected scene below apply to Standard analysis only.</p>
            </>
          ) : <>
          <div className="section-heading">Satellite images</div>
          <div className="imagery-heading">
            <div className="imagery-heading-left"><strong>Available satellite images</strong><span>{props.scenesLoading ? 'Searching…' : `${props.scenes.length} found`}</span></div>
          </div>
          <div className="imagery-date-row">
            <label>Images from<input aria-label="Find images from date" type="date" value={props.imageStart} max={props.imageEnd} onChange={(event) => props.setImageStart(event.target.value)} /></label>
            <label>Images to<input aria-label="Find images to date" type="date" value={props.imageEnd} min={props.imageStart} max={todayIso()} onChange={(event) => props.setImageEnd(event.target.value)} /></label>
          </div>
          <label className="cloud-control"><span>Allow up to <strong>{props.maxCloud}%</strong> cloud cover</span><input type="range" min="0" max="100" step="5" value={props.maxCloud} onChange={(event) => props.setMaxCloud(Number(event.target.value))} /></label>
          {props.scenesError && <div className="map-feedback map-feedback-error">{props.scenesError}{props.scenesErrorDetails && <details><summary>Error details</summary><code>{props.scenesErrorDetails}</code></details>}</div>}
          {props.sceneSelectionMessage && <p className="inline-message" role="status">{props.sceneSelectionMessage}</p>}
          {!props.aoi && <p className="no-scenes">Draw or select an area on the map to see available satellite images.</p>}
          {props.aoi && !props.scenesLoading && !props.scenesError && props.scenes.length === 0 && <p className="no-scenes">No suitable satellite scenes found for this area and time period. Try a wider date range or check the cloud-cover setting.</p>}
          {props.scenes.length > 0 && (
            <SceneGallery scenes={props.scenes} selectedSceneId={props.selectedSceneId}
              onSelect={props.setSelectedSceneId} onClear={() => props.setSelectedSceneId(null)}
              onPreview={setPreviewScene} />
          )}
          {props.scenes.length > 0 && !props.selectedSceneId && <p className="scene-selection-note">Select a scene to use that exact acquisition for single-date Standard index or land-cover analysis. Clear the selection before running change detection or a time series.</p>}
          {props.selectedSceneId && (() => {
            const selectedScene = props.scenes.find((scene) => scene.item_id === props.selectedSceneId)
            return selectedScene ? <p className="scene-selection-complete">Selected scene: {selectedScene.item_id} · {formatSceneDate(selectedScene.datetime)}. This exact scene is used only for supported single-date Standard analysis. Clear it before change detection or time series; Compare and Investigation use their own imagery selection.</p> : null
          })()}
          </>}
        </section>

        {/* 3. Selected scene summary */}
        {!props.comparing && props.selectedSceneId && props.scenes.length > 0 && (
          <section className="panel-section">
            <div className="section-heading">Selected scene</div>
            <div className="selected-scene-summary">
              {(() => {
                const scene = props.scenes.find((s) => s.item_id === props.selectedSceneId)
                if (!scene) return null
                return (
                  <div>
                    <strong>{formatSceneDate(scene.datetime)}</strong>
                    <span className="query-meta-help" style={{ display: 'block', marginTop: 2 }}>{scene.sensor || 'Not available'} · {formatCloud(scene.cloud_cover)} cloud · {scene.item_id}</span>
                  </div>
                )
              })()}
            </div>
            <button type="button" className="filter-btn" onClick={() => props.setSelectedSceneId(null)}>Clear selected scene</button>
          </section>
        )}

        {/* 4. Natural-language question */}
        <form className="query-form" onSubmit={props.onSubmit}>
          <div className="section-heading">Ask a question</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
            <label className="field-label" htmlFor="question">Ask a question</label>
            <button
              type="button"
              className="filter-btn"
              onClick={props.startVoiceInput}
              aria-label="Use voice input"
              title="Use voice input"
              disabled={props.voiceStatus === 'listening'}
              style={{ padding: '4px 8px', fontSize: 12 }}
            >
              {props.voiceStatus === 'listening' ? 'Listening…' : '🎤 Voice'}
            </button>
          </div>
          <textarea id="question" rows={4} maxLength={500} value={props.query} onChange={(event) => props.setQuery(event.target.value)} placeholder="Ask about vegetation, water, change, trends, or land cover" />
          {(props.voiceStatus === 'unsupported' || props.voiceStatus === 'denied' || props.voiceStatus === 'error' || props.voiceStatus === 'no-result') && (
            <p className="inline-message" role="status" style={{ marginTop: 4, fontSize: 13 }}>
              {props.voiceStatus === 'unsupported' ? 'Voice input is not supported in this browser.' : props.voiceStatus === 'denied' ? 'Voice input permission was denied.' : props.voiceStatus === 'no-result' ? 'No speech was detected.' : 'Voice input encountered an error.'}
            </p>
          )}
          <div className="query-date-fields">
            <label>Start date (optional)<input aria-label="Question start date" type="date" value={props.queryStart} max={props.queryEnd || undefined} onChange={(event) => props.setQueryStart(event.target.value)} /></label>
            <label>End date (optional)<input aria-label="Question end date" type="date" value={props.queryEnd} min={props.queryStart || undefined} onChange={(event) => props.setQueryEnd(event.target.value)} /></label>
          </div>
          <p className="query-meta-help">Dates are optional. Add them if your question needs a specific time period.</p>
          <div className="query-meta"><span>Plain language question</span><span>{props.query.length}/500</span></div>

          {/* Example questions */}
          <div className="example-block">
            <span className="field-label">Try an example question</span>
            <div className="example-list">{props.examples.map((example) => <button className="example-question" type="button" key={example} onClick={() => props.setQuery(example)}><span aria-hidden="true">↳</span>{example}</button>)}</div>
          </div>

          {/* 5. Investigate action */}
          <button
            className="run-button"
            type="submit"
            disabled={props.jobBusy || props.investigationLoading ||
              (!props.comparing && Boolean(props.aoi && (props.aoiValidationLoading || props.aoiError || !props.aoiInfo)))}
          >
            <span>{props.comparisonLoading || props.investigationLoading ? 'Analyzing…' : props.jobBusy ? 'Running…' : (props.comparing ? 'Compare areas' : props.investigating ? 'Run investigation' : 'Run analysis')}</span>
            {props.jobBusy || props.investigationLoading ? <span className="map-spinner run-spinner" aria-hidden="true" /> : <span className="run-arrow" aria-hidden="true">↗</span>}
          </button>
        </form>

        {/* Errors */}
        {(props.clarification || props.requestError) && (
          <div className={`inline-message ${props.requestError ? 'inline-message-error' : ''}`} role="status">
            <span>{props.requestError ?? (props.clarification ? `Please clarify your question: ${props.clarification}` : null)}</span>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
              {props.clarification && <button type="button" className="filter-btn" onClick={() => { /* clarification cleared by parent */ }}>Edit question</button>}
              {props.requestError && props.comparing && props.aoiA && props.aoiB && props.query.trim() && <button type="button" className="filter-btn" onClick={props.retryCompare} disabled={props.comparisonLoading}>{props.comparisonLoading ? 'Retrying…' : 'Retry comparison'}</button>}
              {props.requestError && props.investigating && props.aoi && props.query.trim() && <button type="button" className="filter-btn" onClick={props.retryInvestigation} disabled={props.investigationLoading}>{props.investigationLoading ? 'Retrying…' : 'Retry investigation'}</button>}
              {props.requestError && !props.comparing && props.activeRecord?.aoi && props.activeRecord?.query && <button type="button" className="filter-btn" onClick={props.retryFailedAnalysis} disabled={props.submitting}>Run again</button>}
            </div>
            {props.requestErrorDetails && <details style={{ marginTop: 8 }}><summary>Error details (technical)</summary><code>{props.requestErrorDetails.code}: {props.requestErrorDetails.raw}</code></details>}
          </div>
        )}

        {props.failedFriendly && (
          <div className="failure-message" role="alert">
            <strong>{props.failedFriendly.message}</strong>
            <p>{props.failedFriendly.suggestion}</p>
            {props.activeRecord?.aoi && props.activeRecord?.query && (
              <button type="button" className="filter-btn" onClick={props.retryFailedAnalysis} disabled={props.submitting} style={{ marginTop: 8 }}>
                {props.submitting ? 'Running…' : 'Run analysis again'}
              </button>
            )}
            <details style={{ marginTop: 8 }}><summary>Error details (technical)</summary><code>{/* code from parent */}</code></details>
          </div>
        )}

        {props.investigationResult?.status === 'failed' && (
          <div className="investigation-error-banner" role="alert">
            <strong>Investigation failed</strong>
            <p>{props.investigationResult.data_quality_and_uncertainty.limitations?.join(' ') || props.investigationResult.explanation.text || 'The selected investigation could not be completed.'}</p>
            <button type="button" className="retry-button" onClick={props.retryInvestigation} disabled={props.investigationLoading}>
              {props.investigationLoading ? 'Retrying…' : 'Retry investigation'}
            </button>
          </div>
        )}
      </div>

      {false && (
        <div className="first-visit-hint">
          <span>1. Find a place (optional) · 2. Draw an area on the map · 3. Ask a question and run analysis</span>
          <button type="button" title="Dismiss instructions" aria-label="Dismiss instructions" onClick={dismissHint}>×</button>
        </div>
      )}

      <div className="panel-footer"><span>Sentinel-2 L2A via STAC</span></div>
    </aside>
  )
}
