import React, { useState } from 'react'

type BenchmarkTab = 'vrsbench' | 'rsvqa' | 'cdvqa' | 'isrosac'

interface BenchmarkDatasetInfo {
  id: BenchmarkTab
  title: string
  subtitle: string
  metrics: { metric: string; score: string; description: string }[]
  notes: string
}

const BENCHMARK_DATA: Record<BenchmarkTab, BenchmarkDatasetInfo> = {
  vrsbench: {
    id: 'vrsbench',
    title: 'VRSBench',
    subtitle: 'Visual Question Answering & Captioning for Remote Sensing',
    metrics: [
      { metric: 'Evaluation status', score: 'Not evaluated', description: 'No reproducible SatQuery VRSBench evaluation artifact is present.' },
    ],
    notes: 'Published model results are not SatQuery results.',
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
  const [activeTab, setActiveTab] = useState<BenchmarkTab>('vrsbench')
  const current = BENCHMARK_DATA[activeTab]

  return (
    <div className="benchmarks-view-container">
      <div className="benchmarks-header">
        <h2>Evaluation & Benchmarks</h2>
        <p>Reproducible benchmark results will appear here only after the datasets, protocol, outputs, and evaluation artifacts are checked in.</p>
      </div>

      <div className="benchmarks-card">
        {/* Tabs */}
        <div className="benchmark-tabs">
          <button
            type="button"
            className={`benchmark-tab-btn ${activeTab === 'vrsbench' ? 'tab-btn-active' : ''}`}
            onClick={() => setActiveTab('vrsbench')}
          >
            VRSBench
          </button>
          <button
            type="button"
            className={`benchmark-tab-btn ${activeTab === 'rsvqa' ? 'tab-btn-active' : ''}`}
            onClick={() => setActiveTab('rsvqa')}
          >
            RSVQA
          </button>
          <button
            type="button"
            className={`benchmark-tab-btn ${activeTab === 'cdvqa' ? 'tab-btn-active' : ''}`}
            onClick={() => setActiveTab('cdvqa')}
          >
            CDVQA
          </button>
          <button
            type="button"
            className={`benchmark-tab-btn ${activeTab === 'isrosac' ? 'tab-btn-active' : ''}`}
            onClick={() => setActiveTab('isrosac')}
          >
            ISRO / SAC
          </button>
        </div>

        {/* Details Header */}
        <div className="benchmark-subinfo">
          <div>
            <h3>{current.title}</h3>
            <span className="dataset-subtitle">{current.subtitle}</span>
          </div>
          <div className="dataset-meta-chips">
            <span className="meta-chip">Status: Not evaluated</span>
          </div>
        </div>

        {/* Metrics Table matching Reference Panel 12 */}
        <div className="metrics-table-wrapper">
          <table className="benchmark-metrics-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Description</th>
                <th className="score-col">Score</th>
              </tr>
            </thead>
            <tbody>
              {current.metrics.map((row) => (
                <tr key={row.metric}>
                  <td className="metric-name"><strong>{row.metric}</strong></td>
                  <td className="metric-desc">{row.description}</td>
                  <td className="metric-score-cell">
                    <span className="score-pill">{row.score}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Verification Note */}
        <div className="benchmark-audit-footer">
          <div className="audit-icon">🛡</div>
          <div className="audit-text">
            <strong>Verification Protocol:</strong> {current.notes}
          </div>
        </div>
      </div>
    </div>
  )
}
