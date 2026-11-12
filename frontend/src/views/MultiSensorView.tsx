import React, { useEffect, useMemo, useRef, useState } from 'react'
import { analyzeCaptionScene, analyzeFusion, analyzeSarScene, ApiError, friendlyApiError, getCaptionImageUrl, getFusionPairs, getHistoryRecord, getImageryScenes, getLayerUrl, getLayers, getSarScenes } from '../api/client'
import { MapWorkspace, type DrawTarget } from '../components/MapWorkspace'
import { useLanguage } from '../i18n'
import type { AnalysisResult, CaptionResult, FusionPair, FusionResult, HistoryRecord, HistorySummary, ImageryScene, LayersResponse, PolygonGeometry, SarAnalysisResult, SarScene } from '../types/analysis'
import type { SavedAoi } from '../utils/savedAois'

type Props = {
  record: HistoryRecord | null
  recentAnalyses?: HistorySummary[]
  historyLoading?: boolean
  historyError?: string | null
  onRefreshHistory?: () => void
  onRecordSelected?: (record: HistoryRecord) => void
  onRecordCleared?: () => void
  onOpenMap?: () => void
  currentAoi?: PolygonGeometry | null
  savedAois?: SavedAoi[]
}
type SubTab = 'indices' | 'change' | 'trend'

const CATEGORY_OPERATION: Record<SubTab, string> = {
  indices: 'index_stats',
  change: 'change_detection',
  trend: 'time_series',
}

const OPERATION_CATEGORY: Record<string, SubTab> = {
  index_stats: 'indices',
  change_detection: 'change',
  time_series: 'trend',
}

function operationForRecord(record: HistoryRecord | null): string | null {
  const operation = record?.structured_query?.operation
  return typeof operation === 'string' ? operation : null
}

function resultForRecord(record: HistoryRecord | null): AnalysisResult | null {
  const value: unknown = record?.result
  if (!value || typeof value !== 'object' || 'error' in value) return null
  const candidate = value as Record<string, unknown>
  if (!candidate.evidence || typeof candidate.evidence !== 'object' ||
      !candidate.facts || typeof candidate.facts !== 'object') return null
  return candidate as unknown as AnalysisResult
}

function validateSelectedRecord(record: HistoryRecord | null, expectedOperation: string): string | null {
  if (!record || typeof record !== 'object') return 'multisensor.malformedRecord'
  if (record.status !== 'completed') return 'multisensor.recordNotCompleted'
  if (operationForRecord(record) !== expectedOperation) return 'multisensor.incompatibleOperation'

  const result = resultForRecord(record)
  if (!result || !result.evidence || !Array.isArray(result.evidence.scenes) || result.evidence.scenes.length === 0) {
    return 'multisensor.malformedRecord'
  }
  if (result.evidence.operation !== expectedOperation || result.facts.operation !== expectedOperation) {
    return 'multisensor.malformedRecord'
  }

  const identities = result.evidence.scenes.map((scene) => scene?.sensor_identity)
  if (identities.some((identity) => identity === 'other')) return 'multisensor.otherSensorUnavailable'
  if (identities.some((identity) => identity !== 'sentinel-2')) return 'multisensor.unknownSensorUnavailable'
  if (result.evidence.scenes.some((scene) => !scene.item_id || !scene.datetime || !Number.isFinite(Date.parse(scene.datetime)))) {
    return 'multisensor.malformedRecord'
  }

  if (expectedOperation === 'index_stats' && (!result.facts.stats || typeof result.facts.stats !== 'object')) {
    return 'multisensor.malformedRecord'
  }
  if (expectedOperation === 'change_detection' && (!result.facts.change || typeof result.facts.change !== 'object')) {
    return 'multisensor.malformedRecord'
  }
  if (expectedOperation === 'time_series') {
    const series = result.facts.series
    if (!series || !Array.isArray(series.dates) || !Array.isArray(series.values) ||
        series.dates.length === 0 || series.dates.length !== series.values.length) {
      return 'multisensor.malformedRecord'
    }
  }
  return null
}

function initialTab(record: HistoryRecord | null): SubTab {
  return OPERATION_CATEGORY[operationForRecord(record) ?? ''] ?? 'indices'
}

function identityLabel(identity: HistorySummary['sensor_identity'], t: (key: string, fallback?: string) => string): string {
  if (identity === 'sentinel-2') return t('multisensor.identitySentinel2')
  if (identity === 'other') return t('multisensor.identityOther')
  return t('multisensor.identityUnknown')
}

function operationLabel(operation: string, t: (key: string, fallback?: string) => string): string {
  const keys: Record<string, string> = {
    index_stats: 'multisensor.operationIndex',
    change_detection: 'multisensor.operationChange',
    time_series: 'multisensor.operationTrend',
    land_cover: 'multisensor.operationLandCover',
  }
  return keys[operation] ? t(keys[operation]) : t('multisensor.operationOther')
}

function formatDate(value: string | null | undefined, locale: string): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(parsed)
}

function dateInputValue(value: Date): string {
  const shifted = new Date(value.getTime() - value.getTimezoneOffset() * 60_000)
  return shifted.toISOString().slice(0, 10)
}

function sarApiErrorMessage(error: unknown, fallbackKey: string, t: (key: string, fallback?: string) => string): string {
  if (!(error instanceof ApiError)) return t(fallbackKey)
  if (error.code === 'no_imagery') return error.rawMessage
  const friendly = friendlyApiError(error)
  return `${friendly.message} ${friendly.suggestion}`
}

