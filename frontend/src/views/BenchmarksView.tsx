import React, { useEffect, useState } from 'react'
import { getLandCoverEvaluation, type LandCoverEvaluationReport } from '../api/client'
import { useLanguage } from '../i18n'

type BenchmarkTab = 'eurosat' | 'vrsbench' | 'rsvqa' | 'cdvqa' | 'isrosac'
type ExternalBenchmarkTab = Exclude<BenchmarkTab, 'eurosat'>

interface BenchmarkDatasetInfo {
  id: BenchmarkTab
  title: string
  subtitle: string
  metrics: { metric: string; score: string; description: string }[]
  notes: string
}

const BENCHMARK_DATA: Record<ExternalBenchmarkTab, BenchmarkDatasetInfo> = {
  vrsbench: {
    id: 'vrsbench',
    title: 'VRSBench',
    subtitle: 'Visual Question Answering & Captioning for Remote Sensing',
    metrics: [
      { metric: 'Evaluation status', score: 'Not evaluated', description: 'No reproducible SatQuery VRSBench evaluation artifact is present.' },
    ],
    notes: 'Published model results are not SatQuery results. SatQuery has not run or verified this benchmark here.',
  },
  rsvqa: {
    id: 'rsvqa',
    title: 'RSVQA',
    subtitle: 'High-Resolution Remote Sensing Visual Question Answering',
    metrics: [
      { metric: 'Evaluation status', score: 'Not evaluated', description: 'No reproducible SatQuery RSVQA evaluation artifact is present.' },
    ],
    notes: 'RSVQA data and evaluation outputs are not present in this repository.',
  },
  cdvqa: {
    id: 'cdvqa',
    title: 'CDVQA',
    subtitle: 'Change Detection Visual Question Answering on Image Pairs',
    metrics: [
      { metric: 'Evaluation status', score: 'Not evaluated', description: 'No reproducible SatQuery CDVQA evaluation artifact is present.' },
    ],
    notes: 'The existing change engine is tested on synthetic/fake-provider data, not CDVQA.',
  },
  isrosac: {
    id: 'isrosac',
    title: 'ISRO / SAC',
    subtitle: 'Indian Space Research Organisation / Space Applications Centre Datasets',
    metrics: [
      { metric: 'Evaluation status', score: 'Not evaluated', description: 'No reproducible SatQuery ISRO/SAC evaluation artifact is present.' },
    ],
    notes: 'The EuroSAT model card documents limitations, but no ISRO/SAC labelled evaluation is available here.',
  },
}

