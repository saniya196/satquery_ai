import { useEffect, useState } from 'react'
import {
  MetricCards,
  OperationChart,
  displayed,
  DataQualitySection,
  EvidencePanel,
  MethodologyPanel,
  ConfidencePanel,
  whatThisMeansLines,
} from './ResultsDashboard'
import { MapWorkspace } from './MapWorkspace'
import { getLayers } from '../api/client'
import type { AnalysisResult, CompareResponse, HistoryRecord, InvestigationResult, LayersResponse, PolygonGeometry } from '../types/analysis'

interface ResultsWorkspaceProps {
  record: HistoryRecord | null
  compare: CompareResponse | null
  aoiA: PolygonGeometry | null
  aoiB: PolygonGeometry | null
  investigationResult: InvestigationResult | null
  followUps: Array<{ question: string; result: InvestigationResult | null; error: string | null }>
  followUpLoading: boolean
  onSubmitFollowUp: (question: string, dateOverride?: { start: string; end: string } | null) => void
  onReturn: () => void
}

function resultForRecord(record: HistoryRecord | null): AnalysisResult | null {
  if (!record || !record.result) return null
  const r = record.result as AnalysisResult | { error: { code: string; message: string } }
  if ('error' in r) return null
  return r
}

function answerTextFor(result: AnalysisResult | null, investigation: InvestigationResult | null): string {
  if (investigation?.explanation?.text) return investigation.explanation.text
  if (result?.answer?.text) return result.answer.text
  return 'No grounded explanation was returned for this analysis.'
}

function comparisonAnswerText(compare: CompareResponse): string {
  const lines = [
    compare.aoi_a.result.answer?.text ? `Area A: ${compare.aoi_a.result.answer.text}` : null,
    compare.aoi_b.result.answer?.text ? `Area B: ${compare.aoi_b.result.answer.text}` : null,
  ].filter((line): line is string => line !== null)
  return lines.length ? lines.join('\n') : 'No grounded explanation was returned for this comparison.'
}

function answerSourceFor(result: AnalysisResult | null, investigation: InvestigationResult | null,
                         compare: CompareResponse | null): string {
  if (investigation?.explanation?.source) return investigation.explanation.source
  if (result?.answer?.source) return result.answer.source
  if (compare) {
    const sources = [compare.aoi_a.result.answer?.source, compare.aoi_b.result.answer?.source]
      .filter((source): source is string => Boolean(source))
    if (sources.length && sources.every((source) => source === sources[0])) return sources[0]
    if (sources.length) return 'mixed'
  }
  return 'system'
}

function ComparisonAreaMap({ label, aoi }: { label: string; aoi: PolygonGeometry | null }) {
  return (
    <section className="comparison-result-map-card" aria-label={`${label} map`}>
      <h4>{label}</h4>
      <div className="results-map">
        <MapWorkspace
          chrome="minimal"
          aoi={aoi}
          aoiA={null}
          aoiB={null}
          active={true}
          compareMode={false}
          drawTarget={null}
          jobId={null}
          layerInfo={null}
          visibleLayers={[]}
          opacity={0.72}
          setVisibleLayers={() => {}}
          setOpacity={() => {}}
          selectedHotspot={null}
          exploreMode={false}
          onDrawTarget={() => {}}
          onAoiDrawn={() => {}}
          onClearSelectedHotspot={() => {}}
        />
      </div>
    </section>
  )
}