export const MultiSensorView: React.FC<Props> = ({
  record,
  recentAnalyses = [],
  historyLoading = false,
  historyError = null,
  onRefreshHistory,
  onRecordSelected,
  onRecordCleared,
  onOpenMap,
  currentAoi = null,
  savedAois = [],
}) => {
  const { t, lang } = useLanguage()
  const [activeTab, setActiveTab] = useState<SubTab>(() => initialTab(record))
  const initialOperation = CATEGORY_OPERATION[initialTab(record)]
  const initialSelectedRecord = record && validateSelectedRecord(record, initialOperation) === null ? record : null
  const [selectedRecordId, setSelectedRecordId] = useState(initialSelectedRecord?.id ?? '')
  const [selectedRecord, setSelectedRecord] = useState<HistoryRecord | null>(initialSelectedRecord)
  const [recordLoading, setRecordLoading] = useState(false)
  const [recordError, setRecordError] = useState<string | null>(null)
  const [unavailableIds, setUnavailableIds] = useState<Record<string, string>>({})
  const [verifiedRecords, setVerifiedRecords] = useState<Record<string, HistoryRecord>>(() =>
    initialSelectedRecord ? { [initialSelectedRecord.id]: initialSelectedRecord } : {})
  const [layerInfo, setLayerInfo] = useState<LayersResponse | null>(null)
  const [layerLoading, setLayerLoading] = useState(false)
  const [layerError, setLayerError] = useState<string | null>(null)
  const [imageErrorKey, setImageErrorKey] = useState<string | null>(null)
  const [sarAoi, setSarAoi] = useState<PolygonGeometry | null>(currentAoi ?? initialSelectedRecord?.aoi ?? null)
  const [sarAoiSource, setSarAoiSource] = useState<'current' | 'saved' | 'map' | 'history' | null>(
    currentAoi ? 'current' : initialSelectedRecord?.aoi ? 'history' : null,
  )
  const [savedAoiId, setSavedAoiId] = useState('')
  const [showSarMap, setShowSarMap] = useState(false)
  const [sarDrawTarget, setSarDrawTarget] = useState<DrawTarget | null>(null)
  const [sarStart, setSarStart] = useState(() => dateInputValue(new Date(Date.now() - 30 * 86400000)))
  const [sarEnd, setSarEnd] = useState(() => dateInputValue(new Date()))
  const [sarScenes, setSarScenes] = useState<SarScene[]>([])
  const [sarSearched, setSarSearched] = useState(false)
  const [sarSceneId, setSarSceneId] = useState('')
  const [sarSearching, setSarSearching] = useState(false)
  const [sarRunning, setSarRunning] = useState(false)
  const [sarError, setSarError] = useState<string | null>(null)
  const [sarResult, setSarResult] = useState<SarAnalysisResult | null>(null)
  const [sarSelectedHistoryId, setSarSelectedHistoryId] = useState('')
  const [fusionPairs, setFusionPairs] = useState<FusionPair[]>([])
  const [fusionPairKey, setFusionPairKey] = useState('')
  const [fusionOpticalPreviews, setFusionOpticalPreviews] = useState<Record<string, string>>({})
  const [fusionSearching, setFusionSearching] = useState(false)
  const [fusionRunning, setFusionRunning] = useState(false)
  const [fusionError, setFusionError] = useState<string | null>(null)
  const [fusionResult, setFusionResult] = useState<FusionResult | null>(null)
  const [captionScenes, setCaptionScenes] = useState<ImageryScene[]>([])
  const [captionSearched, setCaptionSearched] = useState(false)
  const [captionSceneId, setCaptionSceneId] = useState('')
  const [captionSearching, setCaptionSearching] = useState(false)
  const [captionRunning, setCaptionRunning] = useState(false)
  const [captionError, setCaptionError] = useState<string | null>(null)
  const [captionResult, setCaptionResult] = useState<CaptionResult | null>(null)
  const [captionJobId, setCaptionJobId] = useState('')
  const [captionImageFailed, setCaptionImageFailed] = useState(false)
  const tabButtons = useRef<Record<SubTab, HTMLButtonElement | null>>({ indices: null, change: null, trend: null })
  const recordRequest = useRef(0)
  const layerRequest = useRef(0)
  const verificationRequest = useRef(0)

  const expectedOperation = CATEGORY_OPERATION[activeTab]
  const result = resultForRecord(selectedRecord)
  const categoryRecords = useMemo(() => recentAnalyses.filter((item) => item.operation === expectedOperation), [recentAnalyses, expectedOperation])
  const verificationCandidates = useMemo(() => categoryRecords.filter((item) =>
    item.status === 'completed' && item.sensor_identity === 'sentinel-2' &&
    !verifiedRecords[item.id] && !unavailableIds[item.id]), [categoryRecords, verifiedRecords, unavailableIds])
  const selectableRecords = categoryRecords.filter((item) =>
    item.status === 'completed' && item.sensor_identity === 'sentinel-2' &&
    Boolean(verifiedRecords[item.id]) && !unavailableIds[item.id])
  const anyVerifiedOptical = recentAnalyses.some((item) =>
    item.status === 'completed' && item.sensor_identity === 'sentinel-2' &&
    Object.values(CATEGORY_OPERATION).includes(item.operation as typeof CATEGORY_OPERATION[SubTab]))
  const otherHistory = recentAnalyses.filter((item) =>
    !selectableRecords.some((available) => available.id === item.id) &&
    !verificationCandidates.some((candidate) => candidate.id === item.id))
  const requestedLayer = activeTab === 'indices' ? 'index' : activeTab === 'change' ? 'diff' : null
  const imageKey = selectedRecord && requestedLayer ? `${selectedRecord.id}:${requestedLayer}` : null
  const availableLayer = requestedLayer ? layerInfo?.layers[requestedLayer] : undefined
  const sarHistory = recentAnalyses.filter((item) => item.operation === 'sar_backscatter')
  const sarEvidenceScene = sarResult?.evidence.scenes[0]

  function resetCaptionWorkspace() {
    setCaptionScenes([])
    setCaptionSearched(false)
    setCaptionSceneId('')
    setCaptionError(null)
    setCaptionResult(null)
    setCaptionJobId('')
    setCaptionImageFailed(false)
  }

  function clearSarDiscovery() {
    setSarScenes([])
    setSarSearched(false)
    setSarSceneId('')
    setSarError(null)
    setFusionPairs([])
    setFusionPairKey('')
    setFusionOpticalPreviews({})
    setFusionError(null)
    setFusionResult(null)
    resetCaptionWorkspace()
  }

  function selectSarAoi(geometry: PolygonGeometry | null, source: 'current' | 'saved' | 'map') {
    setSarAoi(geometry)
    setSarAoiSource(geometry ? source : null)
    if (source !== 'saved') setSavedAoiId('')
    setSarSelectedHistoryId('')
    setSarResult(null)
    clearSarDiscovery()
  }

  function handleSarMapAoiDrawn(target: DrawTarget, geometry: PolygonGeometry) {
    if (target === 'main' || target === 'main-rectangle') {
      selectSarAoi(geometry.coordinates.length > 0 ? geometry : null, 'map')
    }
  }

  async function searchSarScenes() {
    if (!sarAoi) {
      setSarError('multisensor.sarNeedsAoi')
      return
    }
    if (sarEnd < sarStart) {
      setSarError('multisensor.sarInvalidDates')
      return
    }
    setSarSearching(true)
    setSarSearched(false)
    setSarError(null)
    setSarScenes([])
    setSarSceneId('')
    setSarSelectedHistoryId('')
    setSarResult(null)
    try {
      setSarScenes(await getSarScenes(sarAoi, sarStart, sarEnd))
      setSarSearched(true)
    } catch (error) {
      setSarSearched(true)
      setSarError(sarApiErrorMessage(error, 'multisensor.sarSearchFailed', t))
    } finally {
      setSarSearching(false)
    }
  }

  async function runSarAnalysis() {
    if (!sarAoi || !sarSceneId) return
    setSarRunning(true)
    setSarError(null)
    try {
      const response = await analyzeSarScene(sarAoi, sarSceneId, sarStart, sarEnd)
      setSarResult(response.result)
      setSarSelectedHistoryId(response.job_id)
      onRefreshHistory?.()
    } catch (error) {
      setSarError(sarApiErrorMessage(error, 'multisensor.sarAnalysisFailed', t))
    } finally {
      setSarRunning(false)
    }
  }

  async function searchFusionPairs() {
    if (!sarAoi) { setFusionError('Select an AOI first.'); return }
    if (sarEnd < sarStart) { setFusionError('End date must be on or after start date.'); return }
    setFusionSearching(true); setFusionError(null); setFusionPairs([]); setFusionPairKey(''); setFusionOpticalPreviews({}); setFusionResult(null)
    try {
      const response = await getFusionPairs(sarAoi, sarStart, sarEnd, 40)
      setFusionPairs(response.pairs)
      if (!response.pairs.length) setFusionError(`No full-coverage optical/SAR pairs were found within ${response.max_temporal_separation_days} days.`)
      else {
        try {
          const opticalScenes = await getImageryScenes(sarAoi, sarStart, sarEnd, 40)
          setFusionOpticalPreviews(Object.fromEntries(
            opticalScenes
              .filter((scene): scene is ImageryScene & { preview_url: string } =>
                typeof scene.preview_url === 'string' && scene.preview_url.length > 0)
              .map((scene) => [scene.item_id, scene.preview_url]),
          ))
        } catch {
          setFusionOpticalPreviews({})
        }
      }
    } catch (error) { setFusionError(sarApiErrorMessage(error, 'multisensor.sarSearchFailed', t)) } finally { setFusionSearching(false) }
  }

  async function runFusion() {
    const pair = fusionPairs.find((item) => `${item.optical.item_id}|${item.sar.item_id}` === fusionPairKey)
    if (!sarAoi || !pair) return
    setFusionRunning(true); setFusionError(null)
    try {
      const response = await analyzeFusion(sarAoi, pair.optical.item_id, pair.sar.item_id, sarStart, sarEnd, 40)
      setFusionResult(response.result)
      onRefreshHistory?.()
    } catch (error) { setFusionError(sarApiErrorMessage(error, 'multisensor.sarAnalysisFailed', t)) } finally { setFusionRunning(false) }
  }

  async function searchCaptionScenes() {
    if (!sarAoi) { setCaptionError('multisensor.capNeedsAoi'); return }
    if (sarEnd < sarStart) { setCaptionError('multisensor.sarInvalidDates'); return }
    setCaptionSearching(true)
    setCaptionSearched(false)
    setCaptionError(null)
    setCaptionResult(null)
    setCaptionJobId('')
    setCaptionImageFailed(false)
    try {
      setCaptionScenes(await getImageryScenes(sarAoi, sarStart, sarEnd, 40))
      setCaptionSearched(true)
    } catch (error) {
      setCaptionSearched(true)
      setCaptionError(sarApiErrorMessage(error, 'multisensor.capSearchFailed', t))
    } finally {
      setCaptionSearching(false)
    }
  }

  async function runCaptionAnalysis() {
    if (!sarAoi || !captionSceneId) return
    setCaptionRunning(true)
    setCaptionError(null)
    try {
      const response = await analyzeCaptionScene(sarAoi, captionSceneId, sarStart, sarEnd, 40)
      setCaptionResult(response.result)
      setCaptionJobId(response.job_id)
      setCaptionImageFailed(false)
      onRefreshHistory?.()
    } catch (error) {
      setCaptionError(sarApiErrorMessage(error, 'multisensor.capAnalysisFailed', t))
    } finally {
      setCaptionRunning(false)
    }
  }

  async function selectSarHistory(id: string) {
    setSarSelectedHistoryId(id)
    setSarResult(null)
    setSarError(null)
    try {
      const saved = await getHistoryRecord(id)
      const value: unknown = saved.result
      const savedFacts = value && typeof value === 'object' && 'facts' in value
        ? (value as { facts?: Record<string, unknown> }).facts
        : undefined
      if (saved.status !== 'completed' || !savedFacts || savedFacts.operation !== 'sar_backscatter' ||
          !('vv' in savedFacts) || !('vh' in savedFacts) || !('evidence' in (value as object))) {
        setSarError('multisensor.sarSavedResultInvalid')
        return
      }
      setSarAoi(saved.aoi)
      setSarAoiSource('history')
      setSavedAoiId('')
      setSarScenes([])
      setSarSearched(false)
      setSarSceneId('')
      resetCaptionWorkspace()
      setSarResult(value as SarAnalysisResult)
    } catch {
      setSarError('multisensor.sarHistoryLoadFailed')
    }
  }

  function clearSelection(notifyParent = true) {
    recordRequest.current += 1
    layerRequest.current += 1
    setSelectedRecordId('')
    setSelectedRecord(null)
    setRecordLoading(false)
    setRecordError(null)
    setLayerInfo(null)
    setLayerLoading(false)
    setLayerError(null)
    setImageErrorKey(null)
    if (notifyParent) onRecordCleared?.()
  }

  function changeCategory(nextTab: SubTab) {
    if (nextTab === activeTab) return
    const nextOperation = CATEGORY_OPERATION[nextTab]
    if (selectedRecord && operationForRecord(selectedRecord) !== nextOperation) clearSelection()
    else if (recordLoading && recentAnalyses.find((item) => item.id === selectedRecordId)?.operation !== nextOperation) clearSelection()
    setActiveTab(nextTab)
    setLayerInfo(null)
    setLayerError(null)
    setLayerLoading(false)
    setImageErrorKey(null)
  }

  useEffect(() => {
    if (verificationCandidates.length === 0) return
    let cancelled = false
    const requestId = ++verificationRequest.current
    Promise.all(verificationCandidates.map(async (summary) => {
      try {
        const fullRecord = await getHistoryRecord(summary.id)
        const reason = fullRecord.id === summary.id
          ? validateSelectedRecord(fullRecord, expectedOperation)
          : 'multisensor.malformedRecord'
        return { id: summary.id, fullRecord, reason: reason ?? null }
      } catch (error) {
        const reason = error instanceof ApiError && error.code === 'http_404'
          ? 'multisensor.recordMissing'
          : 'multisensor.recordLoadError'
        return { id: summary.id, fullRecord: null, reason }
      }
    })).then((checks) => {
      if (cancelled || requestId !== verificationRequest.current) return
      const validRecords: Record<string, HistoryRecord> = {}
      const rejected: Record<string, string> = {}
      for (const check of checks) {
        if (check.fullRecord && !check.reason) validRecords[check.id] = check.fullRecord
        else rejected[check.id] = check.reason ?? 'multisensor.malformedRecord'
      }
      if (Object.keys(validRecords).length > 0) {
        setVerifiedRecords((current) => ({ ...current, ...validRecords }))
      }
      if (Object.keys(rejected).length > 0) {
        setUnavailableIds((current) => ({ ...current, ...rejected }))
      }
    })
    return () => {
      cancelled = true
      if (requestId === verificationRequest.current) verificationRequest.current += 1
    }
  }, [expectedOperation, verificationCandidates])

  async function selectRecord(id: string) {
    const summary = recentAnalyses.find((item) => item.id === id)
    if (!summary || summary.status !== 'completed' || summary.operation !== expectedOperation ||
        summary.sensor_identity !== 'sentinel-2' || unavailableIds[id]) return

    const requestId = ++recordRequest.current
    layerRequest.current += 1
    setSelectedRecordId(id)
    setSelectedRecord(null)
    setRecordLoading(true)
    setRecordError(null)
    setLayerInfo(null)
    setLayerLoading(false)
    setLayerError(null)
    setImageErrorKey(null)

    try {
      const fullRecord = await getHistoryRecord(id)
      if (requestId !== recordRequest.current) return
      const validationError = validateSelectedRecord(fullRecord, expectedOperation)
      if (fullRecord.id !== id || validationError) {
        const reason = fullRecord.id !== id ? 'multisensor.malformedRecord' : validationError
        setRecordError(reason ?? 'multisensor.malformedRecord')
        setUnavailableIds((current) => ({ ...current, [id]: reason ?? 'multisensor.malformedRecord' }))
        setSelectedRecordId('')
        return
      }
      setSelectedRecord(fullRecord)
      setSarAoi(fullRecord.aoi)
      setSarAoiSource('history')
      setSavedAoiId('')
      setSarScenes([])
      setSarSearched(false)
      setSarSceneId('')
      setSarResult(null)
      setSarSelectedHistoryId('')
      resetCaptionWorkspace()
      onRecordSelected?.(fullRecord)
    } catch (reason) {
      if (requestId !== recordRequest.current) return
      const messageKey = reason instanceof ApiError && reason.code === 'http_404'
        ? 'multisensor.recordMissing'
        : 'multisensor.recordLoadError'
      setRecordError(messageKey)
      setUnavailableIds((current) => ({ ...current, [id]: messageKey }))
      setSelectedRecordId('')
    } finally {
      if (requestId === recordRequest.current) setRecordLoading(false)
    }
  }

  useEffect(() => () => {
    recordRequest.current += 1
    layerRequest.current += 1
  }, [])

  useEffect(() => {
    const selectedId = selectedRecord?.id
    setLayerInfo(null)
    setLayerError(null)
    setImageErrorKey(null)
    if (!selectedId || !requestedLayer) {
      setLayerLoading(false)
      return
    }

    const requestId = ++layerRequest.current
    setLayerLoading(true)
    getLayers(selectedId).then((response) => {
      if (requestId === layerRequest.current && selectedRecord?.id === selectedId) setLayerInfo(response)
    }).catch(() => {
      if (requestId === layerRequest.current && selectedRecord?.id === selectedId) setLayerError('multisensor.noRaster')
    }).finally(() => {
      if (requestId === layerRequest.current) setLayerLoading(false)
    })
    return () => { layerRequest.current += 1 }
  }, [selectedRecord?.id, requestedLayer])

  function unavailableReason(item: HistorySummary): string {
    if (unavailableIds[item.id]) return unavailableIds[item.id]
    if (item.status !== 'completed') return `status.${item.status}`
    if (item.operation !== expectedOperation) return 'multisensor.incompatibleOperation'
    if (item.sensor_identity === 'other') return 'multisensor.otherSensorUnavailable'
    if (item.sensor_identity !== 'sentinel-2') return 'multisensor.unknownSensorUnavailable'
    return 'multisensor.unavailableRecord'
  }

  function handleTabKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const tabs: SubTab[] = ['indices', 'change', 'trend']
    const currentIndex = tabs.indexOf(activeTab)
    let nextIndex = currentIndex
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % tabs.length
    else if (event.key === 'ArrowLeft') nextIndex = (currentIndex + tabs.length - 1) % tabs.length
    else if (event.key === 'Home') nextIndex = 0
    else if (event.key === 'End') nextIndex = tabs.length - 1
    else return
    event.preventDefault()
    const next = tabs[nextIndex]
    changeCategory(next)
    tabButtons.current[next]?.focus()
  }

  const locale = lang === 'hi' ? 'hi-IN' : lang === 'te' ? 'te-IN' : 'en-US'

  return (
    <div className="multisensor-view-container">
      <div className="multisensor-intro">
        <div>
          <h2>{t('multisensor.pageTitle')}</h2>
          <p>{t('multisensor.pageSubtitle')}</p>
        </div>
        <div className="multisensor-capability-indicators" aria-label={t('multisensor.capabilities')}>
          <span className="multisensor-capability available"><i aria-hidden="true" />{t('multisensor.sentinel2Available')}</span>
          <span className="multisensor-capability available"><i aria-hidden="true" />{t('multisensor.sentinel1SummaryAvailable')}</span>
          <span className="multisensor-capability available"><i aria-hidden="true" />{t('multisensor.captioningAvailable')}</span>
        </div>
      </div>
      <div className="multisensor-top-tabs" role="tablist" aria-label={t('multisensor.categories')} onKeyDown={handleTabKeyDown}>
        {(['indices', 'change', 'trend'] as SubTab[]).map((tab) => (
          <button
            key={tab}
            ref={(element) => { tabButtons.current[tab] = element }}
            type="button"
            role="tab"
            id={`multisensor-tab-${tab}`}
            aria-selected={activeTab === tab}
            aria-controls="multisensor-category-panel"
            tabIndex={activeTab === tab ? 0 : -1}
            className={`sub-tab-btn ${activeTab === tab ? 'active' : ''}`}
            onClick={() => changeCategory(tab)}
          >
            {t(`multisensor.${tab}`)}
          </button>
        ))}
      </div>

      <section role="tabpanel" id="multisensor-category-panel" aria-labelledby={`multisensor-tab-${activeTab}`} className="multisensor-dashboard" tabIndex={0}>
        <div className="multisensor-dashboard-grid">
          <aside className="multisensor-selector-card" aria-labelledby="multisensor-selector-title">
            <div className="multisensor-section-heading">
              <div>
                <h2 id="multisensor-selector-title">{t('multisensor.yourResults')}</h2>
                <p>{t('multisensor.selectorHelp')}</p>
              </div>
              <button type="button" className="filter-btn" onClick={onRefreshHistory} disabled={historyLoading || !onRefreshHistory}>
                {historyLoading ? t('history.refreshing') : t('common.refresh')}
              </button>
            </div>

            {historyError && <p className="multisensor-inline-alert" role="alert">{t('multisensor.historyLoadError')}</p>}
            {historyLoading && recentAnalyses.length === 0 ? (
              <p className="multisensor-state" role="status">{t('multisensor.historyLoading')}</p>
            ) : (
              <>
                <div className="multisensor-record-list" role="list" aria-label={t('multisensor.resultHistory')}>
                  {selectableRecords.map((item) => {
                    const dates = item.acquisition_dates?.length ? item.acquisition_dates.map((date) => formatDate(date, locale)).join(', ') : formatDate(item.created, locale)
                    const label = `${item.query}; ${operationLabel(item.operation, t)}; ${dates}; ${identityLabel(item.sensor_identity, t)}`
                    return (
                      <div className="multisensor-record-list-item" role="listitem" key={item.id}>
                        <button
                          type="button"
                          className={`multisensor-record-button ${selectedRecordId === item.id ? 'selected' : ''}`}
                          aria-pressed={selectedRecordId === item.id}
                          aria-label={label}
                          onClick={() => void selectRecord(item.id)}
                          disabled={recordLoading && selectedRecordId === item.id}
                        >
                          <span className="multisensor-record-query">{item.query}</span>
                          <span className="multisensor-record-meta">
                            <span>{operationLabel(item.operation, t)}</span>
                            <span>{t('multisensor.acquired')}: {dates}</span>
                            <span>{t('multisensor.aoiArea')}: {item.aoi_area_km2 == null ? '—' : `${item.aoi_area_km2.toFixed(2)} km²`}</span>
                            <span>{t('multisensor.identity')}: {identityLabel(item.sensor_identity, t)}{item.sensor ? ` (${item.sensor})` : ''}</span>
                          </span>
                        </button>
                      </div>
                    )
                  })}
                </div>
                {selectableRecords.length > 0 && (
                  <p className="multisensor-selector-count"><strong>{selectableRecords.length}</strong> {t('multisensor.completedResults')}</p>
                )}
                {verificationCandidates.length > 0 && selectableRecords.length === 0 && (
                  <p className="multisensor-state" role="status">{t('multisensor.verifyingResults')}</p>
                )}

                {otherHistory.length > 0 && (
                  <details className="multisensor-unavailable-list">
                    <summary>{t('multisensor.historyDiagnostics')} ({otherHistory.length})</summary>
                    <p>{t('multisensor.diagnosticsHelp')}</p>
                    <ul>
                      {otherHistory.map((item) => (
                        <li key={item.id}>
                          <strong>{item.query}</strong>
                          <span>{operationLabel(item.operation, t)} · {formatDate(item.created, locale)}</span>
                          <span>{t('history.status')}: {t(`status.${item.status}`, item.status)} · {identityLabel(item.sensor_identity, t)}</span>
                          <span>{t('multisensor.unavailableReason')}: {t(unavailableReason(item), item.status)}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </>
            )}
          </aside>

          <section className="multisensor-overview-card" aria-labelledby="multisensor-overview-title">
            <div className="multisensor-overview-heading">
              <div>
                <h2 id="multisensor-overview-title">{t('multisensor.analysisOverview')}</h2>
                <p>{selectedRecord ? operationLabel(expectedOperation, t) : t('multisensor.overviewHelp')}</p>
              </div>
              {selectedRecord && <button type="button" className="filter-btn" onClick={() => clearSelection()}>{t('multisensor.clearSelection')}</button>}
            </div>

            {recordError && <p className="multisensor-inline-alert" role="alert">{t(recordError)}</p>}
            {recordLoading && <p className="multisensor-state" role="status">{t('multisensor.recordLoading')}</p>}
            {historyLoading && recentAnalyses.length === 0 && !recordLoading && <p className="multisensor-state" role="status">{t('multisensor.historyLoading')}</p>}
            {verificationCandidates.length > 0 && selectableRecords.length === 0 && !recordLoading && <p className="multisensor-state" role="status">{t('multisensor.verifyingResults')}</p>}
            {historyError && recentAnalyses.length === 0 && !recordLoading && <p className="multisensor-state" role="alert">{t('multisensor.historyUnavailable')}</p>}

            {!recordLoading && selectedRecord && result ? (
              <div className="multisensor-result-detail">
                <div className="multisensor-result-heading">
                  <div>
                    <h3>{selectedRecord.query}</h3>
                    <p>{result.evidence.scenes.map((scene) => formatDate(scene.datetime, locale)).join(', ')}</p>
                  </div>
                </div>

                {requestedLayer && (
                  <div className="display-map-canvas multisensor-raster-preview" aria-label={t('multisensor.rasterPreview')}>
                    {layerLoading ? <p role="status">{t('multisensor.layerLoading')}</p>
                      : availableLayer && imageKey && imageErrorKey !== imageKey ? (
                        <img className="raster-preview-image" src={getLayerUrl(selectedRecord.id, requestedLayer)} alt={t('multisensor.rasterAlt')} onError={() => setImageErrorKey(imageKey)} />
                      ) : <p>{t(layerError ?? 'multisensor.noRaster')}</p>}
                  </div>
                )}

                {activeTab === 'indices' && result.facts.stats && (
                  <>
                    <h4>{result.facts.index ?? t('multisensor.indexResult')}</h4>
                    <dl className="multisensor-metric-grid">
                      {Object.entries({
                        mean: result.facts.stats.mean,
                        median: result.facts.stats.median,
                        minimum: result.facts.stats.min,
                        maximum: result.facts.stats.max,
                        standardDeviation: result.facts.stats.std,
                        validPixelFraction: result.facts.stats.valid_fraction,
                      }).map(([key, value]) => (
                        <div key={key}><dt>{t(`multisensor.metric.${key}`)}</dt><dd>{typeof value === 'number' ? (key === 'validPixelFraction' ? `${(value * 100).toFixed(1)}%` : value.toFixed(4)) : '—'}</dd></div>
                      ))}
                    </dl>
                  </>
                )}

                {activeTab === 'change' && result.facts.change && (
                  <>
                    <h4>{t('multisensor.changeSummary')}</h4>
                    <dl className="multisensor-metric-grid">
                      {Object.entries({
                        baselineMean: result.facts.change.mean_a,
                        comparisonMean: result.facts.change.mean_b,
                        meanChange: result.facts.change.mean_change,
                        percentChange: result.facts.change.percent_change_of_mean,
                      }).map(([key, value]) => (
                        <div key={key}><dt>{t(`multisensor.metric.${key}`)}</dt><dd>{typeof value === 'number' ? value.toFixed(4) : '—'}</dd></div>
                      ))}
                    </dl>
                    <h4>{t('multisensor.changeClasses')}</h4>
                    <dl className="multisensor-metric-grid">
                      {Object.entries(result.facts.change.classes ?? {}).map(([name, metric]) => (
                        <div key={name}><dt>{name}</dt><dd>{metric.fraction_of_valid == null ? '—' : `${(metric.fraction_of_valid * 100).toFixed(1)}%`}</dd></div>
                      ))}
                    </dl>
                  </>
                )}

                {activeTab === 'trend' && result.facts.series && (
                  <>
                    {!result.facts.series.trend_claim_allowed && <p className="multisensor-data-note">{result.facts.series.message || t('multisensor.insufficientTrend')}</p>}
                    <p className="multisensor-data-note">{result.facts.series.caveat || t('multisensor.trendCaveat')}</p>
                    {result.facts.series.sens_slope_per_year != null && <p><strong>{t('multisensor.senSlope')}:</strong> {result.facts.series.sens_slope_per_year.toFixed(4)}</p>}
                    <div className="multisensor-series-table-wrap">
                      <table className="multisensor-series-table">
                        <thead><tr><th>{t('multisensor.acquisitionDate')}</th><th>{result.facts.index ?? 'NDVI'}</th></tr></thead>
                        <tbody>{result.facts.series.dates.map((date, index) => (
                          <tr key={`${date}-${index}`}><td>{formatDate(date, locale)}</td><td>{typeof result.facts.series?.values[index] === 'number' ? result.facts.series.values[index]?.toFixed(4) : '—'}</td></tr>
                        ))}</tbody>
                      </table>
                    </div>
                  </>
                )}

                {result.answer?.text && <p className="multisensor-answer">{result.answer.text}</p>}

                <details className="multisensor-evidence">
                  <summary>{t('multisensor.evidence')}</summary>
                  <p><strong>{t('multisensor.formula')}:</strong> {result.evidence.formula ?? '—'}</p>
                  <p><strong>{t('multisensor.bands')}:</strong> {Array.isArray(result.evidence.bands) ? result.evidence.bands.join(', ') : result.evidence.bands ?? '—'}</p>
                  <p><strong>{t('multisensor.aoiArea')}:</strong> {result.evidence.aoi_area_km2 == null ? '—' : `${result.evidence.aoi_area_km2.toFixed(2)} km²`}</p>
                  <ul>{result.evidence.scenes.map((scene) => (
                    <li key={`${scene.item_id}-${scene.datetime}`}>
                      {scene.item_id} · {formatDate(scene.datetime, locale)} · {scene.platform ?? scene.sensor ?? t('multisensor.identityUnknown')} · {t('multisensor.cloudCover')}: {scene.cloud_cover == null ? '—' : `${scene.cloud_cover.toFixed(1)}%`}
                    </li>
                  ))}</ul>
                  {result.evidence.preprocessing?.length > 0 && <p><strong>{t('multisensor.preprocessing')}:</strong> {result.evidence.preprocessing.join('; ')}</p>}
                  {result.model?.limitations?.length ? <p><strong>{t('multisensor.limitations')}:</strong> {result.model.limitations.join('; ')}</p> : null}
                </details>
              </div>
            ) : !recordLoading && !(historyLoading && recentAnalyses.length === 0) && !historyError && verificationCandidates.length === 0 && selectableRecords.length === 0 && !anyVerifiedOptical ? (
              <div className="multisensor-empty-state">
                <div className="multisensor-empty-mark" aria-hidden="true">S2</div>
                <h3>{t('multisensor.emptyTitle')}</h3>
                <p>{t('multisensor.emptyHelp')}</p>
                <button type="button" className="multisensor-open-map" onClick={onOpenMap}>{t('multisensor.openMapMode')}</button>
              </div>
            ) : !recordLoading && verificationCandidates.length === 0 && selectableRecords.length === 0 && anyVerifiedOptical ? (
              <p className="multisensor-select-prompt">{t('multisensor.noCategoryRecords')}</p>
            ) : !recordLoading && !selectedRecord && selectableRecords.length > 0 ? (
              <p className="multisensor-select-prompt">{t('multisensor.selectResultPrompt')}</p>
            ) : null}
          </section>
        </div>
      </section>

      <section className="multisensor-overview-card multisensor-sar-workspace" aria-labelledby="multisensor-sar-title">
        <div className="multisensor-overview-heading">
          <div>
            <h2 id="multisensor-sar-title">{t('multisensor.sarTitle')}</h2>
            <p>{t('multisensor.sarHelp')}</p>
          </div>
        </div>
        <p className="multisensor-data-note"><strong>Sentinel-1 radar:</strong> unlike Sentinel-2 optical imagery, radar measures returned microwave energy. VV is vertical transmit/vertical receive; VH is vertical transmit/horizontal receive. The scene-discovery API does not provide radar image previews, so these scenes are shown as metadata cards, not natural-color photographs.</p>
        <section className="multisensor-sar-aoi" aria-labelledby="multisensor-sar-aoi-title">
          <div>
            <h3 id="multisensor-sar-aoi-title">{t('multisensor.sarAoiTitle')}</h3>
            <p>{t('multisensor.sarAoiHelp')}</p>
          </div>
          <div className="multisensor-sar-aoi-actions">
            {currentAoi && <button type="button" className="filter-btn" onClick={() => selectSarAoi(currentAoi, 'current')}>{t('multisensor.sarUseCurrentAoi')}</button>}
            <label>{t('multisensor.sarSavedAoi')}
              <select value={savedAoiId} onChange={(event) => {
                const id = event.target.value
                setSavedAoiId(id)
                const saved = savedAois.find((item) => item.id === id)
                selectSarAoi(saved?.geometry ?? null, 'saved')
              }}>
                <option value="">{savedAois.length ? t('multisensor.sarChooseSavedAoi') : t('multisensor.sarNoSavedAois')}</option>
                {savedAois.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
            <button type="button" className="filter-btn" aria-expanded={showSarMap} aria-controls="multisensor-sar-map" onClick={() => setShowSarMap((open) => !open)}>
              {showSarMap ? t('multisensor.sarCloseMap') : t('multisensor.sarDefineMap')}
            </button>
          </div>
          {sarAoi && <p className="multisensor-sar-aoi-status" role="status">
            {t('multisensor.sarAoiReady')}{sarAoiSource ? ` · ${t(`multisensor.sarAoiSource.${sarAoiSource}`)}` : ''}
          </p>}
          {!sarAoi && <p className="multisensor-state" role="status">{t('multisensor.sarNeedsAoi')}</p>}
          {showSarMap && <div id="multisensor-sar-map" className="multisensor-sar-map-panel">
            <div className="multisensor-sar-map-heading">
              <div><h4>{t('multisensor.sarMapTitle')}</h4><p>{t('multisensor.sarMapHelp')}</p></div>
              <button type="button" className="filter-btn" onClick={() => setShowSarMap(false)}>{t('multisensor.sarCloseMap')}</button>
            </div>
            <MapWorkspace
              aoi={sarAoi}
              aoiA={null}
              aoiB={null}
              active={showSarMap}
              compareMode={false}
              drawTarget={sarDrawTarget}
              jobId={null}
              chrome="full"
              locationAoiActionLabel={t('multisensor.sarUseLocationAoi')}
              selectionExpanded
              layerInfo={null}
              visibleLayers={[]}
              opacity={0.72}
              setVisibleLayers={() => undefined}
              setOpacity={() => undefined}
              onDrawTarget={setSarDrawTarget}
              onAoiDrawn={handleSarMapAoiDrawn}
            />
          </div>}
        </section>
        <div className="multisensor-sar-controls">
          <label>{t('multisensor.sarStart')}<input type="date" value={sarStart} onChange={(event) => { setSarStart(event.target.value); clearSarDiscovery() }} /></label>
          <label>{t('multisensor.sarEnd')}<input type="date" value={sarEnd} onChange={(event) => { setSarEnd(event.target.value); clearSarDiscovery() }} /></label>
          <button type="button" className="filter-btn" onClick={() => void searchSarScenes()} disabled={!sarAoi || sarSearching}>
            {sarSearching ? t('multisensor.sarSearching') : t('multisensor.sarDiscover')}
          </button>
        </div>
        {sarSearching && <p role="status" className="multisensor-state">{t('multisensor.sarSearching')}</p>}
        {sarScenes.length > 0 && (
          <div className="multisensor-sar-scenes">
            {sarSearched && <p role="status" className="multisensor-sar-aoi-status">{t('multisensor.sarFoundScenes').replace('{count}', String(sarScenes.length))}</p>}
            <div className="multisensor-scene-gallery" role="group" aria-label="Available Sentinel-1 RTC scenes">
              {sarScenes.map((scene) => {
                const usable = scene.analysis_supported && scene.required_polarizations_available && scene.coverage_fraction >= 0.999
                const selected = scene.item_id === sarSceneId
                return (
                  <article className={`multisensor-scene-item ${selected ? 'scene-selected' : ''}`} key={scene.item_id}>
                    <button className="multisensor-scene-card" type="button" aria-pressed={selected} disabled={!usable} onClick={() => setSarSceneId(scene.item_id)}>
                      <span className="multisensor-radar-preview">
                        <strong>Sentinel-1 RTC · Radar</strong>
                        <span>Scene preview not provided</span>
                        <small>VV/VH backscatter data is not a natural-color image</small>
                      </span>
                      <span className="multisensor-scene-metadata">
                        <strong>{formatDate(scene.datetime, locale)}</strong>
                        <span>Platform: {scene.platform ?? 'Not available'}</span>
                        <span>AOI coverage: {scene.coverage_fraction == null ? 'Not available' : `${(scene.coverage_fraction * 100).toFixed(1)}%`}</span>
                        <span>Resolution: Not available</span>
                        <span>Processing level: {scene.processing_level ?? 'Not available'}</span>
                        <span>Orbit: {scene.orbit_state ?? 'Not available'} · Mode: {scene.instrument_mode ?? 'Not available'}</span>
                        <span>Polarizations: {scene.polarizations.length ? scene.polarizations.join(' / ') : 'Not available'}</span>
                        <small title={scene.item_id}>{scene.item_id}</small>
                        <span className="scene-gallery-selection">{selected ? 'Selected for analysis' : usable ? 'Select this scene' : t('multisensor.sarSceneUnavailable')}</span>
                      </span>
                    </button>
                    {selected && <button type="button" className="filter-btn" onClick={() => setSarSceneId('')}>Clear selection</button>}
                  </article>
                )
              })}
            </div>
            <button type="button" className="multisensor-open-map" onClick={() => void runSarAnalysis()} disabled={!sarSceneId || sarRunning}>
              {sarRunning ? t('multisensor.sarRunning') : t('multisensor.sarRun')}
            </button>
          </div>
        )}
        {!sarSearching && sarSearched && sarScenes.length === 0 && !sarError && <p className="multisensor-data-note">{t('multisensor.sarNoScenes')}</p>}
        {!sarSearching && sarScenes.length > 0 && !sarScenes.some((scene) => scene.analysis_supported && scene.required_polarizations_available && scene.coverage_fraction >= 0.999) && (
          <p className="multisensor-data-note">{t('multisensor.sarNoCompatibleScenes')}</p>
        )}
        {sarError && <p className="multisensor-inline-alert" role="alert">{sarError.startsWith('multisensor.') ? t(sarError) : sarError}</p>}

        {sarHistory.length > 0 && (
          <div className="multisensor-sar-history">
            <label htmlFor="multisensor-sar-history-select">{t('multisensor.sarSavedResults')}</label>
            <select id="multisensor-sar-history-select" value={sarSelectedHistoryId} onChange={(event) => { if (event.target.value) void selectSarHistory(event.target.value) }}>
              <option value="">{t('multisensor.sarChooseSaved')}</option>
              {sarHistory.map((item) => <option key={item.id} value={item.id} disabled={item.status !== 'completed'}>
                {item.query} · {formatDate(item.acquisition_dates?.[0] ?? item.created, locale)} · {t(`status.${item.status}`, item.status)}
              </option>)}
            </select>
          </div>
        )}

        {sarResult && (
          <div className="multisensor-result-detail">
            <h3>{t('multisensor.sarResultTitle')}</h3>
            <p className="multisensor-data-note">{t('multisensor.sarLinearGamma0')} · {sarResult.facts.measurement}</p>
            <p><strong>{t('multisensor.acquisitionDate')}:</strong> {formatDate(sarEvidenceScene?.datetime, locale)} · {sarEvidenceScene?.item_id ?? t('multisensor.unknown')}</p>
            <p><strong>Sensor:</strong> {sarEvidenceScene?.sensor ?? 'Not available'}</p>
            <p><strong>{t('multisensor.aoiArea')}:</strong> {sarResult.evidence.aoi_area_km2 == null ? 'Not available' : `${sarResult.evidence.aoi_area_km2.toFixed(3)} km²`}</p>
            <p><strong>{t('multisensor.sarAcquisition')}:</strong> {sarEvidenceScene?.platform ?? t('multisensor.identityUnknown')} · {sarEvidenceScene?.orbit_state ?? t('multisensor.unknown')} · {t('multisensor.sarRelativeOrbit')}: {sarEvidenceScene?.relative_orbit ?? '—'}</p>
            <p><strong>{t('multisensor.sarProvenance')}:</strong> {sarEvidenceScene?.provider ?? t('multisensor.unknown')} · {sarEvidenceScene?.collection ?? t('multisensor.unknown')} · {t('multisensor.sarProcessingLevel')}: {sarEvidenceScene?.processing_level ?? '—'}</p>
            <p><strong>{t('multisensor.sarGrid')}:</strong> {sarEvidenceScene?.crs ?? '—'} · {sarEvidenceScene?.resolution_m == null ? '—' : `${sarEvidenceScene.resolution_m} m`}</p>
            <p><strong>{t('multisensor.metric.validPixelFraction')}:</strong> {(sarResult.facts.valid_pixel_fraction * 100).toFixed(1)}% ({sarResult.facts.valid_pixel_count.toLocaleString(locale)})</p>
            <div className="multisensor-metric-grid">
              {(['vv', 'vh'] as const).map((band) => <div key={band}>
                <h4>{band.toUpperCase()} · {sarResult.facts.unit}</h4>
                <dl>
                  {Object.entries(sarResult.facts[band]).map(([key, value]) => <div key={key}><dt>{t(`multisensor.metric.${key}`, key)}</dt><dd>{value.toPrecision(5)}</dd></div>)}
                </dl>
              </div>)}
            </div>
            <details className="multisensor-evidence"><summary>{t('multisensor.evidence')}</summary>
              <p><strong>{t('multisensor.preprocessing')}:</strong> {sarResult.evidence.preprocessing.join('; ')}</p>
              <p><strong>{t('multisensor.limitations')}:</strong> {t('multisensor.sarLimitations')}</p>
            </details>
          </div>
        )}
      </section>

      <section className="multisensor-overview-card multisensor-sar-workspace" aria-labelledby="multisensor-fusion-title">
        <div className="multisensor-overview-heading"><div>
          <h2 id="multisensor-fusion-title">Optical + SAR Fusion</h2>
          <p>Use the same AOI above to find complete Sentinel-2 L2A and Sentinel-1 RTC pairs. Pairs must be within three days; they are not simultaneous.</p>
        </div></div>
        <div className="multisensor-sar-controls">
          <button type="button" className="filter-btn" onClick={() => void searchFusionPairs()} disabled={!sarAoi || fusionSearching}>
            {fusionSearching ? 'Finding compatible pairs…' : 'Discover compatible pairs'}
          </button>
        </div>
        {fusionPairs.length > 0 && <div className="multisensor-sar-scenes">
          <label>Compatible Sentinel-2 + Sentinel-1 acquisition pairs</label>
          <div className="fusion-pair-gallery" role="group" aria-label="Compatible optical and radar scene pairs">
            {fusionPairs.map((pair) => {
              const key = `${pair.optical.item_id}|${pair.sar.item_id}`
              const selected = key === fusionPairKey
              const opticalPreview = fusionOpticalPreviews[pair.optical.item_id]
              return (
                <button key={key} type="button" className={`fusion-pair-card ${selected ? 'scene-selected' : ''}`} aria-pressed={selected} onClick={() => setFusionPairKey(key)}>
                  <span className="fusion-pair-sensor-preview">
                    <strong>Sentinel-2 · Optical</strong>
                    {opticalPreview
                      ? <img src={opticalPreview} alt={`Provider optical preview for ${pair.optical.item_id}`} loading="lazy" referrerPolicy="no-referrer" />
                      : <span>Optical preview not available</span>}
                    <small>{pair.optical.item_id}</small>
                    <span>{formatDate(pair.optical.datetime, locale)}</span>
                    {pair.optical.cloud_cover != null && <span>Cloud cover: {pair.optical.cloud_cover.toFixed(1)}%</span>}
                    {pair.optical.coverage_fraction != null && <span>AOI coverage: {(pair.optical.coverage_fraction * 100).toFixed(1)}%</span>}
                  </span>
                  <span className="fusion-pair-separation">{pair.temporal_separation_hours.toFixed(1)} hours apart · {selected ? 'Selected pair' : 'Select this pair'}</span>
                  <span className="fusion-pair-sensor-preview fusion-pair-radar">
                    <strong>Sentinel-1 · RTC radar</strong>
                    <span>Radar image preview not supplied; no photograph is shown.</span>
                    <small>{pair.sar.item_id}</small>
                    <span>{formatDate(pair.sar.datetime, locale)}</span>
                    {pair.sar.coverage_fraction != null && <span>AOI coverage: {(pair.sar.coverage_fraction * 100).toFixed(1)}%</span>}
                    <span>Polarizations: {pair.sar.polarizations.length ? pair.sar.polarizations.join(' / ') : 'Not available'}</span>
                  </span>
                </button>
              )
            })}
          </div>
          <button type="button" className="multisensor-open-map" onClick={() => void runFusion()} disabled={!fusionPairKey || fusionRunning}>
            {fusionRunning ? 'Running fusion…' : 'Run fusion'}
          </button>
        </div>}
        {fusionError && <p className="multisensor-inline-alert" role="alert">{fusionError}</p>}
        {fusionResult && <div className="multisensor-result-detail">
          <h3>Fused feature stack</h3>
          <p className="multisensor-data-note">NDVI + VV/VH dB display bands + RVI. RVI is computed from linear RTC gamma0 before dB conversion.</p>
          <p><strong>Common grid:</strong> {fusionResult.common_crs} · {fusionResult.resolution_m} m</p>
          <p><strong>Valid overlap:</strong> {(fusionResult.overlap_fraction * 100).toFixed(1)}% ({fusionResult.valid_overlapping_pixel_count.toLocaleString(locale)} pixels)</p>
          <p><strong>Acquisition separation:</strong> {fusionResult.temporal_separation_hours.toFixed(1)} hours</p>
          <p><strong>Mean features:</strong> NDVI {fusionResult.mean_ndvi.toFixed(4)} · RVI {fusionResult.mean_rvi.toFixed(4)}</p>
          <details className="multisensor-evidence"><summary>Evidence and limitations</summary>
            <ul>{fusionResult.evidence.scenes.map((scene) => <li key={scene.item_id}>{scene.sensor} · {scene.item_id} · {formatDate(scene.datetime, locale)}</li>)}</ul>
            <p>{fusionResult.evidence.preprocessing.join('; ')}</p>
            <p>{fusionResult.limitations.join('; ')}</p>
          </details>
        </div>}
      </section>

      <section className="multisensor-overview-card multisensor-sar-workspace" aria-labelledby="multisensor-caption-title">
        <div className="multisensor-overview-heading"><div>
          <h2 id="multisensor-caption-title">{t('multisensor.capTitle')}</h2>
          <p>{t('multisensor.capHelp')}</p>
        </div></div>
        <div className="multisensor-sar-controls">
          <button type="button" className="filter-btn" onClick={() => void searchCaptionScenes()} disabled={!sarAoi || captionSearching}>
            {captionSearching ? t('multisensor.capSearching') : t('multisensor.capDiscover')}
          </button>
        </div>
        {captionSearching && <p role="status" className="multisensor-state">{t('multisensor.capSearching')}</p>}
        {captionScenes.length > 0 && (
          <div className="multisensor-sar-scenes">
            {captionSearched && <p role="status" className="multisensor-sar-aoi-status">{t('multisensor.capFoundScenes').replace('{count}', String(captionScenes.length))}</p>}
            <label htmlFor="multisensor-caption-scene">{t('multisensor.capSelectScene')}</label>
            <select id="multisensor-caption-scene" value={captionSceneId} onChange={(event) => setCaptionSceneId(event.target.value)}>
              <option value="">{t('multisensor.capChooseScene')}</option>
              {captionScenes.map((scene) => {
                const usable = scene.data_available !== false
                return <option key={scene.item_id} value={scene.item_id} disabled={!usable}>
                  {formatDate(scene.datetime, locale)} · {scene.item_id} · {t('multisensor.cloudCover')} {scene.cloud_cover == null ? '—' : `${scene.cloud_cover.toFixed(1)}%`}{usable ? '' : ` · ${t('multisensor.capSceneUnavailable')}`}
                </option>
              })}
            </select>
            <button type="button" className="multisensor-open-map" onClick={() => void runCaptionAnalysis()} disabled={!captionSceneId || captionRunning}>
              {captionRunning ? t('multisensor.capRunning') : t('multisensor.capRun')}
            </button>
          </div>
        )}
        {!captionSearching && captionSearched && captionScenes.length === 0 && !captionError && <p className="multisensor-data-note">{t('multisensor.capNoScenes')}</p>}
        {captionError && <p className="multisensor-inline-alert" role="alert">{captionError.startsWith('multisensor.') ? t(captionError) : captionError}</p>}
        {captionRunning && <p role="status" className="multisensor-state">{t('multisensor.capRunning')}</p>}

        {captionResult && (
          <div className="multisensor-result-detail">
            <h3>{t('multisensor.capResultTitle')}</h3>
            <p className="multisensor-caption-warning" role="note">{t('multisensor.capWarning')}</p>
            <p className="multisensor-answer">{captionResult.facts.caption}</p>
            <figure className="multisensor-caption-figure">
              {!captionImageFailed && captionJobId ? (
                <img src={getCaptionImageUrl(captionJobId)} alt={t('multisensor.capImageAlt')} onError={() => setCaptionImageFailed(true)} />
              ) : (
                <p className="multisensor-data-note">{t('multisensor.capImageUnavailable')}</p>
              )}
              <figcaption>{t('multisensor.capFigureCaption')}</figcaption>
            </figure>
            <p><strong>{t('multisensor.acquisitionDate')}:</strong> {formatDate(captionResult.facts.acquisition_datetime, locale)} · {captionResult.facts.source_scene_id}</p>
            <p><strong>{t('multisensor.capModel')}:</strong> {captionResult.facts.model_name} · {captionResult.facts.model_repository}@{captionResult.facts.model_revision}</p>
            <p><strong>{t('multisensor.metric.validPixelFraction')}:</strong> {(captionResult.facts.valid_pixel_fraction * 100).toFixed(1)}%</p>
            <p><strong>{t('multisensor.capRenderedSize')}:</strong> {captionResult.facts.rendered_width} × {captionResult.facts.rendered_height} px</p>
            <details className="multisensor-evidence"><summary>{t('multisensor.evidence')}</summary>
              <p><strong>{t('multisensor.bands')}:</strong> {captionResult.evidence.bands.join(', ')}</p>
              <p><strong>{t('multisensor.aoiArea')}:</strong> {captionResult.evidence.aoi_area_km2 == null ? '—' : `${captionResult.evidence.aoi_area_km2.toFixed(2)} km²`}</p>
              <ul>{captionResult.evidence.scenes.map((scene) => (
                <li key={`${scene.item_id}-${scene.datetime}`}>
                  {scene.item_id} · {formatDate(scene.datetime, locale)} · {t('multisensor.cloudCover')}: {scene.cloud_cover == null ? '—' : `${scene.cloud_cover.toFixed(1)}%`}
                </li>
              ))}</ul>
              <p><strong>{t('multisensor.preprocessing')}:</strong> {captionResult.evidence.preprocessing.join('; ')}</p>
              <p><strong>{t('multisensor.limitations')}:</strong> {captionResult.limitations.join('; ')}</p>
            </details>
          </div>
        )}
      </section>

      <section className="multisensor-capabilities" aria-labelledby="multisensor-capabilities-title">
        <h2 id="multisensor-capabilities-title">{t('multisensor.capabilities')}</h2>
        <ul>
          <li>{t('multisensor.capability.sar')}</li>
          <li>{t('multisensor.capability.fusion')}</li>
          <li>{t('multisensor.capability.vqa')}</li>
          <li>{t('multisensor.capability.captioning')}</li>
          <li>{t('multisensor.capability.grounding')}</li>
        </ul>
      </section>
      {(selectedRecord || selectableRecords.length > 0) && (
        <div className="multisensor-footer-actions">
          <button type="button" className="filter-btn" onClick={onOpenMap}>{t('multisensor.openMapMode')}</button>
        </div>
      )}
    </div>
  )
}