export const BenchmarksView: React.FC = () => {
  const { t } = useLanguage()
  const [activeTab, setActiveTab] = useState<BenchmarkTab>('eurosat')
  const [evaluation, setEvaluation] = useState<LandCoverEvaluationReport | null>(null)
  const [evaluationStatus, setEvaluationStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [evaluationError, setEvaluationError] = useState<string | null>(null)
  const [reloadEvaluation, setReloadEvaluation] = useState(0)
  const current = activeTab === 'eurosat' ? null : BENCHMARK_DATA[activeTab]

  useEffect(() => {
    if (activeTab !== 'eurosat') return
    let cancelled = false
    setEvaluationStatus('loading')
    setEvaluationError(null)
    void getLandCoverEvaluation()
      .then((report) => {
        if (cancelled) return
        setEvaluation(report)
        setEvaluationStatus('ready')
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setEvaluation(null)
        setEvaluationError(error instanceof Error ? error.message : 'The model evaluation report could not be loaded.')
        setEvaluationStatus('error')
      })
    return () => { cancelled = true }
  }, [activeTab, reloadEvaluation])

  const eurosatRows = evaluation ? [
    { metric: '10-class accuracy', score: `${(evaluation.results.accuracy_10_class * 100).toFixed(2)}%`, description: 'Reported accuracy on the EuroSAT held-out test split.' },
    { metric: '10-class macro-F1', score: `${(evaluation.results.macro_f1_10_class * 100).toFixed(2)}%`, description: 'Unweighted mean F1 across the ten EuroSAT classes.' },
    { metric: '4-class accuracy', score: `${(evaluation.results.accuracy_4_class * 100).toFixed(2)}%`, description: 'Reported accuracy after grouping classes into four product categories.' },
    { metric: '4-class macro-F1', score: `${(evaluation.results.macro_f1_4_class * 100).toFixed(2)}%`, description: 'Unweighted mean F1 across the four grouped classes.' },
    { metric: 'Expected calibration error', score: evaluation.results.expected_calibration_error.toFixed(4), description: 'Calibration statistic on the EuroSAT test split; not a confidence guarantee for local scenes.' },
    { metric: 'Accuracy with Gaussian noise (SD 0.01)', score: `${(evaluation.results.accuracy_gaussian_noise_sd_0_01 * 100).toFixed(2)}%`, description: 'Reported robustness result for the specified input perturbation.' },
  ] : []

  return (
    <div className="benchmarks-view-container">
      <div className="benchmarks-header">
        <h2>{t('benchmarks.title')}</h2>
        <p>{t('benchmarks.subtitle')}</p>
      </div>

      <div className="benchmarks-card">
        <div className="benchmark-tabs">
          <button type="button" aria-pressed={activeTab === 'eurosat'} className={`benchmark-tab-btn ${activeTab === 'eurosat' ? 'tab-btn-active' : ''}`} onClick={() => setActiveTab('eurosat')}>EuroSAT model</button>
          <button type="button" aria-pressed={activeTab === 'vrsbench'} className={`benchmark-tab-btn ${activeTab === 'vrsbench' ? 'tab-btn-active' : ''}`} onClick={() => setActiveTab('vrsbench')}>VRSBench</button>
          <button type="button" aria-pressed={activeTab === 'rsvqa'} className={`benchmark-tab-btn ${activeTab === 'rsvqa' ? 'tab-btn-active' : ''}`} onClick={() => setActiveTab('rsvqa')}>RSVQA</button>
          <button type="button" aria-pressed={activeTab === 'cdvqa'} className={`benchmark-tab-btn ${activeTab === 'cdvqa' ? 'tab-btn-active' : ''}`} onClick={() => setActiveTab('cdvqa')}>CDVQA</button>
          <button type="button" aria-pressed={activeTab === 'isrosac'} className={`benchmark-tab-btn ${activeTab === 'isrosac' ? 'tab-btn-active' : ''}`} onClick={() => setActiveTab('isrosac')}>ISRO / SAC</button>
        </div>

        {current ? (
          <>
            <div className="benchmark-subinfo">
              <div>
                <h3>{current.title}</h3>
                <span className="dataset-subtitle">{current.subtitle}</span>
              </div>
              <div className="dataset-meta-chips">
                <span className="meta-chip">{t('benchmarks.statusNotEvaluated')}</span>
              </div>
            </div>
            <div className="metrics-table-wrapper">
              <table className="benchmark-metrics-table">
                <thead><tr><th>Metric</th><th>Description</th><th className="score-col">Score</th></tr></thead>
                <tbody>{current.metrics.map((row) => (
                  <tr key={row.metric}>
                    <td className="metric-name"><strong>{row.metric}</strong></td>
                    <td className="metric-desc">{row.description}</td>
                    <td className="metric-score-cell"><span className="score-pill">{row.score}</span></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <div className="benchmark-audit-footer">
              <div className="audit-icon">🛡</div>
              <div className="audit-text"><strong>Verification Protocol:</strong> {current.notes}</div>
            </div>
          </>
        ) : (
          <>
            <div className="benchmark-subinfo">
              <div>
                <h3>EuroSAT land-cover model report</h3>
                <span className="dataset-subtitle">
                  {evaluation ? `${evaluation.test_samples.toLocaleString()} held-out test samples · ${evaluation.source}` : 'Metrics are read from the checked-in model report.'}
                </span>
              </div>
              <div className="dataset-meta-chips"><span className="meta-chip">Reported artifact</span></div>
            </div>
            {evaluationStatus === 'loading' && <p role="status">Loading the checked-in evaluation report…</p>}
            {evaluationStatus === 'error' && (
              <div className="benchmark-audit-footer" role="alert">
                <div className="audit-text">Evaluation report unavailable: {evaluationError} No metric values are shown.</div>
                <button type="button" className="filter-btn" onClick={() => setReloadEvaluation((value) => value + 1)}>Retry</button>
              </div>
            )}
            {evaluationStatus === 'ready' && evaluation && (
              <>
                <div className="metrics-table-wrapper">
                  <table className="benchmark-metrics-table">
                    <thead><tr><th>Metric</th><th>Description</th><th className="score-col">Reported result</th></tr></thead>
                    <tbody>{eurosatRows.map((row) => (
                      <tr key={row.metric}>
                        <td className="metric-name"><strong>{row.metric}</strong></td>
                        <td className="metric-desc">{row.description}</td>
                        <td className="metric-score-cell"><span className="score-pill">{row.score}</span></td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
                <div className="benchmark-audit-footer">
                  <div className="audit-icon">🛡</div>
                  <div className="audit-text">
                    <strong>Scope and limitations:</strong>
                    <ul>{evaluation.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
                  </div>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
