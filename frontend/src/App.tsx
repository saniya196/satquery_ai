import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  compareAnalysis,
  deleteHistoryRecord,
  downloadExport,
  friendlyApiError,
  getHistory,
  getHistoryRecord,
  getJob,
  startAnalysis,
} from './api/client'
import { HistorySidebar } from './components/HistorySidebar'
import { MapWorkspace, type DrawTarget } from './components/MapWorkspace'
import { ResultsDashboard } from './components/ResultsDashboard'
import { JobStatusCard } from './components/JobStatusCard'
import { Sidebar, type NavView } from './components/layout/Sidebar'
import { AppHeader } from './components/layout/AppHeader'
import { HomeView } from './views/HomeView'
import { UploadView } from './views/UploadView'
import { HistoryView } from './views/HistoryView'
import { BenchmarksView } from './views/BenchmarksView'
import { SettingsView } from './views/SettingsView'
import { MultiSensorView } from './views/MultiSensorView'
import { ChangeHotspotsView } from './views/ChangeHotspotsView'
import type { CompareResponse, HistoryRecord, HistorySummary, JobResponse, PolygonGeometry } from './types/analysis'
import './App.css'

const examples = [
  'Did vegetation health decrease between June and September?',
  'Show the vegetation trend over the last year',
  'Show land cover for June',
  'What percentage of the area is water in June?',
]
const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

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
  const [drawTarget, setDrawTarget] = useState<DrawTarget | null>(null)
  const [compareResult, setCompareResult] = useState<CompareResponse | null>(null)
  const [clarification, setClarification] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [requestErrorDetails, setRequestErrorDetails] = useState<{ code: string; raw: string } | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [exporting, setExporting] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const [compareMonthA, setCompareMonthA] = useState('June')
  const [compareMonthB, setCompareMonthB] = useState('September')
  const [panelCollapsed, setPanelCollapsed] = useState(false)

  // Mirrors of the latest query and AOI so the job poller can read them without
  // being torn down and restarted on every keystroke or redraw.
  const queryRef = useRef(query)
  const aoiRef = useRef(aoi)

  function showRequestError(error: unknown) {
    const friendly = friendlyApiError(error)
    setRequestError(`${friendly.message} ${friendly.suggestion}`)
    setRequestErrorDetails(friendly.code ? {
      code: friendly.code,
      raw: error instanceof ApiError ? error.rawMessage : error instanceof Error ? error.message : 'Unknown error',
    } : null)
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

  useEffect(() => {
    queryRef.current = query
    aoiRef.current = aoi
  }, [query, aoi])

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
    if (geometry.coordinates.length === 0) {
      if (target === 'main') setAoi(null)
      if (target === 'compare-a') setAoiA(null)
      if (target === 'compare-b') setAoiB(null)
      setActiveRecord(null)
      setActiveJobId(null)
      setJob(null)
      setCompareResult(null)
      return
    }
    if (target === 'main') setAoi(geometry)
    if (target === 'compare-a') setAoiA(geometry)
    if (target === 'compare-b') setAoiB(geometry)
    setActiveRecord(null)
    setActiveJobId(null)
    setJob(null)
    setCompareResult(null)
  }

  function selectImageDate(date: string) {
    setQueryStart(date)
    setQueryEnd(date)
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setClarification(null)
    setRequestError(null)
    setRequestErrorDetails(null)
    setCompareResult(null)
    if (!query.trim()) {
      setRequestError('Enter an analysis question.')
      return
    }
    const dateClause = queryStart && queryEnd
      ? queryStart === queryEnd ? ` on ${queryStart}` : ` between ${queryStart} and ${queryEnd}`
      : queryStart ? ` on ${queryStart}` : ''
    const submittedQuery = `${query.trim()}${dateClause}`
    if (compareMode) {
      if (!aoiA || !aoiB) {
        setRequestError('Draw both Area A and Area B on the map before comparing.')
        return
      }
      setSubmitting(true)
      try {
        setCompareResult(await compareAnalysis(submittedQuery, aoiA, aoiB))
        setActiveRecord(null)
        setJob(null)
      } catch (error) {
        showRequestError(error)
      } finally {
        setSubmitting(false)
      }
      return
    }
    if (!aoi) {
      setRequestError('Draw or upload an area of interest on the map first.')
      return
    }

    setSubmitting(true)
    setActiveRecord(null)
    setJob(null)
    setActiveJobId(null)
    try {
      const response = await startAnalysis(submittedQuery, aoi)
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

  async function openHistory(id: string) {
    setRequestError(null)
    setClarification(null)
    setCompareResult(null)
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
      setExportError(error instanceof Error ? error.message : 'Export failed.')
    } finally {
      setExporting(null)
    }
  }

  const selectedId = activeRecord?.id ?? job?.job_id ?? null
  const recordResult = activeRecord?.result
  const failedError = recordResult && 'error' in recordResult ? recordResult.error : job?.error
  const failedFriendly = failedError ? friendlyApiError(new ApiError(failedError.code, failedError.message)) : null
  const jobBusy = submitting || Boolean(activeJobId)

  function applyCompareMonths() {
    setQuery(`Did vegetation health decrease between ${compareMonthA} and ${compareMonthB}?`)
    setQueryStart('')
    setQueryEnd('')
  }

  return (
    <div className="satquery-app-container">
      <Sidebar
        currentView={currentView}
        onSelectView={setCurrentView}
        activeJobCount={activeJobId ? 1 : 0}
      />

      <div className="app-main-content-layout">
        <AppHeader
          currentView={currentView}
          activeJobId={activeJobId}
          jobStatus={job?.status}
        />

        <div className="app-view-body">
          {currentView === 'home' && (
            <HomeView
              onNavigate={setCurrentView}
              recentQueries={historyItems}
              onOpenQuery={(id) => {
                void openHistory(id)
                setCurrentView('map')
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
                setCurrentView('map')
              }}
              onDelete={(id) => void removeHistory(id)}
              onRefresh={() => void refreshHistory()}
            />
          )}

          {currentView === 'multisensor' && <MultiSensorView record={activeRecord} />}

          {currentView === 'change' && <ChangeHotspotsView record={activeRecord} />}

          {currentView === 'benchmarks' && <BenchmarksView />}

          {currentView === 'settings' && <SettingsView />}

          {/* Map workspace is kept mounted to preserve Leaflet map canvas and vector layers */}
          <div style={{ display: currentView === 'map' ? 'block' : 'none', height: '100%' }}>
            <main className={`workspace ${panelCollapsed ? 'workspace-panel-collapsed' : ''}`} id="workspace">
              <HistorySidebar
                items={historyItems}
                activeId={selectedId}
                loading={historyLoading}
                error={historyError}
                onSelect={(id) => void openHistory(id)}
                onDelete={(id) => void removeHistory(id)}
                onRefresh={() => void refreshHistory()}
              />
              <MapWorkspace
                aoi={aoi}
                aoiA={aoiA}
                aoiB={aoiB}
                compareMode={compareMode}
                drawTarget={drawTarget}
                jobId={activeRecord?.status === 'completed' ? activeRecord.id : null}
                onDrawTarget={setDrawTarget}
                onAoiDrawn={setArea}
                onImageDateSelected={selectImageDate}
              />
              <aside className="analysis-panel" aria-label="Analysis request and results">
                <button
                  className="panel-toggle"
                  type="button"
                  title={panelCollapsed ? 'Show results panel' : 'Hide results panel'}
                  aria-label={panelCollapsed ? 'Show results panel' : 'Hide results panel'}
                  onClick={() => setPanelCollapsed((value) => !value)}
                >
                  {panelCollapsed ? '‹' : '›'}
                </button>
                <div className="panel-scroll">
                  <div className="request-header">
                    <div><span className="section-kicker">QUERY CONSOLE</span><h1>Read the landscape.</h1></div>
                    <button
                      className={`compare-mode-button ${compareMode ? 'compare-mode-active' : ''}`}
                      type="button"
                      onClick={() => {
                        setCompareMode((current) => !current)
                        setCompareResult(null)
                        setRequestError(null)
                        setActiveRecord(null)
                        setJob(null)
                      }}
                    >
                      {compareMode ? 'Exit compare' : 'Compare areas'}
                    </button>
                  </div>
                  <p className="panel-intro">{compareMode ? 'Draw two areas, then run the same analysis over each.' : 'Choose an area on the map, then ask what is changing on the ground.'}</p>
                  {compareMode && <div className="compare-area-status"><span className={aoiA ? 'area-ready' : ''}>A {aoiA ? 'ready' : 'not drawn'}</span><span className={aoiB ? 'area-ready' : ''}>B {aoiB ? 'ready' : 'not drawn'}</span></div>}
                  {compareMode && (
                    <div className="month-helper">
                      <span className="field-label">Compare two months</span>
                      <label><span>From</span><select value={compareMonthA} onChange={(event) => setCompareMonthA(event.target.value)}>{monthNames.map((month) => <option key={month}>{month}</option>)}</select></label>
                      <label><span>To</span><select value={compareMonthB} onChange={(event) => setCompareMonthB(event.target.value)}>{monthNames.map((month) => <option key={month}>{month}</option>)}</select></label>
                      <button type="button" title="Fill the question with the selected months" onClick={applyCompareMonths}>Use months</button>
                    </div>
                  )}
                  <form className="query-form" onSubmit={handleSubmit}>
                    <label className="field-label" htmlFor="question">Analysis question</label>
                    <textarea id="question" rows={4} maxLength={500} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. Did vegetation health decrease between June and September?" />
                    <div className="query-date-fields">
                      <label>From<input aria-label="Question start date" type="date" value={queryStart} max={queryEnd || undefined} onChange={(event) => setQueryStart(event.target.value)} /></label>
                      <label>To<input aria-label="Question end date" type="date" value={queryEnd} min={queryStart || undefined} onChange={(event) => setQueryEnd(event.target.value)} /></label>
                    </div>
                    <div className="query-meta"><span>Natural language</span><span>{query.length}/500</span></div>
                    <button className="run-button" type="submit" disabled={jobBusy}>
                      <span>{jobBusy ? (job?.status === 'processing' ? 'Processing analysis…' : job?.status === 'queued' ? 'Analysis queued…' : compareMode ? 'Comparing areas…' : 'Starting analysis…') : (compareMode ? 'Compare areas' : 'Run analysis')}</span>
                      {jobBusy ? <span className="map-spinner run-spinner" aria-hidden="true" /> : <span className="run-arrow" aria-hidden="true">↗</span>}
                    </button>
                  </form>
                  {(clarification || requestError) && (
                    <div className={`inline-message ${requestError ? 'inline-message-error' : ''}`} role="status">
                      <span>{requestError ?? clarification}</span>
                      {requestErrorDetails && <details><summary>Error details</summary><code>{requestErrorDetails.code}: {requestErrorDetails.raw}</code></details>}
                    </div>
                  )}
                  <div className="example-block">
                    <span className="field-label">Try an example</span>
                    <div className="example-list">{examples.map((example) => <button className="example-question" type="button" key={example} onClick={() => setQuery(example)}><span aria-hidden="true">↳</span>{example}</button>)}</div>
                  </div>
                  {job && <JobStatusCard job={job} activeJobId={activeJobId} />}
                  {failedFriendly && (
                    <div className="failure-message" role="alert">
                      <strong>{failedFriendly.message}</strong>
                      <p>{failedFriendly.suggestion}</p>
                      <details><summary>Error details</summary><code>{failedError?.code}: {failedError?.message}</code></details>
                    </div>
                  )}
                  <ResultsDashboard record={activeRecord} compare={compareResult} busyExport={exporting} exportError={exportError} onExport={handleExport} />
                </div>
                {!panelCollapsed && <footer className="panel-footer"><span className="footer-mark" aria-hidden="true">●</span><span>Evidence-backed satellite analysis</span></footer>}
              </aside>
            </main>
          </div>
        </div>
      </div>
    </div>
  )
}
