import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet-draw'
import 'leaflet/dist/leaflet.css'
import 'leaflet-draw/dist/leaflet.draw.css'
import { ApiError, friendlyApiError, searchPlaces, validateAoi } from '../api/client'
import type { AoiValidationResponse, ChangeHotspot, LayersResponse, PlaceSearchResult, PolygonGeometry } from '../types/analysis'

export type DrawTarget = 'main' | 'main-rectangle' | 'compare-a' | 'compare-b'

export interface PickedPoint {
  lat: number
  lon: number
  label?: string
}

interface MapWorkspaceProps {
  aoi: PolygonGeometry | null
  aoiA: PolygonGeometry | null
  aoiB: PolygonGeometry | null
  /** True while the map view is the visible view; the map stays mounted when hidden. */
  active: boolean
  compareMode: boolean
  drawTarget: DrawTarget | null
  jobId: string | null
  selectedHotspot?: ChangeHotspot | null
  exploreMode?: boolean
  /** When 'pick-point', map clicks select/update a point (no AOI created). Default 'aoi'. */
  interactionMode?: 'aoi' | 'pick-point'
  pickedPoint?: PickedPoint | null
  /** Focus/zoom the map on pickedPoint when entering the AOI stage. */
  focusPickedPoint?: boolean
  onPointPicked?: (point: PickedPoint) => void
  /** 'full' preserves legacy clutter; 'minimal' keeps essential controls only. */
  chrome?: 'full' | 'minimal'
  /** Optional action label for applying an explicit radius AOI after place search. */
  locationAoiActionLabel?: string
  /** Show drawing tools immediately in compact embedded map workflows. */
  selectionExpanded?: boolean
  /** Result-layer metadata fetched by the shell; the shell owns layer visibility. */
  layerInfo: LayersResponse | null
  layerError?: string | null
  visibleLayers: string[]
  opacity: number
  setVisibleLayers: (value: string[]) => void
  setOpacity: (value: number) => void
  onDrawTarget: (target: DrawTarget | null) => void
  onAoiDrawn: (target: DrawTarget, aoi: PolygonGeometry) => void
  onImageDateSelected?: (date: string) => void
  onClearSelectedHotspot?: () => void
}

interface LeafletMapHandle {
  map: any
  layers: Record<string, any>
  draw: any
  drawnItems?: any
}

interface CursorPosition {
  lat: number
  lon: number
}

const apiBase = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8001').replace(/\/$/, '')
const imageryTiles = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
const boundaryTiles = 'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'
const transportationTiles = 'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}'
const openStreetMapTiles = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
const AOI_RADIUS_OPTIONS = [
  { metres: 500, label: '500 m' },
  { metres: 1000, label: '1 km' },
  { metres: 2000, label: '2 km' },
  { metres: 5000, label: '5 km' },
] as const

