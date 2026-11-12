import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  compareAnalysis,
  deleteHistoryRecord,
  downloadExport,
  friendlyApiError,
  getImageryScenes,
  getLayers,
  getHistory,
  getHistoryRecord,
  getJob,
  investigate,
  startAnalysis,
  validateAoi,
} from './api/client'
import { MapWorkspace, type DrawTarget } from './components/MapWorkspace'
import { ExplorePanel } from './components/ExplorePanel'
import { ResultsWorkspace } from './components/ResultsWorkspace'
import { Sidebar, type NavView } from './components/layout/Sidebar'
import { AppHeader } from './components/layout/AppHeader'
import { HomeView } from './views/HomeView'
import { UploadView } from './views/UploadView'
import { HistoryView } from './views/HistoryView'
import { BenchmarksView } from './views/BenchmarksView'
import { SettingsView } from './views/SettingsView'
import { MultiSensorView } from './views/MultiSensorView'
import { ChangeHotspotsView } from './views/ChangeHotspotsView'
import type { AoiValidationResponse, ChangeHotspot, CompareResponse, HistoryRecord, HistorySummary, ImageryScene, InvestigationResult, JobResponse, LayersResponse, PolygonGeometry } from './types/analysis'
import { useLanguage } from './i18n'
import { deleteSavedAoi, loadSavedAois, saveAoi, savedAoiStorageNote, type SavedAoi } from './utils/savedAois'
import './App.css'