export function ResultsWorkspace(props: ResultsWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<'summary' | 'evidence' | 'limitations'>('summary')
  const [layerInfo, setLayerInfo] = useState<LayersResponse | null>(null)
  const [visibleLayers, setVisibleLayers] = useState<string[]>([])
  const [opacity, setOpacity] = useState(0.72)
  const [followUpInput, setFollowUpInput] = useState('')
  const [followUpDateStart, setFollowUpDateStart] = useState('')
  const [followUpDateEnd, setFollowUpDateEnd] = useState('')

  const result = resultForRecord(props.record)
  const investigation = props.investigationResult
  const comparison = props.compare
  const comparisonQuery = comparison?.structured_query.raw_text
  const question = props.record?.query ??
    (typeof comparisonQuery === 'string' ? comparisonQuery : props.investigationResult?.question_understood ?? '')
  const answer = comparison ? comparisonAnswerText(comparison) : answerTextFor(result, investigation)
  const source = answerSourceFor(result, investigation, comparison)
  const answerIncludesQualityScore = /(?:data quality|quality) score/i.test(answer)
  const comparedScenes = comparison
    ? [...new Map(
      [...comparison.aoi_a.result.evidence.scenes, ...comparison.aoi_b.result.evidence.scenes]
      .map((scene): [string, typeof scene] => [scene.item_id, scene]),
    ).values()]
    : []

  useEffect(() => {
    if (!props.record?.id) {
      setLayerInfo(null)
      setVisibleLayers([])
      return
    }
    let cancelled = false
    getLayers(props.record.id).then((info) => {
      if (!cancelled) {
        setLayerInfo(info)
        setVisibleLayers(Object.keys(info.layers).slice(0, 1))
      }
    }).catch(() => {
      if (!cancelled) setLayerInfo(null)
    })
    return () => { cancelled = true }
  }, [props.record?.id])

  const hasResult = Boolean(result) || Boolean(comparison) || Boolean(investigation)

  const followUpDateOverride = followUpDateStart || followUpDateEnd
    ? { start: followUpDateStart || followUpDateEnd, end: followUpDateEnd || followUpDateStart }
    : null

  function handleFollowUpSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!followUpInput.trim()) return
    props.onSubmitFollowUp(followUpInput.trim(), followUpDateOverride)
    setFollowUpInput('')
    setFollowUpDateStart('')
    setFollowUpDateEnd('')
  }

  return (
    <div className="results-workspace" aria-label="Analysis results">
      <header className="results-header">
        <div className="results-header-bar">
          <button type="button" className="return-button" onClick={props.onReturn} title="Return to the selected area and ask another question">
            <span aria-hidden="true">←</span> Return to map
          </button>
          <div className="results-header-flex">
            <div>
              <span className="results-kicker">ANALYSIS RESULTS</span>
              <h1 className="results-title">{question || 'Untitled analysis'}</h1>
              <p className="results-meta">
                {result?.facts.operation ? result.facts.operation.replaceAll('_', ' ') : comparison ? 'Area comparison' : investigation ? 'Investigation' : ''}
                {props.record ? ` · Record ${props.record.id.slice(0, 8)}` : ''}
              </p>
            </div>
            <div className="results-answer-source">
              <span className={`answer-source answer-source-${source}`}>Explanation method: {source}</span>
            </div>
          </div>
        </div>

        <section className="results-answer-card" aria-labelledby="results-answer-title">
          <span className="results-answer-kicker">Grounded answer</span>
          <h2 id="results-answer-title">What the evidence shows</h2>
          <p className="results-answer-text">{answer}</p>
          <div className="results-answer-foot">
            <span>This answer is phrased only from values returned by the deterministic analysis pipeline.</span>
            {result && result.confidence.score !== null && !answerIncludesQualityScore && (
              <span>Data quality score: {displayed(result.confidence.score, 1)}/100 &mdash; a system score, not verified real-world accuracy.</span>
            )}
          </div>
        </section>
      </header>

      <section className="results-conversation" aria-label="Follow-up conversation">
        <div className="results-conversation-header">
          <h3>Follow-up questions</h3>
          <span>Ask another question about the same area without redrawing it.</span>
        </div>

        <form className="results-followup-form" onSubmit={handleFollowUpSubmit}>
          <label className="followup-label" htmlFor="followup-input">Ask a follow-up question</label>
          <div className="followup-input-row">
            <input
              id="followup-input"
              className="followup-input"
              value={followUpInput}
              onChange={(e) => setFollowUpInput(e.target.value)}
              placeholder="e.g., How has it changed compared with the previous observation?"
              disabled={props.followUpLoading}
            />
            <input
              className="followup-date"
              type="date"
              value={followUpDateStart}
              onChange={(e) => setFollowUpDateStart(e.target.value)}
              placeholder="From date"
              disabled={props.followUpLoading}
              aria-label="From date"
            />
            <input
              className="followup-date"
              type="date"
              value={followUpDateEnd}
              onChange={(e) => setFollowUpDateEnd(e.target.value)}
              placeholder="To date"
              disabled={props.followUpLoading}
              aria-label="To date"
            />
            <button
              type="submit"
              className="followup-submit"
              disabled={props.followUpLoading || !followUpInput.trim()}
            >
              {props.followUpLoading ? 'Analyzing…' : 'Ask'}
            </button>
          </div>
        </form>

        {props.followUps.length > 0 && (
          <div className="results-followup-list">
            {props.followUps.map((item, index) => (
              <div key={index} className="followup-card">
                <div className="followup-card-header">
                  <span className="followup-kicker">FOLLOW-UP #{index + 1}</span>
                  <span className={`followup-source followup-source-${(item.result?.explanation.source || 'system')}`}>
                    Explanation method: {item.result?.explanation.source || 'system'}
                  </span>
                </div>
                <p className="followup-question">{item.question}</p>
                {item.error && (
                  <p className="results-caveat" role="alert">{item.error}</p>
                )}
                {!item.error && item.result && (
                  <>
                    <p className="followup-answer">{item.result.explanation.text}</p>
                    {item.result.explanation.attempts != null && item.result.explanation.attempts > 0 && (
                      <span className="followup-attempts">Regenerated {item.result.explanation.attempts} time(s) for grounding.</span>
                    )}
                    {item.result.suggested_next_investigations && item.result.suggested_next_investigations.length > 0 && (
                      <ul className="followup-suggestions">
                        {item.result.suggested_next_investigations.map((s, i) => <li key={i}>{s}</li>)}
                      </ul>
                    )}
                    {item.result.data_quality_and_uncertainty?.limitations && item.result.data_quality_and_uncertainty.limitations.length > 0 && (
                      <div className="followup-limitations">
                        <strong>Limitations:</strong> {item.result.data_quality_and_uncertainty.limitations.join(' ')}
                      </div>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {hasResult ? (
        <div className="results-body">
          <section className="results-map-panel" aria-label="Analysis evidence map">
            <div className="results-map-header">
              <h3>{comparison ? 'Comparison areas' : 'Evidence map'}</h3>
              <span>{comparison
                ? `2 areas · ${comparedScenes.length} unique scene${comparedScenes.length === 1 ? '' : 's'}`
                : `${result?.evidence.scenes.length ?? 0} scene${result?.evidence.scenes.length === 1 ? '' : 's'}`}</span>
            </div>
            <div className={comparison ? 'comparison-result-maps' : 'results-map'} id={comparison ? undefined : 'results-map'}>
              {comparison ? (
                <>
                  <ComparisonAreaMap label="Area A" aoi={props.aoiA} />
                  <ComparisonAreaMap label="Area B" aoi={props.aoiB} />
                </>
              ) : (
                <MapWorkspace
                  chrome="minimal"
                  aoi={props.record?.aoi ?? null}
                  aoiA={null}
                  aoiB={null}
                  active={true}
                  compareMode={false}
                  drawTarget={null}
                  jobId={props.record?.id ?? null}
                  layerInfo={layerInfo}
                  layerError={null}
                  visibleLayers={visibleLayers}
                  opacity={opacity}
                  setVisibleLayers={setVisibleLayers}
                  setOpacity={setOpacity}
                  selectedHotspot={null}
                  exploreMode={false}
                  onDrawTarget={() => {}}
                  onAoiDrawn={() => {}}
                  onClearSelectedHotspot={() => {}}
                />
              )}
            </div>
            {comparison && <p className="results-caveat">The map shows both AOI outlines. This comparison response does not include raster visualization layers.</p>}
          </section>

          <section className="results-details-panel" aria-label="Measurements and evidence">
            <div className="results-tabs">
              <button type="button" className={`results-tab ${activeTab === 'summary' ? 'tab-active' : ''}`} onClick={() => setActiveTab('summary')}>
                Summary
              </button>
              <button type="button" className={`results-tab ${activeTab === 'evidence' ? 'tab-active' : ''}`} onClick={() => setActiveTab('evidence')}>
                Evidence &amp; data
              </button>
              <button type="button" className={`results-tab ${activeTab === 'limitations' ? 'tab-active' : ''}`} onClick={() => setActiveTab('limitations')}>
                Limitations
              </button>
            </div>

            {activeTab === 'summary' && (
              <>
                {result && (
                  <>
                    <MetricCards result={result} />
                    {result.facts.operation !== 'index_stats' && (
                      <div className="dashboard-section">
                        <div className="dashboard-section-heading">
                          <h3>{result.facts.operation === 'land_cover' ? 'Predicted land-cover distribution' : result.facts.operation === 'change_detection' ? 'Change-class distribution' : 'Trend over observations'}</h3>
                          <span>{result.facts.operation === 'land_cover' ? 'Share of classified area' : result.facts.operation === 'change_detection' ? 'Share of valid comparison pixels' : 'Index value by acquisition date'}</span>
                        </div>
                        <OperationChart result={result} />
                      </div>
                    )}
                    {result.facts.operation === 'land_cover' && (
                      <p className="results-caveat">Land-cover results are model predictions. The recorded EuroSAT test accuracy is a reported model/dataset metric, not an accuracy estimate for this AOI. Model confidence is not verified real-world accuracy.</p>
                    )}
                    {result.facts.operation === 'time_series' && !result.facts.series?.trend_claim_allowed && (
                      <p className="results-trend-guard">Not enough usable observation dates for a reliable trend test. No trend or significance claim is made.</p>
                    )}
                  </>
                )}
                {comparison && (
                  <div className="dashboard-section">
                    <div className="dashboard-section-heading"><h3>Area comparison</h3><span>Area B minus Area A</span></div>
                    <h4>Area A · {comparison.aoi_a.result.facts.date ?? 'date unavailable'}</h4>
                    <ul className="compare-summary-list">
                      <li>AOI: {displayed(comparison.aoi_a.result.evidence.aoi_area_km2, 3)} km² · usable pixels: {displayed(comparison.aoi_a.result.evidence.valid_pixel_fraction === null ? null : comparison.aoi_a.result.evidence.valid_pixel_fraction * 100, 1)}%</li>
                      {comparison.aoi_a.result.evidence.scenes.map((scene) => (
                        <li key={scene.item_id}>{scene.item_id} · {scene.datetime.slice(0, 10)} · cloud {scene.cloud_cover === null ? 'unknown' : `${displayed(scene.cloud_cover, 1)}%`} · footprint coverage {scene.coverage_fraction == null ? 'unknown' : `${displayed(scene.coverage_fraction * 100, 1)}%`}</li>
                      ))}
                    </ul>
                    <MetricCards result={comparison.aoi_a.result} />
                    <h4>Area B · {comparison.aoi_b.result.facts.date ?? 'date unavailable'}</h4>
                    <ul className="compare-summary-list">
                      <li>AOI: {displayed(comparison.aoi_b.result.evidence.aoi_area_km2, 3)} km² · usable pixels: {displayed(comparison.aoi_b.result.evidence.valid_pixel_fraction === null ? null : comparison.aoi_b.result.evidence.valid_pixel_fraction * 100, 1)}%</li>
                      {comparison.aoi_b.result.evidence.scenes.map((scene) => (
                        <li key={scene.item_id}>{scene.item_id} · {scene.datetime.slice(0, 10)} · cloud {scene.cloud_cover === null ? 'unknown' : `${displayed(scene.cloud_cover, 1)}%`} · footprint coverage {scene.coverage_fraction == null ? 'unknown' : `${displayed(scene.coverage_fraction * 100, 1)}%`}</li>
                      ))}
                    </ul>
                    <MetricCards result={comparison.aoi_b.result} />
                    {comparison.aoi_a.result.facts.operation === 'index_stats' && (
                      <>
                        <h4>Differences · {String(comparison.aoi_a.result.facts.index ?? 'Index')} · Area B minus Area A</h4>
                        <div className="metrics-grid">
                          {([
                            ['Mean', 'stats.mean'],
                            ['Median', 'stats.median'],
                            ['Minimum', 'stats.min'],
                            ['Maximum', 'stats.max'],
                          ] as const).map(([label, key]) => (
                            <div className="metric-card" key={key}>
                              <span>{label} difference</span>
                              <strong>{displayed(comparison.differences[key])}</strong>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}
                {investigation && (
                  <div className="dashboard-section">
                    <div className="dashboard-section-heading"><h3>Investigation</h3><span>Interpretation only</span></div>
                    <p>{investigation.question_understood}</p>
                    <p>{investigation.plan.notes.join(' ') || 'The request was classified against the available satellite tools.'}</p>
                  </div>
                )}
              </>
            )}

            {activeTab === 'evidence' && result && (
              <>
                <DataQualitySection result={result} />
                <EvidencePanel result={result} />
                <MethodologyPanel result={result} />
              </>
            )}
            {activeTab === 'evidence' && comparison && (
              <>
                <h3>Area A evidence</h3>
                <DataQualitySection result={comparison.aoi_a.result} />
                <EvidencePanel result={comparison.aoi_a.result} />
                <MethodologyPanel result={comparison.aoi_a.result} />
                <h3>Area B evidence</h3>
                <DataQualitySection result={comparison.aoi_b.result} />
                <EvidencePanel result={comparison.aoi_b.result} />
                <MethodologyPanel result={comparison.aoi_b.result} />
              </>
            )}

            {activeTab === 'limitations' && (
              <div className="dashboard-section">
                <div className="dashboard-section-heading"><h3>Limitations &amp; uncertainty</h3><span>Read before drawing conclusions</span></div>
                {result && <ConfidencePanel result={result} />}
                {comparison && (
                  <>
                    <h4>Area A data quality</h4>
                    <ConfidencePanel result={comparison.aoi_a.result} />
                    <ul className="results-limitation-list">
                      {whatThisMeansLines(comparison.aoi_a.result).lines.map((line, i) => <li key={`a-${i}`}>{line}</li>)}
                    </ul>
                    <h4>Area B data quality</h4>
                    <ConfidencePanel result={comparison.aoi_b.result} />
                    <ul className="results-limitation-list">
                      {whatThisMeansLines(comparison.aoi_b.result).lines.map((line, i) => <li key={`b-${i}`}>{line}</li>)}
                    </ul>
                  </>
                )}
                {result && (
                  <ul className="results-limitation-list">
                    {whatThisMeansLines(result).lines.map((line, i) => <li key={i}>{line}</li>)}
                  </ul>
                )}
                {result?.evidence.coverage?.status === 'partial' && (
                  <p className="results-caveat">Image coverage was partial for the selected area, so measurements may represent only the covered portion.</p>
                )}
                <p className="results-caveat">Confidence reflects data/analysis factors returned by the system, not verified real-world accuracy.</p>
              </div>
            )}
          </section>
        </div>
      ) : (
        <div className="results-empty">
          <p>No analysis result is available to display.</p>
          <button type="button" className="return-button" onClick={props.onReturn}>Return to map</button>
        </div>
      )}

      <footer className="results-footer">
        <button type="button" className="return-button" onClick={props.onReturn}>
          <span aria-hidden="true">←</span> Return to the selected area and ask another question
        </button>
      </footer>
    </div>
  )
}
