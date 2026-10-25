import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet-draw'
import 'leaflet/dist/leaflet.css'
import 'leaflet-draw/dist/leaflet.draw.css'
import { ApiError, friendlyApiError, getImageryScenes, getLayers, searchPlaces, validateAoi } from '../api/client'
import type { AoiValidationResponse, ImageryScene, LayersResponse, PlaceSearchResult, PolygonGeometry } from '../types/analysis'

export type DrawTarget = 'main' | 'main-rectangle' | 'compare-a' | 'compare-b'

interface MapWorkspaceProps {
  aoi: PolygonGeometry | null
  aoiA: PolygonGeometry | null
  aoiB: PolygonGeometry | null
  /** True while the map view is the visible view; the map stays mounted when hidden. */
  active: boolean
  compareMode: boolean
  drawTarget: DrawTarget | null
  jobId: string | null
  onDrawTarget: (target: DrawTarget | null) => void
  onAoiDrawn: (target: DrawTarget, aoi: PolygonGeometry) => void
  onImageDateSelected: (date: string) => void
}

interface LeafletMapHandle {
  map: any
  layers: Record<string, any>
  draw: any
}

interface CursorPosition {
  lat: number
  lon: number
}

const apiBase = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const imageryTiles = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
const boundaryTiles = 'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'
const transportationTiles = 'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}'
const openStreetMapTiles = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'

function polygonLayer(geometry: PolygonGeometry, color: string) {
  const layer = L.geoJSON(geometry as any, {
    pane: 'selectedAreaPane',
    style: () => ({ color, weight: 3, opacity: 1, fillColor: color, fillOpacity: 0.12 }),
  })
  layer.eachLayer((part: any) => part.bindTooltip('Selected area', { sticky: true, direction: 'top', className: 'selected-area-label' }))
  return layer
}

