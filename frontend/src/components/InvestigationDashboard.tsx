import type {
  InvestigationEvidenceCheck,
  InvestigationResult,
  InvestigationToolExecution,
} from '../types/analysis'

interface InvestigationDashboardProps {
  result: InvestigationResult | null
}

function display(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'n/a'
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : 'n/a'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

function percentage(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a'
  return `${(value * 100).toFixed(1)}%`
}

function toolSummary(execution: InvestigationToolExecution): string {
  const facts = execution.actual_result?.facts
  if (!facts || typeof facts !== 'object') return execution.error?.message ?? 'No structured output returned.'
  const record = facts as Record<string, unknown>
  const change = record.change as Record<string, unknown> | undefined
  const stats = record.stats as Record<string, unknown> | undefined
  const series = record.series as Record<string, unknown> | undefined
  if (change) return `Mean change: ${display(change.mean_change)}; before: ${display(change.mean_a)}; after: ${display(change.mean_b)}.`
  if (stats) return `Mean: ${display(stats.mean)}; median: ${display(stats.median)}; valid pixels: ${percentage(stats.valid_fraction)}.`
  if (series) return `Usable dates: ${display(series.n_dates_usable ?? series.n)}; trend claim allowed: ${display(series.trend_claim_allowed)}.`
  return `Operation: ${display(record.operation)}.`
}

function EvidenceChecks({ checks }: { checks: InvestigationEvidenceCheck[] }) {
  if (checks.length === 0) return <p className="query-meta-help">No evidence checks were returned.</p>
  return (
    <ul className="investigation-check-list">
      {checks.map((check) => (
        <li key={`${check.check}-${check.detail}`} className={check.passed ? 'investigation-check-passed' : 'investigation-check-failed'}>
          <strong>{check.passed ? 'PASS' : 'CHECK'}</strong> {check.check}: {check.detail}
        </li>
      ))}
    </ul>
  )
}

export function InvestigationDashboard({ result }: InvestigationDashboardProps) {
  if (!result) return null
  const limitations = result.data_quality_and_uncertainty.limitations ?? []
  const checks = result.data_quality_and_uncertainty.checks ?? []

  return (
    <section className="investigation-dashboard" aria-label="Satellite investigation result">
      <div className="investigation-heading">
        <div>
          <span className="section-kicker">INTELLIGENT INVESTIGATION</span>
          <h2>Investigation result</h2>
        </div>
        <span className={`investigation-status investigation-status-${result.status}`}>{result.status.replace('_', ' ')}</span>
      </div>

      <div className="dashboard-section">
        <div className="dashboard-section-heading"><h3>Question understood</h3><span>Interpretation only</span></div>
        <p>{result.question_understood}</p>
      </div>

      <div className="dashboard-section">
        <div className="dashboard-section-heading"><h3>Investigation plan</h3><span>{result.plan.can_execute ? 'Executable plan' : 'Needs input'}</span></div>
        <p>{result.plan.notes.join(' ') || 'The request was classified against the available satellite tools.'}</p>
        <ul className="investigation-plan-list">
          {result.plan.selected_tools.map((tool) => (
            <li key={`${tool.tool}-${tool.purpose}`}>
              <strong>{tool.tool}</strong>
              <span>{tool.purpose}</span>
              <small>{tool.reason}</small>
            </li>
          ))}
        </ul>
        {result.plan.missing_required_inputs.length > 0 && (
          <p className="inline-message inline-message-error">Required input: {result.plan.missing_required_inputs.join('; ')}</p>
        )}
      </div>

      <div className="dashboard-section">
        <div className="dashboard-section-heading"><h3>Execution history</h3><span>Synchronous request; not live progress</span></div>
        <ol className="investigation-trace-list">
          {result.trace.map((event) => (
            <li key={event.id} className={`investigation-trace-${event.status}`}>
              <div><strong>{event.label}</strong><span>{event.status}</span></div>
              {event.detail && <small>{event.detail}</small>}
              {event.error && <small className="investigation-error">{event.error.code}: {event.error.message}</small>}
            </li>
          ))}
        </ol>
      </div>

      <div className="dashboard-section">
        <div className="dashboard-section-heading"><h3>Actual findings</h3><span>Returned by deterministic tools</span></div>
        {result.tools_executed.length === 0
          ? <p className="query-meta-help">No satellite tool was executed.</p>
          : <ul className="investigation-findings-list">{result.tools_executed.map((execution) => (
            <li key={execution.tool}>
              <strong>{execution.tool}</strong>
              <span className={`investigation-tool-status investigation-tool-${execution.status}`}>{execution.status}</span>
              <p>{toolSummary(execution)}</p>
            </li>
          ))}</ul>}
      </div>

      <div className="dashboard-section">
        <div className="dashboard-section-heading"><h3>Supporting satellite evidence</h3><span>{result.supporting_evidence.length} evidence record(s)</span></div>
        {result.supporting_evidence.length === 0
          ? <p className="query-meta-help">No evidence record was returned.</p>
          : <div className="investigation-evidence-list">{result.supporting_evidence.map((evidence, index) => {
            const scenes = Array.isArray(evidence.scenes) ? evidence.scenes : []
            return (
              <article key={`${String(evidence.tool)}-${index}`} className="investigation-evidence-item">
                <strong>{display(evidence.tool)} · {display(evidence.index)} · {display(evidence.operation)}</strong>
                <span>Valid pixels: {percentage(evidence.valid_pixel_fraction)} · AOI: {display(evidence.aoi_area_km2)} km²</span>
                <small>Scenes: {scenes.map((scene) => typeof scene === 'object' && scene !== null ? display((scene as Record<string, unknown>).item_id) : display(scene)).join(', ') || 'n/a'}</small>
              </article>
            )
          })}</div>}
      </div>

      <div className="dashboard-section">
        <div className="dashboard-section-heading"><h3>Evidence validation and limitations</h3><span>Deterministic checks</span></div>
        <EvidenceChecks checks={checks} />
        {limitations.length > 0 && <ul className="investigation-limitations">{limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>}
        {result.unsupported_conclusions.length > 0 && (
          <p className="inline-message inline-message-error">Unsupported conclusions: {result.unsupported_conclusions.join(' ')}</p>
        )}
      </div>

      <div className="dashboard-section investigation-explanation">
        <div className="dashboard-section-heading"><h3>Grounded explanation</h3><span>{result.explanation.source ?? 'unknown'} · {result.explanation.validated ? 'validated' : 'not validated'}</span></div>
        <p>{result.explanation.text}</p>
      </div>

      {result.suggested_next_investigations.length > 0 && (
        <div className="dashboard-section">
          <div className="dashboard-section-heading"><h3>Suggested next investigations</h3><span>Supported follow-ups</span></div>
          <ul className="investigation-limitations">{result.suggested_next_investigations.map((suggestion) => <li key={suggestion}>{suggestion}</li>)}</ul>
        </div>
      )}
    </section>
  )
}