type SpeechRecognitionLike = {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: any) => void) | null
  onerror: ((event: any) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

const examples = [
  'Did vegetation health decrease between June and September?',
  'Show the vegetation trend over the last year',
  'Show land cover for June',
  'What percentage of the area is water in June?',
]

function todayIso() { return new Date().toISOString().slice(0, 10) }
function monthAgoIso(months: number) {
  const value = new Date()
  value.setMonth(value.getMonth() - months)
  return value.toISOString().slice(0, 10)
}
type ExploreStage = 'choose' | 'search' | 'map-pick' | 'define-aoi' | 'imagery' | 'ask'
export default function App() {
  const [currentView, setCurrentView] = useState<NavView>('home')
  const [historyItems, setHistoryItems] = useState<HistorySummary[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [activeRecord, setActiveRecord] = useState<HistoryRecord | null>(null)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [job, setJob] = useState<JobResponse | null>(null)
  const [query, setQuery] = useState('')
  const [queryStart, setQueryStart] = useState('')
  const [queryEnd, setQueryEnd] = useState('')
  const [aoi, setAoi] = useState<PolygonGeometry | null>(null)
  const [aoiA, setAoiA] = useState<PolygonGeometry | null>(null)
  const [aoiB, setAoiB] = useState<PolygonGeometry | null>(null)
  const [compareMode, setCompareMode] = useState(false)
  const [startInCompareMode, setStartInCompareMode] = useState(false)
  const [investigationMode, setInvestigationMode] = useState(false)
  const [investigationResult, setInvestigationResult] = useState<InvestigationResult | null>(null)
  const [investigationLoading, setInvestigationLoading] = useState(false)
  const [drawTarget, setDrawTarget] = useState<DrawTarget | null>(null)
  const [compareResult, setCompareResult] = useState<CompareResponse | null>(null)
  const [selectedHotspot, setSelectedHotspot] = useState<ChangeHotspot | null>(null)
  const [clarification, setClarification] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [requestErrorDetails, setRequestErrorDetails] = useState<{ code: string; raw: string } | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [compareLoading, setCompareLoading] = useState(false)
  const [exporting, setExporting] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const [compareMonthA, setCompareMonthA] = useState('June')
  const [compareMonthB, setCompareMonthB] = useState('September')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [navOpen, setNavOpen] = useState(false)
  const [showResults, setShowResults] = useState(false)
  // Two-mode location selection flow. Every Explore session starts at the
  // method chooser, then converges on the same AOI -> imagery -> question stages.
  const [exploreStage, setExploreStage] = useState<ExploreStage>('choose')
  const [locationMethod, setLocationMethod] = useState<'search' | 'map' | null>(null)
  const [pickedLocation, setPickedLocation] = useState<{ label: string; lat: number; lon: number } | null>(null)
  const [savedAois, setSavedAois] = useState<SavedAoi[]>(() => loadSavedAois())
  const [saveAoiName, setSaveAoiName] = useState('')
  const [savedAoiMessage, setSavedAoiMessage] = useState<string | null>(null)
  const [imageStart, setImageStart] = useState(monthAgoIso(12))
  const [imageEnd, setImageEnd] = useState(todayIso())
  const [maxCloud, setMaxCloud] = useState(40)
  const [layerInfo, setLayerInfo] = useState<LayersResponse | null>(null)
  const [layerError, setLayerError] = useState<string | null>(null)
  const [visibleLayers, setVisibleLayers] = useState<string[]>([])
  const [opacity, setOpacity] = useState(0.72)
  const [scenes, setScenes] = useState<ImageryScene[]>([])
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null)
  const [scenesQueryKey, setScenesQueryKey] = useState<string | null>(null)
  const [sceneSelectionMessage, setSceneSelectionMessage] = useState<string | null>(null)
  const [scenesLoading, setScenesLoading] = useState(false)
  const [scenesError, setScenesError] = useState<string | null>(null)
  const [scenesErrorDetails, setScenesErrorDetails] = useState<string | null>(null)
  const [aoiInfo, setAoiInfo] = useState<AoiValidationResponse | null>(null)
  const [aoiError, setAoiError] = useState<string | null>(null)
  const [aoiErrorDetails, setAoiErrorDetails] = useState<string | null>(null)
  const [aoiValidationLoading, setAoiValidationLoading] = useState(false)
  const currentScenesQueryKey = aoi ? JSON.stringify({ aoi, imageStart, imageEnd, maxCloud }) : null

  // Follow-up conversation state (preserves AOI context across questions).
  const [followUps, setFollowUps] = useState<Array<{ question: string; result: InvestigationResult | null; error: string | null }>>([])
  const [followUpLoading, setFollowUpLoading] = useState(false)

  // Mirrors of the latest query and AOI so the job poller can read them without
  // being torn down and restarted on every keystroke or redraw.
  const queryRef = useRef(query)
  const aoiRef = useRef(aoi)
  const navButtonRef = useRef<HTMLButtonElement | null>(null)
  const navWasOpenRef = useRef(false)
  const { speechLang } = useLanguage()
  const [voiceStatus, setVoiceStatus] = useState<'idle' | 'listening' | 'processing' | 'unsupported' | 'denied' | 'error' | 'no-result'>('idle')
  const speechRecognitionRef = useRef<SpeechRecognitionLike | null>(null)

  useEffect(() => {
    let cancelled = false
    if (!aoi) {
      setScenes([])
      setScenesQueryKey(null)
      setSelectedSceneId(null)
      setSceneSelectionMessage(null)
      setScenesError(null)
      return
    }
    const requestKey = JSON.stringify({ aoi, imageStart, imageEnd, maxCloud })
    setScenesQueryKey(null)
    setScenesLoading(true)
    setScenesError(null)
    setScenesErrorDetails(null)
    const timer = window.setTimeout(() => {
      void getImageryScenes(aoi, imageStart, imageEnd, maxCloud).then((items) => {
        if (!cancelled) {
          setScenes(items)
          setScenesQueryKey(requestKey)
        }
      }).catch((error: unknown) => {
        if (!cancelled) {
          const friendly = friendlyApiError(error)
          setScenesError(`${friendly.message} ${friendly.suggestion}`)
          setScenesErrorDetails(error instanceof ApiError ? `${error.code}: ${error.rawMessage}` : null)
          setScenes([])
          setScenesQueryKey(null)
          setSelectedSceneId(null)
          setSceneSelectionMessage('Scene discovery failed. The previous selection was cleared; retry the scene search before running an analysis.')
        }
      }).finally(() => {
        if (!cancelled) setScenesLoading(false)
      })
    }, 250)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [aoi, imageStart, imageEnd, maxCloud])

  useEffect(() => {
    if (!selectedSceneId || scenesQueryKey !== currentScenesQueryKey) return
    const scene = scenes.find((item) => item.item_id === selectedSceneId)
    if (!scene || scene.data_available === false ||
        (scene.coverage_fraction != null && scene.coverage_fraction < 0.99)) {
      setSelectedSceneId(null)
      setSceneSelectionMessage('The selected scene is no longer available for the current area and imagery filters. Select another scene to continue.')
    }
  }, [selectedSceneId, scenes, scenesQueryKey, currentScenesQueryKey])

  useEffect(() => {
    if (!aoi || compareMode) {
      setAoiInfo(null)
      setAoiError(null)
      setAoiErrorDetails(null)
      setAoiValidationLoading(false)
      return
    }
    let cancelled = false
    setAoiInfo(null)
    setAoiError(null)
    setAoiErrorDetails(null)
    setAoiValidationLoading(true)
    validateAoi(aoi).then((info) => {
      if (cancelled) return
      if (!info.valid) {
        setAoiInfo(null)
        setAoiError('The selected area could not be validated. Draw or upload a different area.')
        return
      }
      setAoiInfo(info)
    }).catch((error: unknown) => {
      if (cancelled) return
      const friendly = friendlyApiError(error)
      setAoiInfo(null)
      setAoiError(`${friendly.message} ${friendly.suggestion}`)
      setAoiErrorDetails(error instanceof ApiError
        ? `${error.code}: ${error.rawMessage}`
        : error instanceof Error ? error.message : 'Unknown validation error')
    }).finally(() => {
      if (!cancelled) setAoiValidationLoading(false)
    })
    return () => { cancelled = true }
  }, [aoi, compareMode])

  function navigateTo(view: NavView) {
    setCurrentView(view)
    setNavOpen(false)
  }

  function startNewExploration() {
    setExploreStage('choose')
    setLocationMethod(null)
    setPickedLocation(null)
    setQuery('')
    setAoi(null)
    setAoiA(null)
    setAoiB(null)
    setDrawTarget(null)
    setScenes([])
    setSelectedSceneId(null)
    setScenesQueryKey(null)
    setSceneSelectionMessage(null)
    setScenesError(null)
    setScenesErrorDetails(null)
    setCompareMode(false)
    setStartInCompareMode(false)
    setInvestigationMode(false)
    setCompareResult(null)
    setInvestigationResult(null)
    setActiveRecord(null)
    setActiveJobId(null)
    setJob(null)
    setSelectedHotspot(null)
    setRequestError(null)
    setRequestErrorDetails(null)
    setClarification(null)
    setShowResults(false)
  }

  function chooseSearchMethod() {
    setLocationMethod('search')
    setPickedLocation(null)
    setAoi(null)
    setDrawTarget(null)
    setExploreStage('search')
  }

  function chooseMapMethod() {
    setLocationMethod('map')
    setPickedLocation(null)
    setAoi(null)
    setDrawTarget(null)
    setExploreStage('map-pick')
  }

  function handleLocationSelected(location: { label?: string; lat: number; lon: number }) {
    setPickedLocation({
      label: location.label ?? `${location.lat.toFixed(5)}, ${location.lon.toFixed(5)}`,
      lat: location.lat,
      lon: location.lon,
    })
  }

  function goBackFromStage() {
    if (exploreStage === 'search' || exploreStage === 'map-pick') {
      setExploreStage('choose')
      setLocationMethod(null)
      setPickedLocation(null)
      setDrawTarget(null)
      return
    }
    if (exploreStage === 'define-aoi') {
      // Leaving the AOI step must cancel any active draw handler. Otherwise the
      // next map click is consumed by leaflet-draw instead of picking a point.
      setDrawTarget(null)
      setExploreStage(locationMethod === 'map' ? 'map-pick' : 'search')
      return
    }
    if (exploreStage === 'imagery') {
      setExploreStage('define-aoi')
      return
    }
    if (exploreStage === 'ask') {
      setExploreStage('imagery')
    }
  }

  function continueFromStage() {
    if (exploreStage === 'search' || exploreStage === 'map-pick') {
      if (!pickedLocation) return
      setDrawTarget(null)
      setExploreStage('define-aoi')
      return
    }
    if (exploreStage === 'define-aoi') {
      if (!aoi) return
      setDrawTarget(null)
      setExploreStage('imagery')
      return
    }
    if (exploreStage === 'imagery') {
      if (startInCompareMode) {
        setCompareMode(true)
        setStartInCompareMode(false)
      }
      setExploreStage('ask')
    }
  }

  function handleStartTask(taskQuery: string, options?: { compareMode?: boolean }) {
    startNewExploration()
    setQuery(taskQuery)
    if (options?.compareMode) {
      setStartInCompareMode(true)
    }

    setCurrentView('explore')
    setNavOpen(false)
  }

  function startVoiceInput() {
    const w = window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike }
    const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition
    if (!Ctor) {
      setVoiceStatus('unsupported')
      return
    }
    try {
      speechRecognitionRef.current?.abort()
    } catch { /* ignore */ }
    const recognition = new Ctor()
    speechRecognitionRef.current = recognition
    recognition.continuous = false
    recognition.interimResults = false
    recognition.lang = speechLang
    setVoiceStatus('listening')
    recognition.onresult = (event: any) => {
      const transcript = Array.from(event.results || [])
        .map((r: any) => r[0]?.transcript || '')
        .join(' ')
        .trim()
      if (transcript) {
        setQuery((prev) => (prev.trim() ? `${prev.trim()} ${transcript}` : transcript))
        setVoiceStatus('idle')
      } else {
        setVoiceStatus('no-result')
      }
    }
    recognition.onerror = (event: any) => {
      if (event?.error === 'not-allowed' || event?.error === 'service-not-allowed') setVoiceStatus('denied')
      else setVoiceStatus('error')
    }
    recognition.onend = () => {
      setVoiceStatus((s) => (s === 'listening' || s === 'processing' ? 'idle' : s))
      speechRecognitionRef.current = null
    }
    try {
      recognition.start()
    } catch {
      setVoiceStatus('error')
    }
  }

  useEffect(() => () => { try { speechRecognitionRef.current?.abort() } catch { /* ignore */ } }, [])

  function showRequestError(error: unknown) {
    const friendly = friendlyApiError(error)
    setRequestError(`${friendly.message} ${friendly.suggestion}`)
    setRequestErrorDetails(friendly.code ? {
      code: friendly.code,
      raw: error instanceof ApiError ? error.rawMessage : error instanceof Error ? error.message : 'Unknown error',
    } : null)
  }

  function showCompareError(error: unknown) {
    if (error instanceof ApiError) {
      setRequestError(`${error.rawMessage} Next step: widen the date range or allow more cloud cover, then retry.`)
      setRequestErrorDetails({ code: error.code, raw: error.rawMessage })
      return
    }
    setRequestError(error instanceof Error ? error.message : 'Compare could not be completed.')
    setRequestErrorDetails(null)
  }

  async function refreshHistory() {
    setHistoryLoading(true)
    setHistoryError(null)
    try {
      setHistoryItems(await getHistory())
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : 'Could not load history.')
    } finally {
      setHistoryLoading(false)
    }
  }

  useEffect(() => { void refreshHistory() }, [])

  const completedLayerJobId = activeRecord?.status === 'completed' ? activeRecord.id : null
  useEffect(() => {
    if (!completedLayerJobId) {
      setLayerInfo(null)
      setVisibleLayers([])
      setLayerError(null)
      return
    }
    let cancelled = false
    setLayerError(null)
    getLayers(completedLayerJobId).then((info: LayersResponse) => {
      if (!cancelled) {
        setLayerInfo(info)
        setVisibleLayers(Object.keys(info.layers).slice(0, 1))
      }
    }).catch((error: unknown) => {
      if (!cancelled) {
        setLayerInfo(null)
        setLayerError(error instanceof Error ? error.message : 'Raster layers are unavailable.')
        setVisibleLayers([])
      }
    })
    return () => { cancelled = true }
  }, [completedLayerJobId])

  useEffect(() => {
    queryRef.current = query
    aoiRef.current = aoi
  }, [query, aoi])

  // The drawer only exists below the shell breakpoint; close it if the window grows.
  useEffect(() => {
    const narrow = window.matchMedia('(max-width: 720px)')
    const handleChange = () => {
      if (!narrow.matches) setNavOpen(false)
    }
    narrow.addEventListener('change', handleChange)
    return () => narrow.removeEventListener('change', handleChange)
  }, [])

  // Escape closes the drawer; focus then returns to the toggle that opened it.
  useEffect(() => {
    if (!navOpen) {
      if (navWasOpenRef.current) {
        navWasOpenRef.current = false
        navButtonRef.current?.focus()
      }
      return
    }
    navWasOpenRef.current = true
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setNavOpen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [navOpen])

  useEffect(() => {
    if (!activeJobId) return
    let cancelled = false
    let timer: number | undefined

    const poll = async () => {
      try {
        const next = await getJob(activeJobId)
        if (cancelled) return
        setJob(next)
        if (next.status === 'queued' || next.status === 'processing') {
          timer = window.setTimeout(poll, 1500)
          return
        }
        if (next.status === 'completed') {
          try {
            const record = await getHistoryRecord(activeJobId)
            if (!cancelled) {
              setActiveRecord(record)
              setAoi(record.aoi)
              if (record.result && 'facts' in record.result) setShowResults(true)
            }
          } catch {
            if (!cancelled && next.result) {
              setActiveRecord({
                id: activeJobId,
                created: next.created ?? new Date().toISOString(),
                query: queryRef.current,
                structured_query: next.structured_query ?? {},
                aoi: aoiRef.current ?? { type: 'Polygon', coordinates: [] },
                operation: next.result.facts.operation,
                status: 'completed',
                result: next.result,
              })
              setShowResults(true)
            }
          }
        } else if (next.status === 'failed') {
          try {
            const record = await getHistoryRecord(activeJobId)
            if (!cancelled) setActiveRecord(record)
          } catch {
            // Keep the in-memory job error visible if persistence is unavailable.
          }
        }
        if (!cancelled) {
          setActiveJobId(null)
          void refreshHistory()
        }
      } catch (error) {
        if (!cancelled) {
          setRequestError(error instanceof Error ? error.message : 'Could not retrieve job status.')
          setActiveJobId(null)
        }
      }
    }

    void poll()
    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [activeJobId])

  function setArea(target: DrawTarget, geometry: PolygonGeometry) {
    const mainArea = target === 'main' || target === 'main-rectangle'
    if (geometry.coordinates.length === 0) {
      if (mainArea) setAoi(null)
      if (target === 'compare-a') setAoiA(null)
      if (target === 'compare-b') setAoiB(null)
      setActiveRecord(null)
      setActiveJobId(null)
      setJob(null)
      setCompareResult(null)
      setInvestigationResult(null)
      setSelectedHotspot(null)
      return
    }
    if (mainArea) setAoi(geometry)
    if (target === 'compare-a') setAoiA(geometry)
    if (target === 'compare-b') setAoiB(geometry)
    setActiveRecord(null)
    setActiveJobId(null)
    setJob(null)
    setCompareResult(null)
    setSelectedHotspot(null)
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setShowResults(false)
    setClarification(null)
    setRequestError(null)
    setRequestErrorDetails(null)
    setCompareResult(null)
    setInvestigationResult(null)
    if (!query.trim()) {
      setRequestError('Enter an analysis question.')
      return
    }
    const dateClause = queryStart && queryEnd
      ? queryStart === queryEnd ? ` on ${queryStart}` : ` between ${queryStart} and ${queryEnd}`
      : queryStart ? ` on ${queryStart}` : ''
    const submittedQuery = investigationMode ? query.trim() : `${query.trim()}${dateClause}`
    if (investigationMode) {
      if (!aoi) {
        setRequestError('Please select an area on the map first. Draw a shape or upload an area file, then investigate.')
        return
      }
      setInvestigationLoading(true)
      setActiveRecord(null)
      setJob(null)
      setActiveJobId(null)
      try {
        const result = await investigate({
          query: submittedQuery,
          aoi,
          reference_date: new Date().toISOString().slice(0, 10),
          max_cloud: maxCloud,
          date_a: queryStart ? { start: queryStart, end: queryStart } : null,
          date_b: queryEnd ? { start: queryEnd, end: queryEnd } : null,
        })
        setInvestigationResult(result)
        setShowResults(true)
      } catch (error) {
        showRequestError(error)
      } finally {
        setInvestigationLoading(false)
      }
      return
    }
    if (compareMode) {
      if (!aoiA || !aoiB) {
        setRequestError('Please draw both Area A and Area B on the map first. Use the Draw A and Draw B buttons, then try comparing again.')
        setCompareResult(null)
        setInvestigationResult(null)
        return
      }
      setCompareLoading(true)
      setRequestError(null)
      setRequestErrorDetails(null)
      setCompareResult(null)
      setActiveRecord(null)
      setJob(null)
      setSelectedHotspot(null)
      try {
        const result = await compareAnalysis(submittedQuery, aoiA, aoiB, maxCloud)
        setCompareResult(result)
        setShowResults(true)
      } catch (error) {
        setCompareResult(null)
        showCompareError(error)
      } finally {
        setCompareLoading(false)
      }
      return
    }
    if (!aoi) {
      setRequestError('Please select an area on the map first. Draw a shape or upload an area file, then run your analysis.')
      return
    }

    let selectedSceneForRun: string | null = null
    if (selectedSceneId) {
      const selectedScene = scenes.find((scene) => scene.item_id === selectedSceneId)
      const selectedSceneIsValid = !scenesLoading && scenesQueryKey === currentScenesQueryKey &&
        selectedScene && selectedScene.data_available !== false &&
        selectedScene.cloud_cover != null && selectedScene.cloud_cover <= maxCloud &&
        selectedScene.datetime.slice(0, 10) >= imageStart && selectedScene.datetime.slice(0, 10) <= imageEnd &&
        (selectedScene.coverage_fraction == null || selectedScene.coverage_fraction >= 0.99)
      if (!selectedSceneIsValid) {
        setSelectedSceneId(null)
        setSceneSelectionMessage('The selected scene is stale or does not meet the current imagery filters. Select a current scene, or continue without a selected scene.')
        setRequestError('The selected scene is no longer valid for the current AOI and imagery filters. Select another scene or clear the selection.')
        return
      }
      selectedSceneForRun = selectedSceneId
    }

    setSubmitting(true)
    setActiveRecord(null)
    setJob(null)
    setActiveJobId(null)
    setSelectedHotspot(null)
    try {
      const response = await startAnalysis(submittedQuery, aoi, maxCloud, selectedSceneForRun)
      if (response.status === 'needs_clarification') {
        setClarification(response.message ?? 'The question needs more detail.')
      } else if (response.job_id) {
        setActiveJobId(response.job_id)
        setJob({ job_id: response.job_id, status: 'queued' })
      }
    } catch (error) {
      showRequestError(error)
    } finally {
      setSubmitting(false)
    }
  }

  async function submitFollowUp(question: string, aoi: PolygonGeometry | null, dateOverride?: { start: string; end: string } | null) {
    if (!question.trim()) return
    if (!aoi) {
      setFollowUps(prev => [...prev, { question, result: null, error: 'No area selected. Please draw an area on the map first.' }])
      return
    }
    setFollowUpLoading(true)
    setRequestError(null)
    try {
      const result = await investigate({
        query: question.trim(),
        aoi,
        reference_date: new Date().toISOString().slice(0, 10),
        max_cloud: maxCloud,
        date_a: dateOverride ? { start: dateOverride.start, end: dateOverride.end } : null,
        date_b: null,
        series_range: dateOverride ? { start: dateOverride.start, end: dateOverride.end } : null,
      })
      setFollowUps(prev => [...prev, { question, result, error: null }])
      setShowResults(true)
    } catch (error) {
      setFollowUps(prev => [...prev, { question, result: null, error: error instanceof Error ? error.message : 'Follow-up analysis failed.' }])
      setShowResults(true)
    } finally {
      setFollowUpLoading(false)
    }
  }

  async function openHistory(id: string) {
    setRequestError(null)
    setClarification(null)
    setCompareResult(null)
    setSelectedHotspot(null)
    try {
      const record = await getHistoryRecord(id)
      setActiveRecord(record)
      setAoi(record.aoi)
      setAoiA(null)
      setAoiB(null)
      setCompareMode(false)
      setQuery(record.query)
      setJob(null)
      setActiveJobId(null)
      setExploreStage('ask')
      setLocationMethod(null)
      setPickedLocation(null)
      setShowResults(Boolean(record.result && 'facts' in record.result))
    } catch (error) {
      showRequestError(error)
    }
  }

  async function removeHistory(id: string) {
    try {
      await deleteHistoryRecord(id)
      setHistoryItems((items) => items.filter((item) => item.id !== id))
      if (activeRecord?.id === id) setActiveRecord(null)
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : 'Could not delete this record.')
    }
  }

  async function handleExport(format: 'csv' | 'geojson') {
    if (!activeRecord) return
    setExporting(format)
    setExportError(null)
    try {
      await downloadExport(activeRecord.id, format)
    } catch (error) {
      setExportError(error instanceof Error ? `Export failed. ${error.message} Next step: try again, or check that the analysis completed successfully.` : 'Export failed. Next step: try again.')
    } finally {
      setExporting(null)
    }
  }

  async function retryFailedAnalysis() {
    const record = activeRecord
    if (!record || !record.query?.trim() || !record.aoi) return
    setRequestError(null)
    setRequestErrorDetails(null)
    setClarification(null)
    setActiveRecord(null)
    setJob(null)
    setActiveJobId(null)
    setSubmitting(true)
    try {
      const response = await startAnalysis(record.query, record.aoi, maxCloud, selectedSceneId)
      if (response.status === 'needs_clarification') setClarification(response.message ?? 'The question needs more detail.')
      else if (response.job_id) { setActiveJobId(response.job_id); setJob({ job_id: response.job_id, status: 'queued' }) }
    } catch (error) { showRequestError(error) } finally { setSubmitting(false) }
  }

  async function retryCompare() {
    if (!aoiA || !aoiB || !query.trim()) return
    const dateClause = queryStart && queryEnd ? (queryStart === queryEnd ? ` on ${queryStart}` : ` between ${queryStart} and ${queryEnd}`) : queryStart ? ` on ${queryStart}` : ''
    setCompareLoading(true)
    setRequestError(null)
    setRequestErrorDetails(null)
    setCompareResult(null)
    try {
      setCompareResult(await compareAnalysis(`${query.trim()}${dateClause}`, aoiA, aoiB, maxCloud))
      setShowResults(true)
    }
    catch (error) { showCompareError(error) } finally { setCompareLoading(false) }
  }

  async function retryInvestigation() {
    if (!aoi || !query.trim()) return
    setInvestigationLoading(true)
    setRequestError(null)
    setRequestErrorDetails(null)
    setInvestigationResult(null)
    try {
      setInvestigationResult(await investigate({
        query: query.trim(),
        aoi,
        reference_date: new Date().toISOString().slice(0, 10),
        max_cloud: maxCloud,
        date_a: queryStart ? { start: queryStart, end: queryStart } : null,
        date_b: queryEnd ? { start: queryEnd, end: queryEnd } : null,
      }))
      setShowResults(true)
    } catch (error) {
      showRequestError(error)
    } finally {
      setInvestigationLoading(false)
    }
  }

  const recordResult = activeRecord?.result
  const failedError = recordResult && 'error' in recordResult ? recordResult.error : job?.error
  const failedFriendly = failedError ? friendlyApiError(new ApiError(failedError.code, failedError.message)) : null
  const jobBusy = submitting || compareLoading || Boolean(activeJobId)

  function applyCompareMonths() {
    setQuery(`Did vegetation health decrease between ${compareMonthA} and ${compareMonthB}?`)
    setQueryStart('')
    setQueryEnd('')
  }

  function handleSaveAoi(geometry: PolygonGeometry | null, label: string) {
    setSavedAoiMessage(null)
    try {
      if (!geometry) throw new Error(`No ${label} is selected to save.`)
      setSavedAois(saveAoi(saveAoiName, geometry))
      setSaveAoiName('')
      setSavedAoiMessage(`Saved "${saveAoiName.trim() || 'area'}". ${savedAoiStorageNote()}`)
    } catch (error) {
      setSavedAoiMessage(error instanceof Error ? error.message : 'Could not save the area.')
    }
  }

  function handleRestoreAoi(item: SavedAoi, target: DrawTarget) {
    setSavedAoiMessage(null)
    if (!item.geometry || item.geometry.type !== 'Polygon' || !Array.isArray(item.geometry.coordinates?.[0])) {
      setSavedAoiMessage('This saved area has invalid or missing geometry and cannot be restored.')
      return
    }
    setArea(target, item.geometry)
    setSavedAoiMessage(`Restored "${item.name}" to ${target === 'main' ? 'the map' : target === 'compare-a' ? 'Area A' : 'Area B'}.`)
  }

  function handleDeleteAoi(item: SavedAoi) {
    setSavedAoiMessage(null)
    if (!window.confirm(`Delete saved area "${item.name}"? This cannot be undone.`)) return
    setSavedAois(deleteSavedAoi(item.id))
    setSavedAoiMessage(`Deleted "${item.name}".`)
  }

  return (
    <div className="satquery-app-container">
      <Sidebar
        permanent
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((value) => !value)}
        currentView={currentView}
        onSelectView={navigateTo}
        activeJobCount={activeJobId ? 1 : 0}
        open={navOpen}
        onClose={() => setNavOpen(false)}
      />

      {navOpen && <div className="nav-backdrop" aria-hidden="true" onClick={() => setNavOpen(false)} />}

        <div className={`app-main-content-layout ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
        <AppHeader
          currentView={currentView}
          activeJobId={activeJobId}
          jobStatus={job?.status}
          navOpen={navOpen}
          onToggleNav={() => setNavOpen((value) => !value)}
          menuButtonRef={navButtonRef}
        />

        <div className="app-view-body" inert={navOpen}>
          {currentView === 'home' && (
            <HomeView
              onNavigate={navigateTo}
              onStartTask={handleStartTask}
              recentQueries={historyItems}
              onOpenQuery={(id) => {
                void openHistory(id)
                setCurrentView('explore')
              }}
              loadingHistory={historyLoading}
            />
          )}

          {currentView === 'upload' && (
            <UploadView />
          )}

          {currentView === 'history' && (
            <HistoryView
              items={historyItems}
              loading={historyLoading}
              error={historyError}
              onSelect={(id) => {
                void openHistory(id)
                setCurrentView('explore')
              }}
              onDelete={(id) => void removeHistory(id)}
              onRefresh={() => void refreshHistory()}
            />
          )}

          {currentView === 'multisensor' && (
          <MultiSensorView
            record={activeRecord}
            recentAnalyses={historyItems}
            historyLoading={historyLoading}
            historyError={historyError}
            onRefreshHistory={() => void refreshHistory()}
            onRecordSelected={(selected) => {
              setActiveRecord(selected)
              setAoi(selected.aoi)
              setAoiA(null)
              setAoiB(null)
              setCompareMode(false)
              setInvestigationMode(false)
              setCompareResult(null)
              setInvestigationResult(null)
              setSelectedHotspot(null)
              setQuery(selected.query)
              setJob(null)
              setActiveJobId(null)
              setRequestError(null)
              setShowResults(false)
            }}
            onRecordCleared={() => setActiveRecord(null)}
            onOpenMap={() => setCurrentView('explore')}
            currentAoi={aoi}
            savedAois={savedAois}
          />
          )}

          {currentView === 'change' && (
            <ChangeHotspotsView
              record={activeRecord}
              recentAnalyses={historyItems}
              onChooseHistory={(id) => {
                void openHistory(id)
                setCurrentView('change')
              }}
              selectedHotspot={selectedHotspot}
              onSelectHotspot={(hotspot) => {
                setSelectedHotspot(hotspot)
                setCurrentView('explore')
              }}
              onClearSelectedHotspot={() => setSelectedHotspot(null)}
            />
          )}

          {currentView === 'benchmarks' && <BenchmarksView />}

          {currentView === 'settings' && <SettingsView />}

          {currentView === 'explore' && (showResults && (Boolean(compareResult) || Boolean(investigationResult) || Boolean(recordResult && 'facts' in recordResult)) ? (
            <ResultsWorkspace
              record={activeRecord}
              compare={compareResult}
              aoiA={aoiA}
              aoiB={aoiB}
              investigationResult={investigationResult}
              followUps={followUps}
              followUpLoading={followUpLoading}
              onSubmitFollowUp={(question, dateOverride) => void submitFollowUp(question, activeRecord?.aoi ?? aoi, dateOverride)}
              onReturn={() => setShowResults(false)}
            />
          ) : (
            <div className="explore-view-host" style={{ display: currentView === 'explore' ? 'block' : 'none' }}>
              {exploreStage === 'choose' ? (
                <div className="location-choice-screen" aria-label="Choose how to select a location">
                  <div className="location-choice-inner">
                    <p className="section-kicker">EXPLORE LOCATION</p>
                    <h1>How would you like to choose a location?</h1>
                    <p className="location-choice-lead">Pick one method to begin. You will define the exact analysis area before imagery and analysis.</p>
                    <div className="location-choice-grid">
                      <button type="button" className="location-choice-card" onClick={chooseSearchMethod}>
                        <span className="location-choice-icon" aria-hidden="true">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="10.8" cy="10.8" r="6.3" /><path d="m16 16 4.5 4.5" /></svg>
                        </span>
                        <span className="location-choice-title">Search Location</span>
                        <span className="location-choice-desc">Find a city, village, lake, landmark or specific place by name.</span>
                        <span className="location-choice-action">Search Location</span>
                      </button>
                      <button type="button" className="location-choice-card" onClick={chooseMapMethod}>
                        <span className="location-choice-icon" aria-hidden="true">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z" /><path d="M9 3v15m6-12v15" /></svg>
                        </span>
                        <span className="location-choice-title">Select on Map</span>
                        <span className="location-choice-desc">Open an interactive map and choose your location directly.</span>
                        <span className="location-choice-action">Select on Map</span>
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
              <main className={`workspace ${exploreStage === 'search' ? 'workspace-single' : ''}`} id="workspace">
                {exploreStage !== 'search' && (
                <MapWorkspace
                  chrome="minimal"
                  aoi={aoi}
                  aoiA={aoiA}
                  aoiB={aoiB}
                  active={currentView === 'explore'}
                  compareMode={compareMode}
                  drawTarget={drawTarget}
                  jobId={activeRecord?.status === 'completed' ? activeRecord.id : null}
                  layerInfo={layerInfo}
                  layerError={layerError}
                  visibleLayers={visibleLayers}
                  opacity={opacity}
                  setVisibleLayers={setVisibleLayers}
                  setOpacity={setOpacity}
                  selectedHotspot={selectedHotspot}
                  exploreMode={currentView === 'explore'}
                  interactionMode={exploreStage === 'map-pick' ? 'pick-point' : 'aoi'}
                  pickedPoint={exploreStage === 'map-pick' || exploreStage === 'define-aoi' ? pickedLocation : null}
                  focusPickedPoint={exploreStage === 'define-aoi'}
                  onPointPicked={handleLocationSelected}
                  onDrawTarget={setDrawTarget}
                  onAoiDrawn={setArea}
                  onClearSelectedHotspot={() => setSelectedHotspot(null)}
                />
                )}
                <ExplorePanel
                  stage={exploreStage === 'search' ? 'search' : exploreStage === 'map-pick' ? 'map-pick' : exploreStage === 'define-aoi' ? 'define-aoi' : exploreStage === 'imagery' ? 'imagery' : 'ask'}
                  selectedLocation={pickedLocation}
                  onLocationSelected={handleLocationSelected}
                  onBack={goBackFromStage}
                  onContinue={continueFromStage}
                  continueDisabled={
                    exploreStage === 'search' || exploreStage === 'map-pick' ? !pickedLocation
                      : exploreStage === 'define-aoi' ? !aoi || aoiValidationLoading || !aoiInfo || Boolean(aoiError)
                        : false
                  }
                  onNewExploration={startNewExploration}
                  aoi={aoi}
                  aoiA={aoiA}
                  aoiB={aoiB}
                  compareMode={compareMode}
                  investigationMode={investigationMode}
                  drawTarget={drawTarget}
                  onDrawTarget={setDrawTarget}
                  onAoiDrawn={setArea}
                  aoiInfo={aoiInfo}
                  aoiError={aoiError}
                  aoiErrorDetails={aoiErrorDetails}
                  aoiValidationLoading={aoiValidationLoading}
                  jobId={activeRecord?.status === 'completed' ? activeRecord.id : null}
                  layerInfo={layerInfo}
                  visibleLayers={visibleLayers}
                  setVisibleLayers={setVisibleLayers}
                  opacity={opacity}
                  setOpacity={setOpacity}
                  query={query}
                  setQuery={setQuery}
                  queryStart={queryStart}
                  setQueryStart={setQueryStart}
                  queryEnd={queryEnd}
                  setQueryEnd={setQueryEnd}
                  imageStart={imageStart}
                  setImageStart={setImageStart}
                  imageEnd={imageEnd}
                  setImageEnd={setImageEnd}
                  maxCloud={maxCloud}
                  setMaxCloud={setMaxCloud}
                  scenes={scenes}
                  scenesLoading={scenesLoading}
                  scenesError={scenesError}
                  scenesErrorDetails={scenesErrorDetails}
                  sceneSelectionMessage={sceneSelectionMessage}
                  selectedSceneId={selectedSceneId}
                  setSelectedSceneId={(id) => {
                    setSelectedSceneId(id)
                    setSceneSelectionMessage(null)
                  }}
                  onSubmit={handleSubmit}
                  jobBusy={jobBusy}
                  investigationLoading={investigationLoading}
                  comparisonLoading={compareLoading}
                  clarification={clarification}
                  requestError={requestError}
                  requestErrorDetails={requestErrorDetails}
                  failedFriendly={failedFriendly}
                  investigationResult={investigationResult}
                  retryCompare={retryCompare}
                  retryInvestigation={retryInvestigation}
                  retryFailedAnalysis={retryFailedAnalysis}
                  submitting={submitting}
                  savedAois={savedAois}
                  saveAoiName={saveAoiName}
                  setSaveAoiName={setSaveAoiName}
                  savedAoiMessage={savedAoiMessage}
                  handleSaveAoi={handleSaveAoi}
                  handleRestoreAoi={handleRestoreAoi}
                  handleDeleteAoi={handleDeleteAoi}
                  voiceStatus={voiceStatus}
                  startVoiceInput={startVoiceInput}
                  setVoiceStatus={setVoiceStatus}
                  examples={examples}
                  comparing={compareMode}
                  investigating={investigationMode}
                  onToggleInvestigation={() => {
                    setInvestigationMode((current) => !current)
                    setCompareMode(false)
                    setInvestigationResult(null)
                    setRequestError(null)
                    setActiveRecord(null)
                    setJob(null)
                  }}
                  onToggleCompare={() => {
                    setCompareMode((current) => !current)
                    setInvestigationMode(false)
                    setCompareResult(null)
                    setRequestError(null)
                    setActiveRecord(null)
                    setJob(null)
                    setSelectedHotspot(null)
                  }}
                  compareMonthA={compareMonthA}
                  compareMonthB={compareMonthB}
                  setCompareMonthA={setCompareMonthA}
                  setCompareMonthB={setCompareMonthB}
                  applyCompareMonths={applyCompareMonths}
                  onExport={handleExport}
                  exporting={exporting}
                  exportError={exportError}
                  activeRecord={{ aoi, query }}
                />
              </main>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