function polygonLayer(geometry: PolygonGeometry, color: string) {
  const layer = L.geoJSON(geometry as any, {
    pane: 'selectedAreaPane',
    interactive: false,
    style: () => ({ color, weight: 2.5, opacity: 0.95, fillColor: color, fillOpacity: 0.16, dashArray: null }),
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

function validHotspotBbox(bbox: ChangeHotspot['bbox_lonlat']): [number, number, number, number] | null {
  if (!Array.isArray(bbox) || bbox.length !== 4) return null
  const [minLon, minLat, maxLon, maxLat] = bbox
  if (![minLon, minLat, maxLon, maxLat].every((v) => typeof v === 'number' && Number.isFinite(v))) return null
  if (minLon < -180 || maxLon > 180 || minLat < -90 || maxLat > 90 || minLon > maxLon || minLat > maxLat) return null
  return [minLon, minLat, maxLon, maxLat]
}
function validHotspotCentroid(centroid: ChangeHotspot['centroid_lonlat']): [number, number] | null {
  if (!Array.isArray(centroid) || centroid.length !== 2) return null
  const [lon, lat] = centroid
  if (typeof lon !== 'number' || typeof lat !== 'number' || !Number.isFinite(lon) || !Number.isFinite(lat)) return null
  if (lon < -180 || lon > 180 || lat < -90 || lat > 90) return null
  return [lon, lat]
}

export function radiusPolygon(latitude: number, longitude: number, radiusMetres: number): PolygonGeometry {
  const earthRadiusMetres = 6371008.8
  const latitudeRadians = latitude * Math.PI / 180
  const angularDistance = radiusMetres / earthRadiusMetres
  const coordinates: number[][] = []
  for (let index = 0; index <= 64; index += 1) {
    const bearing = (index / 64) * Math.PI * 2
    const pointLatitude = Math.asin(
      Math.sin(latitudeRadians) * Math.cos(angularDistance)
      + Math.cos(latitudeRadians) * Math.sin(angularDistance) * Math.cos(bearing),
    )
    const pointLongitude = longitude * Math.PI / 180 + Math.atan2(
      Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(latitudeRadians),
      Math.cos(angularDistance) - Math.sin(latitudeRadians) * Math.sin(pointLatitude),
    )
    coordinates.push([pointLongitude * 180 / Math.PI, pointLatitude * 180 / Math.PI])
  }
  return { type: 'Polygon', coordinates: [coordinates] }
}

export function MapWorkspace(props: MapWorkspaceProps) {
  const elementRef = useRef<HTMLDivElement>(null)
  const handleRef = useRef<LeafletMapHandle | null>(null)
  const onAoiDrawnRef = useRef(props.onAoiDrawn)
  const onDrawTargetRef = useRef(props.onDrawTarget)
  const drawTargetRef = useRef(props.drawTarget)
  const onPointPickedRef = useRef(props.onPointPicked)
  const interactionModeRef = useRef(props.interactionMode ?? 'aoi')
  const lastHotspotNavRef = useRef<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const searchQueueRef = useRef<Promise<void>>(Promise.resolve())
  const searchDebounceRef = useRef<number | null>(null)
  const lastNominatimAtRef = useRef(0)
  const lastFocusPickedPointRef = useRef(false)
  const chrome = props.chrome ?? 'full'
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState<PlaceSearchResult[]>([])
  const [searchMessage, setSearchMessage] = useState<string | null>(null)
  const [searching, setSearching] = useState(false)
  const [selectedPlace, setSelectedPlace] = useState<string | null>(null)
  const [selectedCentre, setSelectedCentre] = useState<{ lat: number; lon: number } | null>(null)
  const [radiusMetres, setRadiusMetres] = useState(1000)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadErrorDetails, setUploadErrorDetails] = useState<string | null>(null)
  const [uploadTarget, setUploadTarget] = useState<DrawTarget>('main')
  const [aoiInfo, setAoiInfo] = useState<AoiValidationResponse | null>(null)
  const [aoiError, setAoiError] = useState<string | null>(null)
  const [aoiErrorDetails, setAoiErrorDetails] = useState<string | null>(null)
  // Compare Mode keeps separate validation metadata per AOI so A/B never reuse main AOI state.
  const [aoiAInfo, setAoiAInfo] = useState<AoiValidationResponse | null>(null)
  const [aoiBInfo, setAoiBInfo] = useState<AoiValidationResponse | null>(null)
  const [aoiAError, setAoiAError] = useState<string | null>(null)
  const [aoiBError, setAoiBError] = useState<string | null>(null)
  const [cursorPosition, setCursorPosition] = useState<CursorPosition | null>(null)
  const [zoomLevel, setZoomLevel] = useState(5)
  const [coordinateText, setCoordinateText] = useState('')
  const [coordinateError, setCoordinateError] = useState<string | null>(null)
  const [hintVisible, setHintVisible] = useState(() => sessionStorage.getItem('satquery-map-hint-dismissed') !== 'true')
  const [hotspotNavError, setHotspotNavError] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(false)

  onAoiDrawnRef.current = props.onAoiDrawn
  onDrawTargetRef.current = props.onDrawTarget
  drawTargetRef.current = props.drawTarget
  onPointPickedRef.current = props.onPointPicked
  interactionModeRef.current = props.interactionMode ?? 'aoi'

  useEffect(() => {
    if (!elementRef.current || handleRef.current) return
    const map = L.map(elementRef.current, { zoomControl: false, attributionControl: true }).setView([22.8, 78.5], 5)
    map.createPane('referenceLabelsPane')
    map.getPane('referenceLabelsPane')!.style.zIndex = '350'
    map.createPane('analysisPane')
    map.getPane('analysisPane')!.style.zIndex = '400'
    map.createPane('selectedAreaPane')
    map.getPane('selectedAreaPane')!.style.zIndex = '500'

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
    // A new map instance needs its own one-time focus, including under React
    // StrictMode's development double-mount.
    lastFocusPickedPointRef.current = false
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
    map.on('click', (event: any) => {
      if (interactionModeRef.current !== 'pick-point' || drawTargetRef.current) return
      const { lat, lng } = event.latlng || {}
      if (typeof lat !== 'number' || typeof lng !== 'number') return
      // A map click replaces any search result, so clear the search card and
      // keep the picked point as the single source of truth.
      setSearch('')
      setSearchResults([])
      setSelectedPlace(null)
      setSelectedCentre({ lat, lon: lng })
      onPointPickedRef.current?.({ lat, lon: lng, label: `${lat.toFixed(5)}, ${lng.toFixed(5)}` })
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
    let secondFrame = 0
    const frame = window.requestAnimationFrame(() => {
      handleRef.current?.map.invalidateSize()
      secondFrame = window.requestAnimationFrame(() => handleRef.current?.map.invalidateSize())
    })
    return () => {
      window.cancelAnimationFrame(frame)
      if (secondFrame) window.cancelAnimationFrame(secondFrame)
    }
  }, [props.active])

  useEffect(() => {
    const handle = handleRef.current
    if (!handle) return
    try {
      handle.draw?.disable()
    } catch {}
    if (!props.drawTarget) return
    const options = { shapeOptions: { color: '#ffeb00', weight: 3, opacity: 1, fillColor: '#ffeb00', fillOpacity: 0.14 }, showArea: false }
    try {
      if (props.drawTarget === 'main-rectangle') {
        handle.draw = new (L as any).Draw.Rectangle(handle.map, options)
      } else if (props.drawTarget === 'main') {
        handle.draw = new (L as any).Draw.Polygon(handle.map, options)
      } else if (props.drawTarget === 'compare-a' || props.drawTarget === 'compare-b') {
        // For compare areas, use polygon by default (rectangle might not be needed)
        handle.draw = new (L as any).Draw.Polygon(handle.map, { shapeOptions: { color: props.drawTarget === 'compare-a' ? '#ffb72e' : '#48e2d1', weight: 2.5, opacity: 1, fillOpacity: 0.14 }, showArea: false })
      } else {
        handle.draw = null
        return
      }
      handle.draw.enable()
    } catch (e) {
      console.error('draw init error', e)
    }
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
    setAoiAInfo(null)
    setAoiAError(null)
    if (!props.aoiA) return
    void validateAoi(props.aoiA).then((info) => {
      if (!cancelled) setAoiAInfo(info)
    }).catch((error: unknown) => {
      if (!cancelled) {
        const friendly = friendlyApiError(error)
        setAoiAError(`${friendly.message} ${friendly.suggestion}`)
      }
    })
    return () => { cancelled = true }
  }, [props.aoiA])

  useEffect(() => {
    let cancelled = false
    setAoiBInfo(null)
    setAoiBError(null)
    if (!props.aoiB) return
    void validateAoi(props.aoiB).then((info) => {
      if (!cancelled) setAoiBInfo(info)
    }).catch((error: unknown) => {
      if (!cancelled) {
        const friendly = friendlyApiError(error)
        setAoiBError(`${friendly.message} ${friendly.suggestion}`)
      }
    })
    return () => { cancelled = true }
  }, [props.aoiB])

  useEffect(() => {
    const handle = handleRef.current
    if (!handle) return
    const point = props.pickedPoint
    if (!point) {
      if (handle.layers.pickedPointMarker) {
        handle.map.removeLayer(handle.layers.pickedPointMarker)
        delete handle.layers.pickedPointMarker
      }
      return
    }
    const { lat, lon } = point
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return
    if (handle.layers.pickedPointMarker) handle.map.removeLayer(handle.layers.pickedPointMarker)
    handle.layers.pickedPointMarker = L.marker([lat, lon])
      .bindPopup(point.label || `${lat.toFixed(5)}, ${lon.toFixed(5)}`)
      .addTo(handle.map)
      .openPopup()
  }, [props.pickedPoint, props.active])

  // Focus the picked point only when entering the AOI step. Map clicks in
  // point-pick mode must not unexpectedly zoom the map. The retry covers a map
  // that is mounted in the same commit and has not been laid out yet.
  useEffect(() => {
    const shouldFocus = Boolean(props.focusPickedPoint) && props.active
    if (!shouldFocus) {
      lastFocusPickedPointRef.current = false
      return
    }
    if (lastFocusPickedPointRef.current) return
    const point = props.pickedPoint
    if (!point || !Number.isFinite(point.lat) || !Number.isFinite(point.lon)) return
    lastFocusPickedPointRef.current = true
    let retry = 0
    const fly = () => {
      const handle = handleRef.current
      if (!handle) return
      const size = handle.map.getSize()
      if (size.x === 0 || size.y === 0) {
        handle.map.invalidateSize()
        retry = window.setTimeout(fly, 150)
        return
      }
      handle.map.setView([point.lat, point.lon], 14, { animate: false })
    }
    fly()
    return () => window.clearTimeout(retry)
  }, [props.focusPickedPoint, props.pickedPoint, props.active])

  useEffect(() => {
    const handle = handleRef.current
    if (!handle) return
    ;['hotspot-highlight', 'hotspot-centroid'].forEach((key) => {
      const layer = handle.layers[key]
      if (layer) {
        handle.map.removeLayer(layer)
        delete handle.layers[key]
      }
    })
    setHotspotNavError(null)
    const hotspot = props.selectedHotspot ?? null
    if (!hotspot) {
      lastHotspotNavRef.current = null
      return
    }
    const hotspotKey = `${String(hotspot.id)}:${JSON.stringify(hotspot.bbox_lonlat ?? null)}:${JSON.stringify(hotspot.centroid_lonlat ?? null)}`
    const bbox = validHotspotBbox(hotspot.bbox_lonlat)
    const centroid = validHotspotCentroid(hotspot.centroid_lonlat)
    if (bbox) {
      const [minLon, minLat, maxLon, maxLat] = bbox
      const bounds = L.latLngBounds([[minLat, minLon], [maxLat, maxLon]])
      const rect = L.rectangle(bounds, {
        pane: 'selectedAreaPane',
        color: '#00e5ff',
        weight: 3,
        opacity: 1,
        fillColor: '#00e5ff',
        fillOpacity: 0.12,
        dashArray: '6 4',
      }).addTo(handle.map)
      handle.layers['hotspot-highlight'] = rect
      if (props.active && lastHotspotNavRef.current !== hotspotKey) {
        lastHotspotNavRef.current = hotspotKey
        if (bounds.isValid()) handle.map.flyToBounds(bounds, { padding: [48, 48], maxZoom: 17, duration: 0.8 })
      }
      return
    }
    if (centroid) {
      const [lon, lat] = centroid
      const marker = L.circleMarker([lat, lon], {
        pane: 'selectedAreaPane',
        radius: 8,
        color: '#00e5ff',
        weight: 3,
        opacity: 1,
        fillColor: '#00e5ff',
        fillOpacity: 0.2,
      }).addTo(handle.map)
      handle.layers['hotspot-centroid'] = marker
      if (props.active && lastHotspotNavRef.current !== hotspotKey) {
        lastHotspotNavRef.current = hotspotKey
        handle.map.flyTo([lat, lon], Math.max(handle.map.getZoom(), 14), { duration: 0.8 })
      }
      return
    }
    setHotspotNavError('This hotspot cannot be shown on the map because its location information is missing.')
  }, [props.selectedHotspot, props.active])

  useEffect(() => {
    const handle = handleRef.current
    if (!handle || !props.layerInfo || !props.jobId) return
    Object.entries(handle.layers).forEach(([key, layer]) => {
      if (!key.startsWith('raster-')) return
      handle.map.removeLayer(layer)
      delete handle.layers[key]
    })
    props.visibleLayers.forEach((name) => {
      const image = L.imageOverlay(
        `${apiBase}/analysis/${encodeURIComponent(props.jobId!)}/layer/${encodeURIComponent(name)}.png`,
        props.layerInfo!.bounds as any,
        { opacity: props.opacity, interactive: false, pane: 'analysisPane' },
      )
      image.addTo(handle.map)
      handle.layers[`raster-${name}`] = image
    })
  }, [props.layerInfo, props.visibleLayers, props.opacity, props.jobId])

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

  function choosePlace(place: PlaceSearchResult): boolean {
    const lat = Number(place.lat)
    const lon = Number(place.lon)
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      setSearchMessage('This place returned invalid coordinates. Try another location or enter coordinates manually.')
      return false
    }
    const pickPoint = interactionModeRef.current === 'pick-point'
    const handle = handleRef.current
    const map = handle?.map
    if (map && handle) {
      map.invalidateSize()
      const mapSize = map.getSize()
      if (mapSize.x > 0 && mapSize.y > 0) {
        map.setView([lat, lon], 14, { animate: false })
        handle.layers.placeMarker?.remove()
        delete handle.layers.placeMarker
        if (!pickPoint) {
          handle.layers.placeMarker = L.marker([lat, lon]).bindPopup(place.display_name).addTo(map).openPopup()
        }
      }
    }
    setSelectedPlace(place.display_name)
    setSelectedCentre({ lat, lon })
    setSearch(place.display_name)
    setSearchResults([])
    setSearchMessage(null)
    if (pickPoint) {
      // In point-pick mode the shared picked point is the source of truth, so the
      // Explore panel's Continue button enables immediately and the marker is
      // rendered by the pickedPoint effect.
      onPointPickedRef.current?.({ lat, lon, label: place.display_name })
    } else if (!props.exploreMode) {
      void applyRadiusAoi(lat, lon, radiusMetres, place.display_name)
    }
    return true
  }

  async function applyRadiusAoi(latitude: number, longitude: number, metres: number, placeName = selectedPlace ?? 'selected location') {
    const geometry = radiusPolygon(latitude, longitude, metres)
    try {
      await validateAoi(geometry)
      props.onAoiDrawn('main', geometry)
      setSearchMessage(`${placeName} selected with a ${AOI_RADIUS_OPTIONS.find((option) => option.metres === metres)?.label ?? `${metres} m`} radius. You can now ask a question or adjust the area.`)
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

  function handleSearchSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void searchForPlace(search)
  }

  function useMyLocation() {
    setSearchMessage(null)
    if (!navigator.geolocation) {
      setSearchMessage('Location is not available in this browser. You can search for a place or enter coordinates, then draw an area on the map.')
      return
    }
    setSearchMessage('Getting your location… Allow browser permission if asked.')
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords
        handleRef.current?.map.setView([latitude, longitude], 14, { animate: false })
        const pickPoint = interactionModeRef.current === 'pick-point'
        if (pickPoint) {
          onPointPickedRef.current?.({ lat: latitude, lon: longitude, label: 'Your location' })
        } else {
          const marker = L.marker([latitude, longitude]).bindPopup('Your location').addTo(handleRef.current!.map).openPopup()
          handleRef.current?.layers.placeMarker?.remove()
          if (handleRef.current) handleRef.current.layers.placeMarker = marker
        }
        setSelectedPlace('Your location')
        setSelectedCentre({ lat: latitude, lon: longitude })
        if (!pickPoint) void applyRadiusAoi(latitude, longitude, radiusMetres, 'Your location')
      },
      (error) => {
        if (error.code === error.PERMISSION_DENIED) {
          setSearchMessage('Location permission was denied. Next step: allow location access in your browser settings, or search for a place/enter coordinates, then draw an area.')
        } else if (error.code === error.POSITION_UNAVAILABLE) {
          setSearchMessage('Your location could not be determined right now. Next step: search for a place or enter coordinates, then draw an area on the map.')
        } else if (error.code === error.TIMEOUT) {
          setSearchMessage('Location request timed out. Next step: try again, or search for a place/enter coordinates, then draw an area.')
        } else {
          setSearchMessage('Could not get your location. Next step: search for a place or enter coordinates, then draw an area on the map.')
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
      setCoordinateError('Enter coordinates as: latitude, longitude (for example: 28.6139, 77.2090). Latitude must be -90 to 90, longitude -180 to 180.')
      return
    }
    const map = handleRef.current?.map
    if (!map) {
      setCoordinateError('The map is still loading. Please wait a moment and try again.')
      return
    }
    map.invalidateSize()
    const mapSize = map.getSize()
    if (!Number.isFinite(mapSize.x) || !Number.isFinite(mapSize.y) || mapSize.x <= 0 || mapSize.y <= 0) {
      setCoordinateError('The map is not ready for navigation yet. Please wait a moment and try again.')
      return
    }
    setCoordinateError(null)
    map.setView([lat, lon], 14, { animate: false })
    const marker = L.marker([lat, lon]).bindPopup(`${lat.toFixed(5)}, ${lon.toFixed(5)}`).addTo(map).openPopup()
    handleRef.current?.layers.placeMarker?.remove()
    if (handleRef.current) handleRef.current.layers.placeMarker = marker
    setSelectedPlace(`${lat.toFixed(5)}, ${lon.toFixed(5)}`)
    setSearchMessage('Map centered on the entered coordinates. Next step: draw an area on the map to analyze this place.')
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
      if (geometry?.type !== 'Polygon') throw new Error('This file does not contain a single area shape (Polygon). Please upload a GeoJSON Polygon, or draw an area on the map instead.')
      await validateAoi(geometry as PolygonGeometry)
      props.onAoiDrawn(uploadTarget, geometry as PolygonGeometry)
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

  function dismissHint() {
    sessionStorage.setItem('satquery-map-hint-dismissed', 'true')
    setHintVisible(false)
  }

  const drawText = props.drawTarget === 'main'
    ? 'Drawing mode: click on the map to place points for a polygon. Double-click the last point to finish.'
    : props.drawTarget === 'main-rectangle'
      ? 'Drawing mode: click and drag on the map to draw a rectangle.'
      : props.drawTarget === 'compare-a' ? 'Drawing mode: click on the map to draw Area A (a polygon). Double-click to finish.'
        : props.drawTarget === 'compare-b' ? 'Drawing mode: click on the map to draw Area B (a polygon). Double-click to finish.' : null
  return (
    <section className={`map-workspace ${props.interactionMode === 'pick-point' ? 'map-pick-mode' : ''}`} aria-label="Area of interest map">
      <div ref={elementRef} className="map-canvas" />
      {(chrome !== 'minimal' || props.exploreMode) && (
        <div className="map-search-control" style={chrome === 'minimal' ? { top: '56px' } : undefined}>
          <form className="map-search" role="search" onSubmit={handleSearchSubmit}>
            <Icon name="search" />
            <input aria-label="Search a place" value={search} onChange={(event) => handleSearchInput(event.target.value)} placeholder="Find a place, region or address" autoComplete="off" />
            <button type="submit" disabled={searching || !search.trim()} title="Search place" aria-label="Search place">{searching ? <span className="map-spinner" /> : 'Search'}</button>
          </form>
          {searchMessage && <p className="map-feedback" role="status">{searchMessage}</p>}
          {searchResults.length > 0 && <div className="place-results" role="listbox" aria-label="Search results">
            {searchResults.map((place, index) => <button type="button" role="option" key={`${place.lat}-${place.lon}-${index}`} onClick={() => choosePlace(place)}>
              <strong>{place.display_name.split(',').slice(0, 2).join(',')}</strong><span>{place.display_name}</span>
            </button>)}
          </div>}
          {selectedPlace && (props.interactionMode ?? 'aoi') !== 'pick-point' && <div className="selected-place">
            <span>Selected location</span><strong>{selectedPlace}</strong>
            <label className="radius-control">Analysis radius
              <select aria-label="Analysis radius" value={radiusMetres} onChange={changeRadius}>
                {AOI_RADIUS_OPTIONS.map((option) => <option key={option.metres} value={option.metres}>{option.label}</option>)}
              </select>
            </label>
            {(props.exploreMode || props.locationAoiActionLabel) && <button type="button" className="explore-imagery-button" onClick={() => { if (selectedCentre) void applyRadiusAoi(selectedCentre.lat, selectedCentre.lon, radiusMetres, selectedPlace) }}>{props.locationAoiActionLabel ?? 'Get Satellite Images'} <span aria-hidden="true">→</span></button>}
          </div>}
        </div>
      )}

      {chrome !== 'minimal' ? (
        <div className="discovery-controls">
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
      ) : (
        <div className="map-action-row map-essential-controls" style={{ position: 'absolute', zIndex: 450, top: '10px', ...(props.exploreMode ? { left: '10px', right: 'auto' } : { right: '10px' }), display: 'flex', gap: '5px' }}>
          <button className="map-action-icon" type="button" title={fullscreen ? 'Exit full screen map' : 'Full screen map'} aria-label={fullscreen ? 'Exit full screen map' : 'Full screen map'} onClick={() => void toggleFullscreen()}><Icon name="fullscreen" /></button>
        </div>
      )}

      {chrome !== 'minimal' && (
        <>
          <details className="advanced-selection" open={props.selectionExpanded}>
            <summary>{props.exploreMode ? 'Map Selection' : 'Advanced selection'} <span>Draw, upload, or refine an area manually</span></summary>
          <div className="draw-toolbar" aria-label="Area drawing tools">
            {!props.compareMode ? <>
              <button className={`map-tool ${props.drawTarget === 'main-rectangle' ? 'map-tool-active' : ''}`} type="button" onClick={() => props.onDrawTarget(props.drawTarget === 'main-rectangle' ? null : 'main-rectangle')} title="Draw a rectangle area on the map"><Icon name="rectangle" /><span>Draw rectangle</span></button>
              <button className={`map-tool ${props.drawTarget === 'main' ? 'map-tool-active' : ''}`} type="button" onClick={() => props.onDrawTarget(props.drawTarget === 'main' ? null : 'main')} title="Draw a custom shape (polygon) on the map"><Icon name="polygon" /><span>Draw polygon</span></button>
              <button className="map-tool map-tool-clear" type="button" disabled={!props.aoi} onClick={() => props.onAoiDrawn('main', { type: 'Polygon', coordinates: [] })} title="Clear the selected area"><Icon name="clear" /><span>Clear area</span></button>
              <button className="map-tool" type="button" onClick={() => { setUploadTarget('main'); fileRef.current?.click() }} title="Upload an area file (GeoJSON) instead of drawing"><Icon name="upload" /><span>Upload area file (GeoJSON)</span></button>
              <button className="map-tool" type="button" disabled={!props.aoi} onClick={zoomToArea} title="Zoom the map to your selected area"><Icon name="zoom" /><span>Zoom to area</span></button>
            </> : <>
              <button className={`map-tool ${props.drawTarget === 'compare-a' ? 'map-tool-active' : ''}`} type="button" title="Draw Area A on the map" onClick={() => props.onDrawTarget(props.drawTarget === 'compare-a' ? null : 'compare-a')}><span className="compare-swatch compare-swatch-a" /><span>Draw A</span></button>
              <button className={`map-tool ${props.drawTarget === 'compare-b' ? 'map-tool-active' : ''}`} type="button" title="Draw Area B on the map" onClick={() => props.onDrawTarget(props.drawTarget === 'compare-b' ? null : 'compare-b')}><span className="compare-swatch compare-swatch-b" /><span>Draw B</span></button>
            </>}
            <input ref={fileRef} type="file" accept=".geojson,.json,application/geo+json,application/json" className="visually-hidden" onChange={uploadAoi} aria-label="Upload area file (GeoJSON)" />
          </div>
          </details>

          {drawText && <div className="draw-instruction" role="status">{drawText}</div>}
          {uploadError && <div className="map-feedback map-feedback-error map-upload-error" role="alert">{uploadError}{uploadErrorDetails && <details><summary>Error details</summary><code>{uploadErrorDetails}</code></details>}</div>}

          {hintVisible && <div className="first-visit-hint">
            <span>1. Find a place (optional) · 2. Draw an area on the map · 3. Ask a question and run analysis</span>
            <button type="button" title="Dismiss instructions" aria-label="Dismiss instructions" onClick={dismissHint}>×</button>
          </div>}
        </>
      )}

      <div className="map-readouts" aria-live="polite">
        <span>{cursorPosition ? `${cursorPosition.lat.toFixed(5)}°, ${cursorPosition.lon.toFixed(5)}°` : 'Move over the map for coordinates'}</span>
        <span>Zoom {zoomLevel}</span>
      </div>

      {chrome !== 'minimal' && (
        <>
          <div className="aoi-area-readout" aria-live="polite">
            {props.compareMode ? <>
              <span title={aoiAError ?? undefined}><i className="compare-swatch-a" />Area A: {!props.aoiA ? 'not drawn yet' : aoiAError ? 'needs attention' : aoiAInfo ? `${aoiAInfo.area_km2.toFixed(2)} km²` : 'checking…'}</span>
              <span title={aoiBError ?? undefined}><i className="compare-swatch-b" />Area B: {!props.aoiB ? 'not drawn yet' : aoiBError ? 'needs attention' : aoiBInfo ? `${aoiBInfo.area_km2.toFixed(2)} km²` : 'checking…'}</span>
            </> : <>
              <small>SELECTED AREA</small>
              <strong>{aoiInfo ? `${aoiInfo.area_km2.toFixed(2)} km²` : props.aoi ? 'Checking your selected area…' : 'No area selected — draw or upload an area'}</strong>
            </>}
          </div>

          {!props.compareMode && props.aoi && aoiInfo && <div className="aoi-info-card">
            <div className="aoi-info-heading"><strong>Selected area</strong><span>{aoiInfo.geometry_type === 'Polygon' ? 'Shape: polygon' : aoiInfo.geometry_type}</span></div>
            <p className="aoi-info-explain">This is the place on the map your question will be analyzed for.</p>
            <div><span>Size</span><strong>{aoiInfo.area_km2.toFixed(2)} km²</strong></div>
            <div className="copy-center"><span>Centre point</span><strong>{aoiInfo.centre.lat.toFixed(5)}, {aoiInfo.centre.lon.toFixed(5)}</strong>
              <button type="button" title="Copy centre coordinates" onClick={() => void navigator.clipboard.writeText(`${aoiInfo.centre.lat.toFixed(6)}, {aoiInfo.centre.lon.toFixed(6)}`)}>Copy</button>
            </div>
            <div><span>Bounds (edges)</span><strong>{aoiInfo.bounds.map((value) => value.toFixed(4)).join(', ')}</strong></div>
            {aoiInfo.area_km2 < 0.41 && <p className="area-warning">This area is very small. Land-cover classification may not run for areas this small, but vegetation/water index and change analyses can still work. Next step: draw a larger area if you need land-cover results.</p>}
            {aoiInfo.area_km2 > 100 && aoiInfo.area_km2 <= 200 && <p className="area-warning">This is a large area. Analysis may take longer than usual.</p>}
            {aoiInfo.area_km2 > 200 && <p className="area-blocked">This area is too large to analyze. Next step: draw or upload a smaller area (maximum 200 km²).</p>}
          </div>}
          {!props.compareMode && aoiError && <div className="area-blocked" role="alert">{aoiError}{aoiErrorDetails && <details><summary>Error details</summary><code>{aoiErrorDetails}</code></details>}</div>}
          {props.compareMode && (aoiAError || aoiBError) && <div className="area-blocked" role="alert">{[aoiAError ? `Area A: ${aoiAError}` : null, aoiBError ? `Area B: ${aoiBError}` : null].filter(Boolean).join(' ')} Next step: try drawing that area again, or choose a different place or size.</div>}
        </>
      )}
      {props.selectedHotspot && <div className="area-blocked" role="status" aria-live="polite"><strong>Hotspot {String(props.selectedHotspot.id)}</strong> selected on map.{hotspotNavError ? ` ${hotspotNavError}` : ''} {props.onClearSelectedHotspot && <button type="button" className="map-tool map-tool-clear" onClick={props.onClearSelectedHotspot} title="Clear hotspot highlight">Clear hotspot</button>}</div>}
      {!props.selectedHotspot && hotspotNavError && <div className="area-blocked" role="status">{hotspotNavError}</div>}


      {props.layerInfo && Object.keys(props.layerInfo.layers).length > 0 && (
        <div className="map-layer-panel">
          <div className="map-layer-heading">RESULT LAYERS</div>
          <div className="map-layer-list">
            {Object.entries(props.layerInfo.layers).map(([name]) => (
              <label className="map-layer-toggle" key={name}>
                <input
                  type="checkbox"
                  checked={props.visibleLayers.includes(name)}
                  onChange={(event) =>
                    props.setVisibleLayers(event.target.checked ? [...props.visibleLayers, name] : props.visibleLayers.filter((item) => item !== name))
                  } />
                <span>{name.replaceAll('_', ' ')}</span>
              </label>
            ))}
          </div>
          <label className="opacity-control"><span>Opacity</span><input type="range" min="0.1" max="1" step="0.05" value={props.opacity} onChange={(event) => props.setOpacity(Number(event.target.value))} /></label>
          {props.visibleLayers.map((name) => {
            const legend = props.layerInfo!.layers[name]
            return legend ? <div className="map-legend" key={name}>{legend.colors.map((color) => <span key={`${color.value}-${color.hex}`}><i style={{ backgroundColor: color.hex }} />{color.label ?? color.value}</span>)}</div> : null
          })}
        </div>
      )}
      {props.layerError && props.jobId && <div className="map-layer-unavailable">Result map unavailable: {props.layerError}</div>}
    </section>
  )
}
