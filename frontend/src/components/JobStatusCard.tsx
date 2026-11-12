import React from 'react'
import type { JobResponse } from '../types/analysis'

interface JobStatusCardProps {
  job: JobResponse | null
  activeJobId: string | null
}

export const JobStatusCard: React.FC<JobStatusCardProps> = ({ job, activeJobId }) => {
  if (!job && !activeJobId) return null

  const displayJobId = job?.job_id || activeJobId || ''
  const status = job?.status || 'queued'

  // No fallback stages or provider metadata: the backend reports these only when it
  // actually measured or observed them, so the card must never invent values.
  const stages = job?.stages ?? []
  const provider = job?.provider_info
  // A failed job never reports a stage, so the stepper would otherwise leave a
  // spinner running on a run that already stopped. App.tsx surfaces the error.
  const showStepper = status !== 'failed' && stages.length > 0

  const statusLabel =
    status === 'completed' ? 'Completed'
      : status === 'failed' ? 'Failed'
        : status === 'queued' ? 'Queued'
          : 'Processing'
  const statusTone = status === 'completed' ? 'valid' : status === 'failed' ? 'invalid' : 'processing'

  return (
    <div className="job-status-panel-card">
      <div className="job-status-card-header">
        <div className="job-id-line">
          <span className="card-kicker">Job Status</span>
          <h3>Job ID: <span className="job-id-mono">{displayJobId.slice(0, 16)}</span></h3>
        </div>
        <span className={`status-pill status-${statusTone}`}>
          {statusLabel}
        </span>
      </div>

      {showStepper && (
        <div className="job-stepper-list">
          {stages.map((stage, idx) => {
            const isDone = stage.status === 'completed'
            const isCurrent = stage.status === 'processing'
            return (
              <div key={`${stage.name}-${idx}`} className={`job-step-row ${isDone ? 'step-done' : isCurrent ? 'step-current' : 'step-pending'}`}>
                <div className="step-icon-col">
                  {isDone ? (
                    <span className="step-check-icon">✓</span>
                  ) : isCurrent ? (
                    <span className="step-spinner-icon" />
                  ) : (
                    <span className="step-pending-icon">○</span>
                  )}
                </div>
                <div className="step-name-col">
                  <span className="step-name">{stage.name}</span>
                </div>
                {stage.duration && (
                  <div className="step-duration-col">
                    <span className="step-duration">✓ {stage.duration}</span>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      <div className="data-provider-section">
        <span className="section-small-title">Data Provider</span>
        <div className="provider-meta-row">
          <div className="provider-satellite-badge">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="sat-icon">
              <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z" />
              <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z" />
              <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0" />
              <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5" />
            </svg>
            <strong>{provider?.name || 'Sentinel-2'}</strong>
          </div>
          <div className="provider-details-chips">
            {provider?.tile && (
              <span className="provider-chip">Tile: <strong>{provider.tile}</strong></span>
            )}
            {provider?.date && (
              <span className="provider-chip">Date: <strong>{provider.date}</strong></span>
            )}
            {provider?.coverage && (
              <span className="provider-chip" title={provider.coverage.note || 'Scene footprint coverage of AOI'}>
                Coverage: <strong>{provider.coverage.status === 'full' ? 'Full' : provider.coverage.status === 'partial' ? 'Partial' : 'Unknown'}{typeof provider.coverage.fraction === 'number' && Number.isFinite(provider.coverage.fraction) ? ` (${(provider.coverage.fraction * 100).toFixed(1)}%)` : ''}</strong>
              </span>
            )}
          </div>
        </div>
        {provider?.coverage?.status === 'partial' && (
          <p className="coverage-note">Partial scene coverage: statistics may represent only the covered portion of the AOI.</p>
        )}
        {status === 'failed' && provider?.coverage?.status === 'partial' && (
          <p className="coverage-note">Analysis failed due to insufficient scene coverage (multiple tiles may be required).</p>
        )}
      </div>
    </div>
  )
}