function Icon({ name }: { name: 'upload' | 'search' | 'clear' | 'rectangle' | 'polygon' | 'location' | 'fullscreen' | 'zoom' }) {
  const paths = {
    upload: <><path d="M12 16V4m0 0L7 9m5-5 5 5" /><path d="M4 16v4h16v-4" /></>,
    search: <><circle cx="10.8" cy="10.8" r="6.3" /><path d="m16 16 4.5 4.5" /></>,
    clear: <><path d="M4 7h16M10 11v6m4-6v6" /><path d="m5 7 1 13h12l1-13M9 7V4h6v3" /></>,
    rectangle: <rect x="3" y="5" width="18" height="14" rx="1" />,
    polygon: <path d="m3 12 4-8 8 2 5 8-7 6-9-3z" />,
    location: <><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z" /><circle cx="12" cy="10" r="2" /></>,
    fullscreen: <><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5" /></>,
    zoom: <><circle cx="10.8" cy="10.8" r="6.3" /><path d="m16 16 4.5 4.5M8 10.8h5.6m-2.8-2.8v5.6" /></>,
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>
}

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function monthAgoIso(months: number) {
  const date = new Date()
  date.setMonth(date.getMonth() - months)
  return date.toISOString().slice(0, 10)
}

function formatCloud(cloud: number | null) {
  return cloud === null ? 'n/a' : `${cloud.toFixed(1)}%`
}

function cloudColor(cloud: number | null) {
  if (cloud === null || cloud > 60) return '#bd5548'
  if (cloud > 30) return '#d89b38'
  return '#5c8346'
}

export function MapWorkspace(props: MapWorkspaceProps) {
  const elementRef = useRef<HTMLDivElement>(null)
  const handleRef = useRef<LeafletMapHandle | null>(null)
  const onAoiDrawnRef = useRef(props.onAoiDrawn)
  const onDrawTargetRef = useRef(props.onDrawTarget)
  const drawTargetRef = useRef(props.drawTarget)
  const fileRef = useRef<HTMLInputElement>(null)
  const searchQueueRef = useRef<Promise<void>>(Promise.resolve())
  const lastNominatimAtRef = useRef(0)
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState<PlaceSearchResult[]>([])
  const [searchMessage, setSearchMessage] = useState<string | null>(null)
  const [searching, setSearching] = useState(false)
  const [selectedPlace, setSelectedPlace] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadErrorDetails, setUploadErrorDetails] = useState<string | null>(null)
  const [uploadTarget, setUploadTarget] = useState<DrawTarget>('main')
  const [aoiInfo, setAoiInfo] = useState<AoiValidationResponse | null>(null)
  const [aoiError, setAoiError] = useState<string | null>(null)
  const [aoiErrorDetails, setAoiErrorDetails] = useState<string | null>(null)
  const [layerInfo, setLayerInfo] = useState<LayersResponse | null>(null)
  const [layerError, setLayerError] = useState<string | null>(null)
  const [visibleLayers, setVisibleLayers] = useState<string[]>([])
  const [opacity, setOpacity] = useState(0.72)
  const [cursorPosition, setCursorPosition] = useState<CursorPosition | null>(null)
  const [zoomLevel, setZoomLevel] = useState(5)
  const [coordinateText, setCoordinateText] = useState('')
  const [coordinateError, setCoordinateError] = useState<string | null>(null)
  const [hintVisible, setHintVisible] = useState(() => sessionStorage.getItem('satquery-map-hint-dismissed') !== 'true')
  const [imageStart, setImageStart] = useState(monthAgoIso(12))
  const [imageEnd, setImageEnd] = useState(todayIso())
  const [maxCloud, setMaxCloud] = useState(40)
  const [scenes, setScenes] = useState<ImageryScene[]>([])
  const [scenesLoading, setScenesLoading] = useState(false)
  const [scenesError, setScenesError] = useState<string | null>(null)
  const [scenesErrorDetails, setScenesErrorDetails] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(false)

  onAoiDrawnRef.current = props.onAoiDrawn
  onDrawTargetRef.current = props.onDrawTarget
  drawTargetRef.current = props.drawTarget

  useEffect(() => {
    if (!elementRef.current || handleRef.current) return
    const map = L.map(elementRef.current, { zoomControl: false, attributionControl: true, preferCanvas: true }).setView([22.8, 78.5], 5)
    map.createPane('referenceLabelsPane')
    map.getPane('referenceLabelsPane').style.zIndex = '350'
    map.createPane('analysisPane')
    map.getPane('analysisPane').style.zIndex = '400'
    map.createPane('selectedAreaPane')
    map.getPane('selectedAreaPane').style.zIndex = '500'

    const imagery = L.tileLayer(imageryTiles, {
      maxZoom: 18,
      attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community',
    })
    const boundaries = L.tileLayer(boundaryTiles, {
      maxZoom: 18,
      pane: 'referenceLabelsPane',
      attribution: 'Reference overlays &copy; Esri',
    })
    const transport = L.tileLayer(transportationTiles, {
      maxZoom: 18,
      pane: 'referenceLabelsPane',
      attribution: 'Reference overlays &copy; Esri',
    })
    const labels = L.layerGroup([boundaries, transport])
    const satelliteLabels = L.layerGroup([imagery, labels]).addTo(map)
    const streets = L.tileLayer(openStreetMapTiles, {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    })
    const satelliteOnly = L.layerGroup([imagery])
    L.control.layers({ 'Satellite + labels': satelliteLabels, Streets: streets, 'Satellite only': satelliteOnly }, {}, { position: 'topright' }).addTo(map)
    L.control.zoom({ position: 'topright' }).addTo(map)
    L.control.scale({ position: 'bottomleft', metric: true, imperial: false, maxWidth: 120 }).addTo(map)
    handleRef.current = { map, layers: { labels, imagery, boundaries, transport }, draw: null }
    setZoomLevel(map.getZoom())

    map.on('mousemove', (event: any) => setCursorPosition({ lat: event.latlng.lat, lon: event.latlng.lng }))
    map.on('mouseout', () => setCursorPosition(null))
    map.on('zoomend', () => setZoomLevel(map.getZoom()))
    map.on('baselayerchange', (event: any) => {
      if (event.name === 'Satellite + labels') {
        if (!map.hasLayer(labels)) labels.addTo(map)
      } else if (event.name === 'Satellite only' || event.name === 'Streets') {
        if (map.hasLayer(labels)) map.removeLayer(labels)
      }
    })
    map.on('draw:created', (event: any) => {
      const target = drawTargetRef.current
      if (!target) return
      const geo = event.layer.toGeoJSON()
      const geometry = geo.type === 'Feature' ? geo.geometry : geo
      if (geometry?.type !== 'Polygon') return
      void validateAoi(geometry as PolygonGeometry).then(() => {
        onAoiDrawnRef.current(target, geometry as PolygonGeometry)
        setAoiError(null)
      }).catch((error: unknown) => {
        const friendly = friendlyApiError(error)
        setAoiError(`${friendly.message} ${friendly.suggestion}`)
        setAoiErrorDetails(error instanceof ApiError ? `${error.code}: ${error.rawMessage}` : null)
      }).finally(() => onDrawTargetRef.current(null))
    })

    const handleFullscreenChange = () => setFullscreen(Boolean(document.fullscreenElement))
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange)
      Object.values(handleRef.current?.layers ?? {}).forEach((layer: any) => map.removeLayer(layer))
      map.remove()
      handleRef.current = null
    }
  }, [])

  // Leaflet is initialised while the view is hidden, so it measures a zero-size
  // container. One recalculation per activation keeps the tiles and vectors aligned.
  useEffect(() => {
    if (!props.active) return
    const frame = window.requestAnimationFrame(() => {
      handleRef.current?.map.invalidateSize()
    })
    return () => window.cancelAnimationFrame(frame)
  }, [props.active])

  useEffect(() => {
    const handle = handleRef.current
    if (!handle) return
    handle.draw?.disable()
    if (!props.drawTarget) return
    const options = { shapeOptions: { color: '#ffeb00', weight: 3, opacity: 1, fillColor: '#ffeb00', fillOpacity: 0.14 } }
    handle.draw = props.drawTarget === 'main-rectangle'
      ? new (L as any).Draw.Rectangle(handle.map, options)
      : new (L as any).Draw.Polygon(handle.map, options)
    handle.draw.enable()
  }, [props.drawTarget])

  const currentAoi = props.compareMode ? props.aoiA ?? props.aoiB : props.aoi

  useEffect(() => {
    const handle = handleRef.current
    if (!handle) return
    Object.entries(handle.layers).forEach(([key, layer]) => {
      if (key.startsWith('aoi-')) {
        handle.map.removeLayer(layer)
        delete handle.layers[key]
      }
    })
    if (props.aoi) handle.layers['aoi-main'] = polygonLayer(props.aoi, '#ffeb00').addTo(handle.map)
    if (props.aoiA) handle.layers['aoi-a'] = polygonLayer(props.aoiA, '#ffb72e').addTo(handle.map)
    if (props.aoiB) handle.layers['aoi-b'] = polygonLayer(props.aoiB, '#48e2d1').addTo(handle.map)
    const selected = props.compareMode
      ? [props.aoiA, props.aoiB].filter(Boolean)
      : [props.aoi].filter(Boolean)
    if (selected.length) {
      const group = L.featureGroup(selected.map((item) => polygonLayer(item!, '#ffeb00')))
      if (group.getBounds().isValid()) handle.map.fitBounds(group.getBounds(), { padding: [48, 48], maxZoom: 18 })
    }
  }, [props.aoi, props.aoiA, props.aoiB, props.compareMode])

  useEffect(() => {
    let cancelled = false
    setAoiInfo(null)
    setAoiError(null)
    setAoiErrorDetails(null)
    setScenes([])
    if (!currentAoi) return
    void validateAoi(currentAoi).then((info) => {
      if (!cancelled) setAoiInfo(info)
    }).catch((error: unknown) => {
      if (!cancelled) {
        const friendly = friendlyApiError(error)
        setAoiError(`${friendly.message} ${friendly.suggestion}`)
        setAoiErrorDetails(error instanceof ApiError ? `${error.code}: ${error.rawMessage}` : null)
      }
    })
    return () => { cancelled = true }
  }, [currentAoi])

  useEffect(() => {
    let cancelled = false
    if (!currentAoi || !aoiInfo || aoiInfo.area_km2 > 200) {
      setScenes([])
      return
    }
    setScenesLoading(true)
    setScenesError(null)
    setScenesErrorDetails(null)
    const timer = window.setTimeout(() => {
      void getImageryScenes(currentAoi, imageStart, imageEnd, maxCloud).then((items) => {
        if (!cancelled) setScenes(items)
      }).catch((error: unknown) => {
        if (!cancelled) {
          const friendly = friendlyApiError(error)
          setScenesError(`${friendly.message} ${friendly.suggestion}`)
          setScenesErrorDetails(error instanceof ApiError ? `${error.code}: ${error.rawMessage}` : null)
        }
      }).finally(() => {
        if (!cancelled) setScenesLoading(false)
      })
    }, 250)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [currentAoi, aoiInfo, imageStart, imageEnd, maxCloud])

  useEffect(() => {
    let cancelled = false
    if (!props.jobId) {
      setLayerInfo(null)
      setLayerError(null)
      setVisibleLayers([])
      return
    }
    getLayers(props.jobId).then((info) => {
      if (cancelled) return
      setLayerInfo(info)
      setLayerError(null)
      setVisibleLayers(Object.keys(info.layers).slice(0, 1))
    }).catch((error: unknown) => {
      if (!cancelled) {
        setLayerInfo(null)
        setLayerError(error instanceof Error ? error.message : 'Raster layers are unavailable.')
      }
    })
    return () => { cancelled = true }
  }, [props.jobId])

  useEffect(() => {
    const handle = handleRef.current
    if (!handle || !layerInfo || !props.jobId) return
    Object.entries(handle.layers).forEach(([key, layer]) => {
      if (!key.startsWith('raster-')) return
      handle.map.removeLayer(layer)
      delete handle.layers[key]
    })
    visibleLayers.forEach((name) => {
      const image = L.imageOverlay(
        `${apiBase}/analysis/${encodeURIComponent(props.jobId!)}/layer/${encodeURIComponent(name)}.png`,
        layerInfo.bounds as any,
        { opacity, interactive: false, pane: 'analysisPane' },
      )
      image.addTo(handle.map)
      handle.layers[`raster-${name}`] = image
    })
  }, [layerInfo, visibleLayers, opacity, props.jobId])

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
      if (results.length === 0) setSearchMessage('No place found.')
    } catch (error) {
      setSearchMessage(error instanceof Error ? error.message : 'Place search failed. Try again.')
    } finally {
      setSearching(false)
    }
  }

  function choosePlace(place: PlaceSearchResult) {
    const lat = Number(place.lat)
    const lon = Number(place.lon)
    handleRef.current?.map.flyTo([lat, lon], 14, { duration: 1 })
    const marker = L.marker([lat, lon]).bindPopup(place.display_name).addTo(handleRef.current!.map).openPopup()
    handleRef.current?.layers.placeMarker?.remove()
    if (handleRef.current) handleRef.current.layers.placeMarker = marker
    setSelectedPlace(place.display_name)
    setSearch(place.display_name)
    setSearchResults([])
    setSearchMessage(null)
  }

  function handleSearchSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void searchForPlace(search)
  }

  function useMyLocation() {
    setSearchMessage(null)
    if (!navigator.geolocation) {
      setSearchMessage('Location is not available in this browser.')
      return
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords
        handleRef.current?.map.flyTo([latitude, longitude], 14, { duration: 1 })
        const marker = L.marker([latitude, longitude]).bindPopup('Your location').addTo(handleRef.current!.map).openPopup()
        handleRef.current?.layers.placeMarker?.remove()
        if (handleRef.current) handleRef.current.layers.placeMarker = marker
        setSelectedPlace('Your location')
      },
      (error) => {
        setSearchMessage(error.code === error.PERMISSION_DENIED
          ? 'Location permission was denied. Allow location access in your browser, or search for a place.'
          : 'Could not determine your location. Try searching for a place instead.')
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
      setCoordinateError('Enter coordinates as latitude, longitude within valid ranges.')
      return
    }
    setCoordinateError(null)
    handleRef.current?.map.flyTo([lat, lon], 14, { duration: 1 })
    const marker = L.marker([lat, lon]).bindPopup(`${lat.toFixed(5)}, ${lon.toFixed(5)}`).addTo(handleRef.current!.map).openPopup()
    handleRef.current?.layers.placeMarker?.remove()
    if (handleRef.current) handleRef.current.layers.placeMarker = marker
    setSelectedPlace(`${lat.toFixed(5)}, ${lon.toFixed(5)}`)
  }

  async function uploadAoi(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    setUploadError(null)
    setUploadErrorDetails(null)
    if (!file) return
    try {
      const root = JSON.parse(await file.text()) as Record<string, any>
      const geometry = root.type === 'Feature' ? root.geometry : root
      if (geometry?.type !== 'Polygon') throw new Error('Upload a GeoJSON Polygon or a Feature containing one Polygon.')
      await validateAoi(geometry as PolygonGeometry)
      props.onAoiDrawn(uploadTarget, geometry as PolygonGeometry)
    } catch (error) {
      const friendly = friendlyApiError(error)
      setUploadError(`${friendly.message} ${friendly.suggestion}`)
      setUploadErrorDetails(error instanceof ApiError ? `${error.code}: ${error.rawMessage}` : null)
    }
  }

  function zoomToArea() {
    const handle = handleRef.current
    if (!handle || !currentAoi) return
    const bounds = L.geoJSON(currentAoi as any).getBounds()
    if (bounds.isValid()) handle.map.fitBounds(bounds, { padding: [48, 48], maxZoom: 18 })
  }

  async function toggleFullscreen() {
    const element = elementRef.current?.parentElement
    if (!element) return
    try {
      if (document.fullscreenElement) await document.exitFullscreen()
      else await element.requestFullscreen()
    } catch {
      setSearchMessage('Full-screen mode is not available in this browser.')
    }
  }

  function selectSceneDate(dateTime: string) {
    props.onImageDateSelected(dateTime.slice(0, 10))
  }

  function dismissHint() {
    sessionStorage.setItem('satquery-map-hint-dismissed', 'true')
    setHintVisible(false)
  }

  const drawText = props.drawTarget === 'main' || props.drawTarget === 'main-rectangle'
    ? 'Draw an area on the map.'
    : props.drawTarget === 'compare-a' ? 'Draw Area A on the map.'
      : props.drawTarget === 'compare-b' ? 'Draw Area B on the map.' : null
  const changedScene = scenes.filter((scene) => scene.cloud_cover !== null)
  const leastCloudy = changedScene.length ? [...changedScene].sort((a, b) => (a.cloud_cover ?? 100) - (b.cloud_cover ?? 100))[0] : null

  return (
    <section className="map-workspace" aria-label="Area of interest map">
      <div ref={elementRef} className="map-canvas" />
      <div className="map-search-control">
        <form className="map-search" role="search" onSubmit={handleSearchSubmit}>
          <Icon name="search" />
          <input aria-label="Search a place" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a place, region or address" />
          <button type="submit" disabled={searching || !search.trim()} title="Search place" aria-label="Search place">{searching ? <span className="map-spinner" /> : 'Search'}</button>
        </form>
        {searchMessage && <p className="map-feedback" role="status">{searchMessage}</p>}
        {searchResults.length > 0 && <div className="place-results" role="listbox" aria-label="Search results">
          {searchResults.map((place, index) => <button type="button" role="option" key={`${place.lat}-${place.lon}-${index}`} onClick={() => choosePlace(place)}>
            <strong>{place.display_name.split(',').slice(0, 2).join(',')}</strong><span>{place.display_name}</span>
          </button>)}
        </div>}
        {selectedPlace && <div className="selected-place"><span>Viewing</span><strong>{selectedPlace}</strong></div>}
      </div>

      <div className="discovery-controls">
        <div className="quick-jumps" aria-label="Quick place search">
          {['Hyderabad', 'Vijayawada', 'Guntur', 'Amaravati'].map((place) => <button key={place} type="button" title={`Find ${place} in India`} onClick={() => void searchForPlace(`${place}, India`)}>{place}</button>)}
        </div>
        <div className="map-action-row">
          <button type="button" title="Use your current location" onClick={useMyLocation}><Icon name="location" /><span>Use my location</span></button>
          <form className="coordinate-form" onSubmit={goToCoordinates}>
            <input aria-label="Latitude and longitude" value={coordinateText} onChange={(event) => setCoordinateText(event.target.value)} placeholder="lat, lon" />
            <button type="submit" title="Go to coordinates">Go</button>
          </form>
          <button className="map-action-icon" type="button" title={fullscreen ? 'Exit full screen map' : 'Full screen map'} aria-label={fullscreen ? 'Exit full screen map' : 'Full screen map'} onClick={() => void toggleFullscreen()}><Icon name="fullscreen" /></button>
        </div>
        {coordinateError && <p className="map-feedback map-feedback-error" role="alert">{coordinateError}</p>}
      </div>

      <div className="draw-toolbar" aria-label="Area drawing tools">
        {!props.compareMode ? <>
          <button className={`map-tool ${props.drawTarget === 'main-rectangle' ? 'map-tool-active' : ''}`} type="button" onClick={() => props.onDrawTarget(props.drawTarget === 'main-rectangle' ? null : 'main-rectangle')} title="Draw rectangle"><Icon name="rectangle" /><span>Draw rectangle</span></button>
          <button className={`map-tool ${props.drawTarget === 'main' ? 'map-tool-active' : ''}`} type="button" onClick={() => props.onDrawTarget(props.drawTarget === 'main' ? null : 'main')} title="Draw polygon"><Icon name="polygon" /><span>Draw polygon</span></button>
          <button className="map-tool map-tool-clear" type="button" disabled={!props.aoi} onClick={() => props.onAoiDrawn('main', { type: 'Polygon', coordinates: [] })} title="Clear selected area"><Icon name="clear" /><span>Clear</span></button>
          <button className="map-tool" type="button" onClick={() => { setUploadTarget('main'); fileRef.current?.click() }} title="Upload a GeoJSON polygon"><Icon name="upload" /><span>Upload GeoJSON</span></button>
          <button className="map-tool" type="button" disabled={!props.aoi} onClick={zoomToArea} title="Zoom to selected area"><Icon name="zoom" /><span>Zoom to area</span></button>
        </> : <>
          <button className={`map-tool ${props.drawTarget === 'compare-a' ? 'map-tool-active' : ''}`} type="button" title="Draw Area A" onClick={() => props.onDrawTarget(props.drawTarget === 'compare-a' ? null : 'compare-a')}><span className="compare-swatch compare-swatch-a" /><span>Draw Area A</span></button>
          <button className={`map-tool ${props.drawTarget === 'compare-b' ? 'map-tool-active' : ''}`} type="button" title="Draw Area B" onClick={() => props.onDrawTarget(props.drawTarget === 'compare-b' ? null : 'compare-b')}><span className="compare-swatch compare-swatch-b" /><span>Draw Area B</span></button>
        </>}
        <input ref={fileRef} type="file" accept=".geojson,.json,application/geo+json,application/json" className="visually-hidden" onChange={uploadAoi} />
      </div>

      {drawText && <div className="draw-instruction" role="status">{drawText}</div>}
      {uploadError && <div className="map-feedback map-feedback-error map-upload-error" role="alert">{uploadError}{uploadErrorDetails && <details><summary>Error details</summary><code>{uploadErrorDetails}</code></details>}</div>}

      {hintVisible && <div className="first-visit-hint">
        <strong>Get started</strong><span>1. Find your place</span><span>2. Draw an area</span><span>3. Ask a question</span>
        <button type="button" title="Dismiss instructions" aria-label="Dismiss instructions" onClick={dismissHint}>×</button>
      </div>}

      <div className="map-readouts" aria-live="polite">
        <span>{cursorPosition ? `${cursorPosition.lat.toFixed(5)}°, ${cursorPosition.lon.toFixed(5)}°` : 'Move over the map for coordinates'}</span>
        <span>Zoom {zoomLevel}</span>
      </div>

      <div className="aoi-area-readout" aria-live="polite">
        {props.compareMode ? <><span><i className="compare-swatch-a" />A {aoiInfo?.area_km2.toFixed(2) ?? 'n/a'} km²</span><span><i className="compare-swatch-b" />B {aoiInfo?.area_km2.toFixed(2) ?? 'n/a'} km²</span></> : <>
          <small>AREA OF INTEREST</small>
          <strong>{aoiInfo ? `${aoiInfo.area_km2.toFixed(2)} km²` : props.aoi ? 'Checking area…' : 'Draw or upload an area'}</strong>
        </>}
      </div>

      {!props.compareMode && props.aoi && aoiInfo && <div className="aoi-info-card">
        <div className="aoi-info-heading"><strong>Selected area</strong><span>{aoiInfo.geometry_type}</span></div>
        <div><span>Area</span><strong>{aoiInfo.area_km2.toFixed(2)} km²</strong></div>
        <div className="copy-center"><span>Centre</span><strong>{aoiInfo.centre.lat.toFixed(5)}, {aoiInfo.centre.lon.toFixed(5)}</strong>
          <button type="button" title="Copy centre coordinates" onClick={() => void navigator.clipboard.writeText(`${aoiInfo.centre.lat.toFixed(6)}, ${aoiInfo.centre.lon.toFixed(6)}`)}>Copy</button>
        </div>
        <div><span>Bounds</span><strong>{aoiInfo.bounds.map((value) => value.toFixed(4)).join(', ')}</strong></div>
        {aoiInfo.area_km2 < 0.41 && <p className="area-warning">Too small for land-cover classification (needs one 640 m tile). Index and change analyses still work.</p>}
        {aoiInfo.area_km2 > 100 && aoiInfo.area_km2 <= 200 && <p className="area-warning">Large area: results will be slower.</p>}
        {aoiInfo.area_km2 > 200 && <p className="area-blocked">Please select a smaller area.</p>}
      </div>}
      {aoiError && <div className="area-blocked" role="alert">{aoiError}{aoiErrorDetails && <details><summary>Error details</summary><code>{aoiErrorDetails}</code></details>}</div>}

      {!props.compareMode && <section className="imagery-panel" aria-label="Available images">
        <div className="imagery-heading"><strong>Available images</strong><span>{scenesLoading ? 'Searching…' : `${scenes.length} found`}</span></div>
        <div className="imagery-date-row">
          <label>From<input aria-label="Imagery start date" type="date" value={imageStart} max={imageEnd} onChange={(event) => setImageStart(event.target.value)} /></label>
          <label>To<input aria-label="Imagery end date" type="date" value={imageEnd} min={imageStart} max={todayIso()} onChange={(event) => setImageEnd(event.target.value)} /></label>
        </div>
        <label className="cloud-control"><span>Max cloud <strong>{maxCloud}%</strong></span><input type="range" min="0" max="100" step="5" value={maxCloud} onChange={(event) => setMaxCloud(Number(event.target.value))} /></label>
        {scenesError && <div className="map-feedback map-feedback-error">{scenesError}{scenesErrorDetails && <details><summary>Error details</summary><code>{scenesErrorDetails}</code></details>}</div>}
        {!currentAoi && <p className="no-scenes">Draw an area to check available images.</p>}
        {currentAoi && !scenesLoading && !scenesError && scenes.length === 0 && <p className="no-scenes">No clear images in this period. Try a wider date range or a higher cloud limit.</p>}
        {leastCloudy && <p className="least-cloudy">Least cloudy: {new Date(leastCloudy.datetime).toLocaleDateString()} · {formatCloud(leastCloudy.cloud_cover)}</p>}
        {scenes.length > 0 && <div className="scene-timeline" aria-label="Available image dates">
          {scenes.map((scene) => <button type="button" key={scene.item_id} title={`${new Date(scene.datetime).toLocaleDateString()} · ${formatCloud(scene.cloud_cover)} cloud`} onClick={() => selectSceneDate(scene.datetime)}>
            <i style={{ backgroundColor: cloudColor(scene.cloud_cover) }} />
            <span>{new Date(scene.datetime).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
            <small>{formatCloud(scene.cloud_cover)}</small>
          </button>)}
        </div>}
        <small className="osm-credit">Search data © OpenStreetMap contributors</small>
      </section>}

      {layerInfo && Object.keys(layerInfo.layers).length > 0 && (
        <div className="map-layer-panel">
          <div className="map-layer-heading">RESULT LAYERS</div>
          <div className="map-layer-list">
            {Object.entries(layerInfo.layers).map(([name]) => (
              <label className="map-layer-toggle" key={name}>
                <input type="checkbox" checked={visibleLayers.includes(name)} onChange={(event) => setVisibleLayers((current) => event.target.checked ? [...current, name] : current.filter((item) => item !== name))} />
                <span>{name.replaceAll('_', ' ')}</span>
              </label>
            ))}
          </div>
          <label className="opacity-control"><span>Opacity</span><input type="range" min="0.1" max="1" step="0.05" value={opacity} onChange={(event) => setOpacity(Number(event.target.value))} /></label>
          {visibleLayers.map((name) => {
            const legend = layerInfo.layers[name]
            return legend ? <div className="map-legend" key={name}>{legend.colors.map((color) => <span key={`${color.value}-${color.hex}`}><i style={{ backgroundColor: color.hex }} />{color.label ?? color.value}</span>)}</div> : null
          })}
        </div>
      )}
      {layerError && props.jobId && <div className="map-layer-unavailable">Result map unavailable: {layerError}</div>}
    </section>
  )
}
